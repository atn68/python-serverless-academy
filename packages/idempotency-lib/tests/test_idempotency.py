"""Tests for IdempotencyManager."""

import boto3
import pytest
from idempotency_lib import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyManager,
    IdempotencyResult,
    MissingIdempotencyKeyError,
    calculate_sha256,
    format_pk,
)
from moto import mock_aws

PK_PREFIX = "IDEM"


@pytest.fixture
def mock_dynamodb():
    """Create mock DynamoDB table."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="IdempotencyStore",
            KeySchema=[{"AttributeName": "IdempotencyKey", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "IdempotencyKey", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


@pytest.fixture
def manager(mock_dynamodb):
    """Create IdempotencyManager with mock DynamoDB."""
    return IdempotencyManager(
        table_name="IdempotencyStore",
        pk_prefix=PK_PREFIX,
        region_name="us-east-1",
    )


class TestIdempotencyManager:
    """Tests for IdempotencyManager."""

    def test_creates_in_progress_and_completes(self, manager, mock_dynamodb):
        """Test creating and completing an idempotent operation."""
        with manager.idempotent("test-key", {"amount": 100}) as result:
            assert isinstance(result, IdempotencyResult)
            assert result.is_replay is False
            result.response = {"status": "SUCCESS"}

        pk = format_pk("test-key", PK_PREFIX)
        item = mock_dynamodb.get_item(Key={"IdempotencyKey": pk}).get("Item")
        assert item["Status"] == "COMPLETED"

    def test_returns_replay_for_completed_request(self, manager):
        """Test replay for completed request."""
        # First request
        with manager.idempotent("completed-key", {"amount": 100}) as result:
            result.response = {"status": "SUCCESS", "amount": 100}

        # Second request - should be replay
        with manager.idempotent("completed-key", {"amount": 100}) as result:
            assert result.is_replay is True
            assert result.cached_response == {"status": "SUCCESS", "amount": 100}

    def test_raises_conflict_for_different_payload(self, manager):
        """Test conflict error for different payload."""
        with manager.idempotent("existing-key", {"amount": 100}) as result:
            result.response = {"status": "SUCCESS"}

        with pytest.raises(IdempotencyConflictError):
            with manager.idempotent("existing-key", {"amount": 999}):
                pass

    def test_raises_in_progress_error(self, manager, mock_dynamodb, mocker):
        """Test in progress error."""
        pk = format_pk("ongoing-key", PK_PREFIX)
        mock_dynamodb.put_item(
            Item={
                "IdempotencyKey": pk,
                "RequestHash": "some-hash",
                "Status": "IN_PROGRESS",
                "TimeToLive": 9999999999,
            }
        )

        mocker.patch(
            "idempotency_lib.manager.calculate_sha256", return_value="some-hash"
        )

        with pytest.raises(IdempotencyInProgressError):
            with manager.idempotent("ongoing-key", {"amount": 10}):
                pass

    def test_raises_missing_key_error(self, manager):
        """Test missing key error."""
        with pytest.raises(MissingIdempotencyKeyError):
            with manager.idempotent("", {"amount": 100}):
                pass

    def test_deletes_record_on_exception(self, manager, mock_dynamodb):
        """Test record deletion on exception."""
        pk = format_pk("error-key", PK_PREFIX)

        with pytest.raises(ValueError):
            with manager.idempotent("error-key", {"amount": 100}):
                raise ValueError("Processing failed")

        item = mock_dynamodb.get_item(Key={"IdempotencyKey": pk}).get("Item")
        assert item is None


class TestUtils:
    """Tests for utility functions."""

    def test_format_pk(self):
        """Test partition key formatting."""
        assert format_pk("key123", "PREFIX") == "PREFIX#key123"

    def test_calculate_sha256_deterministic(self):
        """Test SHA256 is deterministic."""
        data = {"b": 2, "a": 1}
        hash1 = calculate_sha256(data)
        hash2 = calculate_sha256({"a": 1, "b": 2})
        assert hash1 == hash2

    def test_calculate_sha256_different_data(self):
        """Test SHA256 differs for different data."""
        hash1 = calculate_sha256({"a": 1})
        hash2 = calculate_sha256({"a": 2})
        assert hash1 != hash2
