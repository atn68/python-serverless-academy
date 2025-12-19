"""IdempotencyManager for handling idempotent operations."""

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import ClientError

from .constants import Status
from .utils import calculate_sha256, format_pk


class IdempotencyError(Exception):
    pass


class MissingIdempotencyKeyError(IdempotencyError):
    pass


class IdempotencyConflictError(IdempotencyError):
    pass


class IdempotencyInProgressError(IdempotencyError):
    pass


@dataclass
class IdempotencyResult:
    is_replay: bool
    cached_response: dict = field(default=None)
    response: dict = field(default=None, repr=False)


class IdempotencyManager:
    DEFAULT_TTL_SECONDS = 86400

    def __init__(
        self,
        table_name,
        pk_prefix,
        region_name="us-east-1",
        ttl_seconds=DEFAULT_TTL_SECONDS,
    ):
        self.table = boto3.resource("dynamodb", region_name=region_name).Table(
            table_name
        )
        self.pk_prefix = pk_prefix
        self.ttl_seconds = ttl_seconds

    @contextmanager
    def idempotent(self, idem_key, request_body):
        if not idem_key:
            raise MissingIdempotencyKeyError("Idempotency key is required")

        request_hash = calculate_sha256(request_body)
        pk = format_pk(idem_key, self.pk_prefix)

        existing = self._get_record(pk)
        if existing:
            yield self._handle_existing(existing, request_hash)
            return

        try:
            self._create_record(pk, request_hash)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                existing = self._get_record(pk, consistent_read=True)
                if existing:
                    yield self._handle_existing(existing, request_hash)
                    return
            raise

        result = IdempotencyResult(is_replay=False)
        try:
            yield result
            self._complete(pk, result.response)
        except Exception:
            self._delete_record(pk)
            raise

    def _create_record(self, pk, request_hash):
        self.table.put_item(
            Item={
                "IdempotencyKey": pk,
                "RequestHash": request_hash,
                "Status": Status.IN_PROGRESS,
                "TimeToLive": int(time.time()) + self.ttl_seconds,
            },
            ConditionExpression="attribute_not_exists(IdempotencyKey)",
        )

    def _complete(self, pk, response):
        self.table.update_item(
            Key={"IdempotencyKey": pk},
            UpdateExpression="SET #s = :s, ResponseBody = :r",
            ExpressionAttributeNames={"#s": "Status"},
            ExpressionAttributeValues={
                ":s": Status.COMPLETED,
                ":r": json.dumps(response),
            },
        )

    def _delete_record(self, pk):
        self.table.delete_item(Key={"IdempotencyKey": pk})

    def _get_record(self, pk, consistent_read=False):
        return self.table.get_item(
            Key={"IdempotencyKey": pk},
            ConsistentRead=consistent_read,
        ).get("Item")

    def _handle_existing(self, item, request_hash):
        if item["RequestHash"] != request_hash:
            raise IdempotencyConflictError(
                "Idempotency key used with different payload"
            )

        if item["Status"] == Status.IN_PROGRESS:
            raise IdempotencyInProgressError("Transaction already in progress")

        return IdempotencyResult(
            is_replay=True,
            cached_response=json.loads(item["ResponseBody"]),
        )
