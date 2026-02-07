"""Unit tests for SQS utility functions."""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from mongodb_session_manager.hooks.utils_sqs import send_message


@pytest.fixture
def mock_sqs_client():
    """Mock SQS client."""
    with patch("mongodb_session_manager.hooks.utils_sqs._get_sqs_client") as mock_get:
        client = MagicMock()
        client.send_message.return_value = {
            "MessageId": "msg-456",
            "MD5OfMessageBody": "abc",
        }
        mock_get.return_value = client
        yield client


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_sends_message(self, mock_sqs_client):
        result = send_message(
            queue_url="https://sqs.example.com/queue",
            message_body="Hello",
        )
        mock_sqs_client.send_message.assert_called_once()
        assert result["MessageId"] == "msg-456"

    def test_sends_with_attributes(self, mock_sqs_client):
        attrs = {"event": {"DataType": "String", "StringValue": "update"}}
        send_message(
            queue_url="https://sqs.example.com/queue",
            message_body="Hello",
            message_attributes=attrs,
        )
        call_kwargs = mock_sqs_client.send_message.call_args[1]
        assert call_kwargs["MessageAttributes"] == attrs

    def test_converts_dict_to_json(self, mock_sqs_client):
        send_message(
            queue_url="https://sqs.example.com/queue",
            message_body={"key": "value"},
        )
        call_kwargs = mock_sqs_client.send_message.call_args[1]
        assert json.loads(call_kwargs["MessageBody"]) == {"key": "value"}

    def test_raises_invalid_delay_seconds(self, mock_sqs_client):
        with pytest.raises(ValueError, match="delay_seconds"):
            send_message(
                queue_url="https://sqs.example.com/queue",
                message_body="Hello",
                delay_seconds=1000,
            )

    def test_handles_queue_does_not_exist(self, mock_sqs_client):
        error_response = {"Error": {"Code": "QueueDoesNotExist", "Message": "no queue"}}
        mock_sqs_client.send_message.side_effect = ClientError(
            error_response, "SendMessage"
        )
        with pytest.raises(ValueError, match="cola no existe"):
            send_message(
                queue_url="https://sqs.example.com/bad",
                message_body="Hello",
            )

    def test_handles_access_denied(self, mock_sqs_client):
        error_response = {"Error": {"Code": "AccessDenied", "Message": "denied"}}
        mock_sqs_client.send_message.side_effect = ClientError(
            error_response, "SendMessage"
        )
        with pytest.raises(PermissionError, match="Acceso denegado"):
            send_message(
                queue_url="https://sqs.example.com/queue",
                message_body="Hello",
            )

    def test_handles_invalid_message(self, mock_sqs_client):
        error_response = {"Error": {"Code": "InvalidMessageContents", "Message": "bad"}}
        mock_sqs_client.send_message.side_effect = ClientError(
            error_response, "SendMessage"
        )
        with pytest.raises(ValueError, match="contenido del mensaje"):
            send_message(
                queue_url="https://sqs.example.com/queue",
                message_body="Hello",
            )

    def test_fifo_queue_params(self, mock_sqs_client):
        send_message(
            queue_url="https://sqs.example.com/queue.fifo",
            message_body="Hello",
            message_group_id="group1",
            message_deduplication_id="dedup1",
        )
        call_kwargs = mock_sqs_client.send_message.call_args[1]
        assert call_kwargs["MessageGroupId"] == "group1"
        assert call_kwargs["MessageDeduplicationId"] == "dedup1"
