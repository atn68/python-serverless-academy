"""Tests for channel strategies."""

import pytest
from notification_lib import ChannelType, EmailStrategy, SmsStrategy, create_strategy


class TestEmailStrategy:
    """Tests for EmailStrategy."""

    def test_send_email_success(self):
        """Test successful email send (mock implementation)."""
        strategy = EmailStrategy(
            region_name="us-east-1",
            sender_email="sender@example.com",
        )

        result = strategy.send(
            recipient="user@example.com",
            subject="Test Subject",
            message="Test message body",
        )

        assert result["channel"] == ChannelType.EMAIL
        assert "message_id" in result

    def test_channel_type(self):
        """Test channel type property."""
        strategy = EmailStrategy(region_name="us-east-1")
        assert strategy.channel_type == ChannelType.EMAIL


class TestSmsStrategy:
    """Tests for SmsStrategy."""

    def test_send_sms_success(self):
        """Test successful SMS send (mock implementation)."""
        strategy = SmsStrategy(region_name="us-east-1")

        result = strategy.send(
            recipient="+1234567890",
            subject="",
            message="Test SMS message",
        )

        assert result["channel"] == ChannelType.SMS
        assert "message_id" in result

    def test_channel_type(self):
        """Test channel type property."""
        strategy = SmsStrategy(region_name="us-east-1")
        assert strategy.channel_type == ChannelType.SMS

    def test_mask_phone(self):
        """Test phone number masking."""
        assert SmsStrategy._mask_phone("+1234567890") == "******7890"
        assert SmsStrategy._mask_phone("+123") == "****"


class TestCreateStrategy:
    """Tests for strategy factory function."""

    def test_create_email_strategy(self):
        """Test creating email strategy."""
        strategy = create_strategy(
            ChannelType.EMAIL,
            region_name="us-east-1",
            sender_email="test@example.com",
        )
        assert isinstance(strategy, EmailStrategy)
        assert strategy.sender_email == "test@example.com"

    def test_create_sms_strategy(self):
        """Test creating SMS strategy."""
        strategy = create_strategy(
            ChannelType.SMS,
            region_name="us-east-1",
            sender_id="MyApp",
        )
        assert isinstance(strategy, SmsStrategy)
        assert strategy.sender_id == "MyApp"

    def test_create_invalid_strategy(self):
        """Test creating strategy with invalid type."""
        with pytest.raises(ValueError) as exc_info:
            create_strategy("INVALID")

        assert "Unsupported channel type" in str(exc_info.value)
