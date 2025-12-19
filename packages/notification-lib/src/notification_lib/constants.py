"""Constants for notification library."""


class NotificationStatus:
    """Notification processing status."""

    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ChannelType:
    """Notification delivery channels."""

    EMAIL = "EMAIL"
    SMS = "SMS"


class NotificationRegisterAddressType:
    """NotificationRegister address types."""

    EMAIL = "EMAIL"
    PHONE = "PHONE"


class Priority:
    """Notification priority levels."""

    HIGH = "HIGH"  # -> Standard Queue (high throughput)
    NORMAL = "NORMAL"  # -> FIFO Queue (ordered by user)
