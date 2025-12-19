"""Tests for payment handler."""

import json
import os

import boto3
import pytest
from idempotency_lib import format_pk
from moto import mock_aws

from handlers import payment as payment_module
from handlers.payment import payment_handler

PK_PREFIX = "PAYMENT#IDEM"


@pytest.fixture(autouse=True)
def set_env_vars():
    """Set payment-specific environment variables."""
    os.environ["IDEMPOTENCY_PK_PREFIX"] = PK_PREFIX
    yield


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

        # Update the manager with the mock table
        payment_module.manager.table = table
        payment_module.manager.pk_prefix = PK_PREFIX

        yield table


class TestPaymentHandler:
    """Tests for payment handler."""

    def test_missing_idempotency_key_returns_400(self, mock_dynamodb):
        """Test missing idempotency key returns 400."""
        event = {
            "headers": {},
            "body": json.dumps({"amount": 100}),
        }

        result = payment_handler(event, None)

        assert result["statusCode"] == 400
        assert "Idempotency-Key" in json.loads(result["body"])["error"]

    def test_invalid_json_body_returns_400(self, mock_dynamodb):
        """Test invalid JSON body returns 400."""
        event = {
            "headers": {"Idempotency-Key": "test-key"},
            "body": "invalid-json",
        }

        result = payment_handler(event, None)

        assert result["statusCode"] == 400
        assert "Invalid JSON" in json.loads(result["body"])["error"]

    def test_new_payment_returns_201(self, mock_dynamodb):
        """Test new payment returns 201."""
        event = {
            "headers": {"Idempotency-Key": "new-payment"},
            "body": json.dumps({"amount": 100, "currency": "USD"}),
        }

        result = payment_handler(event, None)

        assert result["statusCode"] == 201
        body = json.loads(result["body"])
        assert body["amount"] == 100
        assert body["currency"] == "USD"
        assert body["status"] == "SUCCESS"
        assert body["transaction_id"].startswith("TXN-")

    def test_replay_returns_cached_response(self, mock_dynamodb):
        """Test replay returns cached response."""
        # First request
        event = {
            "headers": {"Idempotency-Key": "completed-payment"},
            "body": json.dumps({"amount": 100}),
        }
        first_result = payment_handler(event, None)
        first_body = json.loads(first_result["body"])

        # Second request - should be replay
        second_result = payment_handler(event, None)

        assert second_result["statusCode"] == 201
        assert second_result["headers"]["X-Idempotency-Replay"] == "true"
        assert json.loads(second_result["body"]) == first_body

    def test_different_payload_returns_409(self, mock_dynamodb):
        """Test different payload returns 409."""
        # First request
        event1 = {
            "headers": {"Idempotency-Key": "existing-payment"},
            "body": json.dumps({"amount": 100}),
        }
        payment_handler(event1, None)

        # Second request with different payload
        event2 = {
            "headers": {"Idempotency-Key": "existing-payment"},
            "body": json.dumps({"amount": 999}),
        }
        result = payment_handler(event2, None)

        assert result["statusCode"] == 409
        assert "different payload" in json.loads(result["body"])["error"]

    def test_in_progress_returns_409(self, mock_dynamodb, mocker):
        """Test in progress returns 409."""
        pk = format_pk("ongoing-payment", PK_PREFIX)
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

        event = {
            "headers": {"Idempotency-Key": "ongoing-payment"},
            "body": json.dumps({"amount": 10}),
        }

        result = payment_handler(event, None)

        assert result["statusCode"] == 409
        assert "in progress" in json.loads(result["body"])["error"]

    def test_idempotency_key_case_insensitive(self, mock_dynamodb):
        """Test idempotency key header is case insensitive."""
        event = {
            "headers": {"IDEMPOTENCY-KEY": "case-test"},
            "body": json.dumps({"amount": 50}),
        }

        result = payment_handler(event, None)

        assert result["statusCode"] == 201

    def test_stores_completed_transaction(self, mock_dynamodb):
        """Test completed transaction is stored."""
        event = {
            "headers": {"Idempotency-Key": "store-test"},
            "body": json.dumps({"amount": 200}),
        }

        result = payment_handler(event, None)

        assert result["statusCode"] == 201

        pk = format_pk("store-test", PK_PREFIX)
        item = mock_dynamodb.get_item(Key={"IdempotencyKey": pk}).get("Item")
        assert item["Status"] == "COMPLETED"
        assert item["ResponseBody"] is not None
