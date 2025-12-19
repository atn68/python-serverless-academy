"""NotificationManager for handling notification lifecycle."""

import base64
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .constants import ChannelType, NotificationStatus, Priority
from .exceptions import NotificationError
from .strategies import create_strategy

logger = logging.getLogger(__name__)


@dataclass
class NotificationResult:
    success: bool
    notification_id: str | None = None
    message_id: str | None = None
    channel: str | None = None
    error: str | None = None
    retry: bool = False


class DataKeyCache:
    DEFAULT_MAX_AGE_SECONDS = 300
    DEFAULT_MAX_ENCRYPTIONS = 1000

    def __init__(self, max_age_seconds=None, max_encryptions=None):
        self.max_age_seconds = max_age_seconds or self.DEFAULT_MAX_AGE_SECONDS
        self.max_encryptions = max_encryptions or self.DEFAULT_MAX_ENCRYPTIONS
        self._plaintext_key = None
        self._encrypted_key = None
        self._created_at = None
        self._encryption_count = 0
        self._decrypt_cache = {}
        self._decrypt_cache_max_size = 100

    def get_encrypt_key(self, kms_client, key_id):
        if self._should_refresh():
            self._generate_new_key(kms_client, key_id)
        self._encryption_count += 1
        return self._plaintext_key, self._encrypted_key

    def get_decrypt_key(self, kms_client, encrypted_key):
        encrypted_key_b64 = base64.b64encode(encrypted_key).decode("utf-8")

        if encrypted_key_b64 in self._decrypt_cache:
            return self._decrypt_cache[encrypted_key_b64]

        response = kms_client.decrypt(CiphertextBlob=encrypted_key)
        plaintext_key = response["Plaintext"]

        if len(self._decrypt_cache) >= self._decrypt_cache_max_size:
            oldest_key = next(iter(self._decrypt_cache))
            del self._decrypt_cache[oldest_key]
        self._decrypt_cache[encrypted_key_b64] = plaintext_key

        return plaintext_key

    def _should_refresh(self):
        if not self._plaintext_key:
            return True
        if time.time() - self._created_at > self.max_age_seconds:
            return True
        if self._encryption_count >= self.max_encryptions:
            return True
        return False

    def _generate_new_key(self, kms_client, key_id):
        response = kms_client.generate_data_key(KeyId=key_id, KeySpec="AES_256")
        self._plaintext_key = response["Plaintext"]
        self._encrypted_key = response["CiphertextBlob"]
        self._created_at = time.time()
        self._encryption_count = 0


_data_key_cache = DataKeyCache()


class NotificationManager:
    DEFAULT_TTL_SECONDS = 86400 * 30
    NONCE_SIZE = 12

    def __init__(
        self,
        notification_table_name,
        notification_register_table_name,
        kms_key_id,
        region_name="us-east-1",
        ttl_seconds=None,
        email_config=None,
        sms_config=None,
        data_key_cache=None,
    ):
        dynamodb = boto3.resource("dynamodb", region_name=region_name)
        self.notification_table = dynamodb.Table(notification_table_name)
        self.notification_register_table = dynamodb.Table(
            notification_register_table_name
        )
        self.kms_client = boto3.client("kms", region_name=region_name)
        self.kms_key_id = kms_key_id
        self.ttl_seconds = ttl_seconds or self.DEFAULT_TTL_SECONDS
        self._data_key_cache = data_key_cache or _data_key_cache

        self._strategies = {}
        if email_config:
            self._strategies[ChannelType.EMAIL] = create_strategy(
                ChannelType.EMAIL, **email_config
            )
        if sms_config:
            self._strategies[ChannelType.SMS] = create_strategy(
                ChannelType.SMS, **sms_config
            )

    def _encrypt(self, plaintext):
        plaintext_key, encrypted_key = self._data_key_cache.get_encrypt_key(
            self.kms_client, self.kms_key_id
        )
        nonce = os.urandom(self.NONCE_SIZE)
        aesgcm = AESGCM(plaintext_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

        envelope = {
            "k": base64.b64encode(encrypted_key).decode("utf-8"),
            "n": base64.b64encode(nonce).decode("utf-8"),
            "c": base64.b64encode(ciphertext).decode("utf-8"),
        }
        return base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("utf-8")

    def _decrypt(self, ciphertext_b64):
        envelope = json.loads(base64.b64decode(ciphertext_b64))
        encrypted_key = base64.b64decode(envelope["k"])
        nonce = base64.b64decode(envelope["n"])
        ciphertext = base64.b64decode(envelope["c"])

        plaintext_key = self._data_key_cache.get_decrypt_key(
            self.kms_client, encrypted_key
        )
        aesgcm = AESGCM(plaintext_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        return plaintext.decode("utf-8")

    def get_strategy(self, channel_type):
        return self._strategies.get(channel_type)

    def create_notification(
        self,
        user_id,
        primary_channel,
        recipient,
        subject,
        message,
        priority=Priority.NORMAL,
        fallback_channel=None,
        metadata=None,
    ):
        notification_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        ttl = int(time.time()) + self.ttl_seconds

        pk = f"USER#{user_id}"
        sk = f"NOTI#{notification_id}"
        gsi1pk = f"STATUS#{NotificationStatus.CREATED}"

        item = {
            "PK": pk,
            "SK": sk,
            "GSI1PK": gsi1pk,
            "NotificationId": notification_id,
            "UserId": user_id,
            "Status": NotificationStatus.CREATED,
            "Priority": priority,
            "Channel": primary_channel,
            "FallbackChannel": fallback_channel,
            "Content": {"subject": subject, "message": self._encrypt(message)},
            "Recipient": recipient,
            "EventVersion": 1,
            "CreatedAt": timestamp,
            "TimeToLive": ttl,
        }

        if metadata:
            item["Metadata"] = metadata

        item = {k: v for k, v in item.items() if v is not None}

        try:
            self.notification_table.put_item(Item=item)
            logger.info("Created notification: %s", notification_id)
            return item
        except ClientError as e:
            logger.error("Failed to create notification: %s", e)
            raise

    def get_user_preferences(self, user_id):
        pk = f"USER#{user_id}"

        try:
            response = self.notification_register_table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
                ExpressionAttributeValues={
                    ":pk": pk,
                    ":sk_prefix": "ADDR#",
                },
            )
            items = response.get("Items", [])

            preferences = []
            for item in items:
                sk = item.get("SK", "")
                channel = sk.replace("ADDR#", "") if sk.startswith("ADDR#") else None
                if channel:
                    preferences.append(
                        {
                            "Channel": channel,
                            "Address": item.get("Value"),
                            "Verified": item.get("Verified", False),
                        }
                    )

            return preferences
        except ClientError as e:
            logger.error("Failed to get user preferences for %s: %s", user_id, e)
            raise

    def get_notification(self, notification_id):
        try:
            response = self.notification_table.query(
                IndexName="NotificationIdIndex",
                KeyConditionExpression="NotificationId = :nid",
                ExpressionAttributeValues={":nid": notification_id},
                Limit=1,
            )
            items = response.get("Items", [])
            if not items:
                raise NotificationError(f"Notification {notification_id} not found")
            return items[0]
        except ClientError as e:
            logger.error("Failed to get notification %s: %s", notification_id, e)
            raise

    def update_status(self, notification, status):
        pk = notification["PK"]
        sk = notification["SK"]
        current_version = notification["EventVersion"]
        new_gsi1pk = f"STATUS#{status}"

        response = self.notification_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET #status = :status, #gsi1pk = :gsi1pk, #version = :new_version",
            ConditionExpression="#version = :current_version",
            ExpressionAttributeNames={
                "#status": "Status",
                "#gsi1pk": "GSI1PK",
                "#version": "EventVersion",
            },
            ExpressionAttributeValues={
                ":status": status,
                ":gsi1pk": new_gsi1pk,
                ":current_version": current_version,
                ":new_version": current_version + 1,
            },
            ReturnValues="ALL_NEW",
        )
        return response.get("Attributes", {})

    def send_notification(self, notification_id) -> NotificationResult:
        try:
            notification = self.get_notification(notification_id)
        except Exception as e:
            logger.error("Failed to get notification %s: %s", notification_id, e)
            return NotificationResult(
                success=False,
                notification_id=notification_id,
                error=f"Notification not found: {notification_id}",
                retry=False,
            )

        channel = notification["Channel"]
        recipient = notification["Recipient"]
        content = notification.get("Content", {})
        subject = content.get("subject", "")
        encrypted_message = content.get("message", "")
        message = self._decrypt(encrypted_message) if encrypted_message else ""

        strategy = self.get_strategy(channel)
        if not strategy:
            logger.error("Channel not configured: %s", channel)
            return NotificationResult(
                success=False,
                notification_id=notification_id,
                error=f"Channel {channel} not configured",
                retry=False,
            )

        try:
            notification = self.update_status(
                notification, NotificationStatus.PROCESSING
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.info("Notification %s already being processed", notification_id)
                return NotificationResult(
                    success=False,
                    notification_id=notification_id,
                    error="Already being processed by another worker",
                    retry=False,
                )
            raise

        try:
            result = strategy.send(recipient, subject, message)
            self.update_status(notification, NotificationStatus.COMPLETED)
            return NotificationResult(
                success=True,
                notification_id=notification_id,
                message_id=result.get("message_id"),
                channel=channel,
            )
        except Exception as e:
            logger.error("Failed to send notification %s: %s", notification_id, e)
            self.update_status(notification, NotificationStatus.FAILED)
            return NotificationResult(
                success=False,
                notification_id=notification_id,
                channel=channel,
                error=str(e),
                retry=True,
            )
