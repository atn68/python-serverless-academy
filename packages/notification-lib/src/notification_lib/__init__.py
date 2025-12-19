"""Notification library for AWS Lambda."""

from .constants import (
    ChannelType,
    NotificationRegisterAddressType,
    NotificationStatus,
    Priority,
)
from .exceptions import NotificationError
from .manager import DataKeyCache, NotificationManager, NotificationResult
from .strategies import EmailStrategy, SmsStrategy, create_strategy

__all__ = [
    # Manager
    "NotificationManager",
    "NotificationResult",
    "DataKeyCache",
    # Strategies
    "EmailStrategy",
    "SmsStrategy",
    "create_strategy",
    # Constants
    "ChannelType",
    "NotificationRegisterAddressType",
    "NotificationStatus",
    "Priority",
    # Exceptions
    "NotificationError",
]
