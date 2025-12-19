"""Channel strategies for sending notifications (mock implementation)."""

import logging
import uuid

from .constants import ChannelType

logger = logging.getLogger(__name__)


class EmailStrategy:
    """Email channel strategy (mock implementation - logs only)."""

    channel_type = ChannelType.EMAIL

    def __init__(self, sender_email=None):
        self.sender_email = sender_email

    def send(self, recipient, subject, message, **kwargs):
        """Mock send email - logs the notification details."""
        message_id = str(uuid.uuid4())

        logger.info(
            "[MOCK] Email sent: to=%s, subject=%s",
            recipient,
            subject,
        )

        return {"message_id": message_id, "channel": self.channel_type}


class SmsStrategy:
    """SMS channel strategy (mock implementation - logs only)."""

    channel_type = ChannelType.SMS

    def __init__(self, region_name=None, sender_id=None, sms_type=None):
        self.sender_id = sender_id

    def send(self, recipient, subject, message, **kwargs):
        """Mock send SMS - logs the notification details."""
        message_id = str(uuid.uuid4())

        logger.info(
            "[MOCK] SMS sent: to=%s, message=%s",
            self._mask_phone(recipient),
            message[:50] if message else "",
        )

        return {"message_id": message_id, "channel": self.channel_type}

    @staticmethod
    def _mask_phone(phone):
        """Mask phone number for logging."""
        if len(phone) > 4:
            return "*" * (len(phone) - 4) + phone[-4:]
        return "****"


def create_strategy(channel_type, **kwargs):
    """
    Factory function to create channel strategy.

    Args:
        channel_type: ChannelType.EMAIL or ChannelType.SMS
        **kwargs: Channel-specific configuration

    Returns:
        Configured ChannelStrategy instance

    Raises:
        ValueError: If channel_type is not supported
    """
    strategies = {
        ChannelType.EMAIL: EmailStrategy,
        ChannelType.SMS: SmsStrategy,
    }

    strategy_class = strategies.get(channel_type)
    if not strategy_class:
        raise ValueError(f"Unsupported channel type: {channel_type}")

    return strategy_class(**kwargs)
