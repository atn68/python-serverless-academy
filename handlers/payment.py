import json
import os
import time

from idempotency_lib import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyManager,
    MissingIdempotencyKeyError,
)

manager = IdempotencyManager(
    table_name=os.environ["IDEMPOTENCY_TABLE_NAME"],
    pk_prefix=os.environ["IDEMPOTENCY_PK_PREFIX"],
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    ttl_seconds=int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", 86400)),
)


def payment_handler(event, context):
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    idem_key = headers.get("idempotency-key")

    if not idem_key:
        return _error(400, "Missing Idempotency-Key header")

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _error(400, "Invalid JSON body")

    try:
        with manager.idempotent(idem_key, body) as result:
            if result.is_replay:
                return _success(result.cached_response, replay=True)
            result.response = _process_payment(body)
            return _success(result.response)
    except MissingIdempotencyKeyError:
        return _error(400, "Missing Idempotency-Key header")
    except IdempotencyConflictError:
        return _error(409, "Idempotency key used with different payload")
    except IdempotencyInProgressError:
        return _error(409, "Transaction already in progress")
    except Exception:
        return _error(500, "Internal server error")


def _process_payment(body):
    return {
        "transaction_id": f"TXN-{int(time.time())}",
        "amount": body.get("amount"),
        "currency": body.get("currency"),
        "status": "SUCCESS",
    }


def _success(body, replay=False):
    headers = {"Content-Type": "application/json"}
    if replay:
        headers["X-Idempotency-Replay"] = "true"
    return {"statusCode": 201, "headers": headers, "body": json.dumps(body)}


def _error(status_code, message):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }
