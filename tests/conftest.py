"""Pytest configuration - sets up environment variables before test collection."""

import os

# Set required environment variables before any module imports
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")

# Idempotency settings (uses AWS owned key - no KMS key needed)
os.environ.setdefault("IDEMPOTENCY_TABLE_NAME", "IdempotencyStore")
os.environ.setdefault("IDEMPOTENCY_PK_PREFIX", "TEST#IDEM")
os.environ.setdefault("IDEMPOTENCY_TTL_SECONDS", "86400")

# Notification settings (uses customer managed KMS key)
os.environ.setdefault("NOTIFICATION_TABLE_NAME", "Notification")
os.environ.setdefault("NOTIFICATION_REGISTER_TABLE_NAME", "NotificationRegister")
os.environ.setdefault("NOTIFICATION_KMS_KEY_ID", "alias/notification-test-key")
os.environ.setdefault("NOTIFICATION_TTL_SECONDS", "2592000")
os.environ.setdefault("NOTIFICATION_EVENT_BUS_NAME", "test-event-bus")
os.environ.setdefault("SENDER_EMAIL", "sender@example.com")
os.environ.setdefault("SMS_SENDER_ID", "TestApp")
