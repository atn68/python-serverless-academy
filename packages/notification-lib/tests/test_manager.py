"""Tests for NotificationManager."""

import boto3
import pytest
from moto import mock_aws
from notification_lib import (
    ChannelType,
    DataKeyCache,
    NotificationError,
    NotificationManager,
    NotificationStatus,
    Priority,
)


@pytest.fixture
def mock_aws_services():
    """Create mock AWS services."""
    with mock_aws():
        # Create DynamoDB tables
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        notification_table = dynamodb.create_table(
            TableName="Notification",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "NotificationId", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "NotificationIdIndex",
                    "KeySchema": [
                        {"AttributeName": "NotificationId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        register_table = dynamodb.create_table(
            TableName="NotificationRegister",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Create KMS key
        kms = boto3.client("kms", region_name="us-east-1")
        key_response = kms.create_key(Description="Test key")
        kms_key_id = key_response["KeyMetadata"]["KeyId"]

        yield {
            "notification_table": notification_table,
            "register_table": register_table,
            "kms_key_id": kms_key_id,
            "kms_client": kms,
        }


@pytest.fixture
def manager(mock_aws_services):
    """Create NotificationManager with mock AWS and fresh cache."""
    # Use a fresh cache for each test
    cache = DataKeyCache()
    return NotificationManager(
        notification_table_name="Notification",
        notification_register_table_name="NotificationRegister",
        kms_key_id=mock_aws_services["kms_key_id"],
        region_name="us-east-1",
        email_config={"sender_email": "sender@example.com"},
        sms_config={"sender_id": "TestApp"},
        data_key_cache=cache,
    )


class TestDataKeyCache:
    """Tests for DataKeyCache."""

    def test_generates_key_on_first_use(self, mock_aws_services):
        """Test that cache generates key on first encryption."""
        cache = DataKeyCache()
        kms_client = mock_aws_services["kms_client"]
        key_id = mock_aws_services["kms_key_id"]

        plaintext_key, encrypted_key = cache.get_encrypt_key(kms_client, key_id)

        assert plaintext_key is not None
        assert encrypted_key is not None
        assert len(plaintext_key) == 32  # AES-256

    def test_reuses_cached_key(self, mock_aws_services):
        """Test that cache reuses key within limits."""
        cache = DataKeyCache()
        kms_client = mock_aws_services["kms_client"]
        key_id = mock_aws_services["kms_key_id"]

        key1, _ = cache.get_encrypt_key(kms_client, key_id)
        key2, _ = cache.get_encrypt_key(kms_client, key_id)

        assert key1 == key2

    def test_caches_decrypted_keys(self, mock_aws_services):
        """Test that decrypted keys are cached."""
        cache = DataKeyCache()
        kms_client = mock_aws_services["kms_client"]
        key_id = mock_aws_services["kms_key_id"]

        _, encrypted_key = cache.get_encrypt_key(kms_client, key_id)

        # First decrypt
        decrypted1 = cache.get_decrypt_key(kms_client, encrypted_key)
        # Second decrypt should use cache
        decrypted2 = cache.get_decrypt_key(kms_client, encrypted_key)

        assert decrypted1 == decrypted2


class TestNotificationManager:
    """Tests for NotificationManager."""

    def test_create_notification(self, manager):
        """Test creating a new notification."""
        notification = manager.create_notification(
            user_id="user123",
            primary_channel=ChannelType.EMAIL,
            recipient="user@example.com",
            subject="Test Subject",
            message="Test message",
        )

        assert "NotificationId" in notification
        assert notification["UserId"] == "user123"
        assert notification["Channel"] == ChannelType.EMAIL
        assert notification["Status"] == NotificationStatus.CREATED

    def test_create_notification_encrypts_message(self, manager):
        """Test that message is encrypted in notification."""
        notification = manager.create_notification(
            user_id="user123",
            primary_channel=ChannelType.EMAIL,
            recipient="user@example.com",
            subject="Test Subject",
            message="Secret message",
        )

        # Message should be encrypted (not plaintext)
        encrypted_message = notification["Content"]["message"]
        assert encrypted_message != "Secret message"
        assert "Secret" not in encrypted_message

    def test_encrypt_decrypt_round_trip(self, manager):
        """Test that encryption and decryption work correctly."""
        original = "Hello, World! This is a test message."
        encrypted = manager._encrypt(original)
        decrypted = manager._decrypt(encrypted)

        assert decrypted == original

    def test_create_notification_high_priority(self, manager):
        """Test creating high priority notification."""
        notification = manager.create_notification(
            user_id="user123",
            primary_channel=ChannelType.EMAIL,
            recipient="user@example.com",
            subject="Urgent",
            message="Urgent message",
            priority=Priority.HIGH,
        )

        assert notification["Priority"] == Priority.HIGH

    def test_get_notification(self, manager):
        """Test retrieving a notification."""
        created = manager.create_notification(
            user_id="user123",
            primary_channel=ChannelType.EMAIL,
            recipient="user@example.com",
            subject="Test",
            message="Test message",
        )

        retrieved = manager.get_notification(created["NotificationId"])

        assert retrieved["NotificationId"] == created["NotificationId"]
        assert retrieved["UserId"] == "user123"

    def test_get_notification_not_found(self, manager):
        """Test retrieving non-existent notification."""
        with pytest.raises(NotificationError):
            manager.get_notification("non-existent-id")

    def test_update_status(self, manager):
        """Test updating notification status."""
        notification = manager.create_notification(
            user_id="user123",
            primary_channel=ChannelType.EMAIL,
            recipient="user@example.com",
            subject="Test",
            message="Test message",
        )

        updated = manager.update_status(notification, NotificationStatus.PROCESSING)

        assert updated["Status"] == NotificationStatus.PROCESSING
        assert updated["EventVersion"] == 2

    def test_get_user_preferences(self, manager, mock_aws_services):
        """Test getting user preferences."""
        # Add test preferences
        mock_aws_services["register_table"].put_item(
            Item={
                "PK": "USER#user123",
                "SK": "ADDR#EMAIL",
                "Value": "user@example.com",
                "Verified": True,
            }
        )
        mock_aws_services["register_table"].put_item(
            Item={
                "PK": "USER#user123",
                "SK": "ADDR#PHONE",
                "Value": "+1234567890",
                "Verified": True,
            }
        )

        preferences = manager.get_user_preferences("user123")

        assert len(preferences) == 2
        channels = [p["Channel"] for p in preferences]
        assert "EMAIL" in channels
        assert "PHONE" in channels

    def test_send_notification_success(self, manager):
        """Test successful notification send."""
        notification = manager.create_notification(
            user_id="user123",
            primary_channel=ChannelType.EMAIL,
            recipient="user@example.com",
            subject="Test Subject",
            message="Test message body",
        )

        result = manager.send_notification(notification["NotificationId"])

        assert result.success
        assert result.channel == ChannelType.EMAIL
        assert result.message_id is not None

    def test_send_notification_decrypts_message(self, manager, mocker):
        """Test that send_notification correctly decrypts the message."""
        original_message = "This is the secret message"

        notification = manager.create_notification(
            user_id="user123",
            primary_channel=ChannelType.EMAIL,
            recipient="user@example.com",
            subject="Test",
            message=original_message,
        )

        # Mock the strategy to capture the decrypted message
        mock_strategy = mocker.MagicMock()
        mock_strategy.send.return_value = {"message_id": "test-id"}
        manager._strategies[ChannelType.EMAIL] = mock_strategy

        manager.send_notification(notification["NotificationId"])

        # Verify the decrypted message was passed to strategy
        mock_strategy.send.assert_called_once()
        call_args = mock_strategy.send.call_args
        assert call_args[0][2] == original_message  # Third arg is message

    def test_send_notification_not_found(self, manager):
        """Test sending non-existent notification."""
        result = manager.send_notification("non-existent-id")

        assert not result.success
        assert not result.retry
        assert "not found" in result.error
