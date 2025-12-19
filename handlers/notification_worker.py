"""Notification Worker Handler."""

import json
import logging
import os

from notification_lib import NotificationManager

logger = logging.getLogger()
logger.setLevel(logging.INFO)

notification_manager = NotificationManager(
    notification_table_name=os.environ["NOTIFICATION_TABLE_NAME"],
    notification_register_table_name=os.environ["NOTIFICATION_REGISTER_TABLE_NAME"],
    kms_key_id=os.environ["NOTIFICATION_KMS_KEY_ID"],
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    email_config={"sender_email": os.environ.get("SENDER_EMAIL")},
    sms_config={"sender_id": os.environ.get("SMS_SENDER_ID")},
)


def notification_worker_handler(event, context):
    batch_item_failures = []
    records = event.get("Records", [])

    logger.info("Processing %d records", len(records))

    for record in records:
        message_id = record.get("messageId", "unknown")

        try:
            result = _process_record(record)
            if not result["success"] and result.get("retry"):
                batch_item_failures.append({"itemIdentifier": message_id})

        except Exception as e:
            logger.exception("Error processing record %s: %s", message_id, e)
            batch_item_failures.append({"itemIdentifier": message_id})

    if batch_item_failures:
        logger.info("Batch: %d failed of %d", len(batch_item_failures), len(records))

    return {"batchItemFailures": batch_item_failures}


def _process_record(record):
    try:
        body = json.loads(record.get("body", "{}"))
        if "detail" in body:
            notification_id = body["detail"].get("notification_id")
        else:
            notification_id = body.get("notification_id")
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON: %s", e)
        return {"success": False, "retry": False}

    if not notification_id:
        logger.error("Missing notification_id")
        return {"success": False, "retry": False}

    result = notification_manager.send_notification(notification_id)

    if result.success:
        logger.info("Sent: %s via %s", notification_id, result.channel)
        return {"success": True}

    logger.error("Send failed: %s - %s", notification_id, result.error)
    return {"success": False, "retry": result.retry}
