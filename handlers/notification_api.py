"""Notification API Handler."""

import json
import logging
import os

import boto3
from idempotency_lib import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyManager,
    calculate_sha256,
)
from notification_lib import (
    ChannelType,
    NotificationError,
    NotificationManager,
    NotificationRegisterAddressType,
    NotificationStatus,
    Priority,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

idempotency_manager = IdempotencyManager(
    table_name=os.environ["IDEMPOTENCY_TABLE_NAME"],
    pk_prefix=os.environ["IDEMPOTENCY_PK_PREFIX"],
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    ttl_seconds=int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", 86400)),
)

notification_manager = NotificationManager(
    notification_table_name=os.environ["NOTIFICATION_TABLE_NAME"],
    notification_register_table_name=os.environ["NOTIFICATION_REGISTER_TABLE_NAME"],
    kms_key_id=os.environ["NOTIFICATION_KMS_KEY_ID"],
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    ttl_seconds=int(os.environ.get("NOTIFICATION_TTL_SECONDS", 86400 * 30)),
)

eventbridge = boto3.client(
    "events",
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)
NOTIFICATION_EVENT_BUS_NAME = os.environ["NOTIFICATION_EVENT_BUS_NAME"]


def notification_api_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _error(400, "Invalid JSON body")

    validation_error = _validate_request(body)
    if validation_error:
        return _error(400, validation_error)

    idem_key = calculate_sha256(body)
    user_id = body.get("user_id")
    message = body.get("message")
    subject = body.get("subject", "")
    priority = body.get("priority", Priority.NORMAL).upper()

    try:
        with idempotency_manager.idempotent(idem_key, body) as result:
            if result.is_replay:
                logger.info("Idempotent replay: %s", idem_key[:8])
                return _success(result.cached_response, replay=True)

            created_notifications = _create_notifications(
                user_id=user_id,
                subject=subject,
                message=message,
                priority=priority,
            )
            _publish_events(created_notifications)

            notification_ids = [n["NotificationId"] for n in created_notifications]
            response_body = {
                "notification_ids": notification_ids,
                "status": NotificationStatus.CREATED,
            }
            result.response = response_body

            return _success(response_body)

    except IdempotencyConflictError:
        logger.warning("Idempotency conflict: %s", idem_key[:8])
        return _error(409, "Idempotency key used with different payload")

    except IdempotencyInProgressError:
        logger.warning("Request in progress: %s", idem_key[:8])
        return _error(409, "Request already in progress")

    except NotificationError as e:
        logger.warning("Notification error: %s", e)
        return _error(400, str(e))

    except Exception as e:
        logger.exception("Error creating notification: %s", e)
        return _error(500, "Internal server error")


def _validate_request(body):
    required_fields = ["user_id", "message"]

    for field in required_fields:
        if not body.get(field):
            return f"Missing required field: {field}"

    priority = body.get("priority", "").upper()
    if priority and priority not in [Priority.HIGH, Priority.NORMAL]:
        return f"Invalid priority: {priority}. Must be HIGH or NORMAL"

    return None


def _create_notifications(user_id, subject, message, priority):
    preferences = notification_manager.get_user_preferences(user_id)
    verified_prefs = [p for p in preferences if p["Verified"]]

    if not verified_prefs:
        raise NotificationError(f"No verified channels found for user {user_id}")

    pref_to_channel = {
        NotificationRegisterAddressType.EMAIL: ChannelType.EMAIL,
        NotificationRegisterAddressType.PHONE: ChannelType.SMS,
    }

    created_notifications = []
    for pref in verified_prefs:
        channel = pref_to_channel.get(pref["Channel"])
        recipient = pref["Address"]

        try:
            notification = notification_manager.create_notification(
                user_id=user_id,
                primary_channel=channel,
                recipient=recipient,
                subject=subject,
                message=message,
                priority=priority,
            )
            created_notifications.append(notification)
            logger.info(
                "Notification created: %s for channel %s",
                notification["NotificationId"],
                channel,
            )
        except Exception as e:
            logger.error("Failed to create notification for channel %s: %s", channel, e)

    if not created_notifications:
        raise NotificationError(
            f"Failed to create any notifications for user {user_id}"
        )

    return created_notifications


EVENTBRIDGE_MAX_BATCH_SIZE = 10


def _publish_events(notifications):
    if not notifications:
        return

    entries = [
        {
            "Source": "notification.api",
            "DetailType": "NotificationCreated",
            "Detail": json.dumps(
                {
                    "notification_id": n["NotificationId"],
                    "user_id": n["UserId"],
                    "channel": n["Channel"],
                    "priority": n["Priority"],
                }
            ),
            "EventBusName": NOTIFICATION_EVENT_BUS_NAME,
        }
        for n in notifications
    ]

    for i in range(0, len(entries), EVENTBRIDGE_MAX_BATCH_SIZE):
        batch = entries[i : i + EVENTBRIDGE_MAX_BATCH_SIZE]
        batch_notifications = notifications[i : i + EVENTBRIDGE_MAX_BATCH_SIZE]

        try:
            response = eventbridge.put_events(Entries=batch)

            if response.get("FailedEntryCount", 0) > 0:
                logger.error(
                    "EventBridge batch publish partial failure: %d/%d failed",
                    response["FailedEntryCount"],
                    len(batch),
                )
                for j, entry in enumerate(response.get("Entries", [])):
                    if "ErrorCode" in entry:
                        logger.error(
                            "Failed to publish event for notification %s: %s - %s",
                            batch_notifications[j]["NotificationId"],
                            entry["ErrorCode"],
                            entry.get("ErrorMessage", ""),
                        )

        except Exception as e:
            logger.exception("EventBridge batch publish error: %s", e)


def _success(body, replay=False):
    headers = {"Content-Type": "application/json"}
    if replay:
        headers["X-Idempotency-Replay"] = "true"
    return {
        "statusCode": 201,
        "headers": headers,
        "body": json.dumps(body),
    }


def _error(status_code, message):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }
