"""Unit tests for SNS utility functions."""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from mongodb_session_manager.hooks.utils_sns import publish_message


@pytest.fixture
def mock_sns_client():
    """Mock SNS client."""
    with patch("mongodb_session_manager.hooks.utils_sns._get_sns_client") as mock_get:
        client = MagicMock()
        client.publish.return_value = {"MessageId": "msg-123"}
        mock_get.return_value = client
        yield client


# ---------------------------------------------------------------------------
# publish_message
# ---------------------------------------------------------------------------


class TestPublishMessage:
    def test_publishes_to_topic(self, mock_sns_client):
        result = publish_message(
            topic_arn="arn:aws:sns:eu-west-1:123:topic",
            message="Hello",
        )
        mock_sns_client.publish.assert_called_once()
        assert result["MessageId"] == "msg-123"

    def test_publishes_with_subject(self, mock_sns_client):
        publish_message(
            topic_arn="arn:topic",
            message="Hello",
            subject="Test Subject",
        )
        call_kwargs = mock_sns_client.publish.call_args[1]
        assert call_kwargs["Subject"] == "Test Subject"

    def test_publishes_with_attributes(self, mock_sns_client):
        attrs = {"session_id": {"DataType": "String", "StringValue": "s1"}}
        publish_message(
            topic_arn="arn:topic",
            message="Hello",
            message_attributes=attrs,
        )
        call_kwargs = mock_sns_client.publish.call_args[1]
        assert call_kwargs["MessageAttributes"] == attrs

    def test_converts_dict_to_json(self, mock_sns_client):
        publish_message(
            topic_arn="arn:topic",
            message={"key": "value"},
        )
        call_kwargs = mock_sns_client.publish.call_args[1]
        assert json.loads(call_kwargs["Message"]) == {"key": "value"}

    def test_raises_without_target(self, mock_sns_client):
        with pytest.raises(ValueError, match="topic_arn o phone_number"):
            publish_message(message="Hello")

    def test_raises_with_both_targets(self, mock_sns_client):
        with pytest.raises(ValueError, match="solo uno"):
            publish_message(
                topic_arn="arn:topic",
                phone_number="+34600000000",
                message="Hello",
            )

    def test_raises_empty_message(self, mock_sns_client):
        with pytest.raises(ValueError, match="mensaje no puede estar vacío"):
            publish_message(topic_arn="arn:topic", message=None)

    def test_handles_not_found_error(self, mock_sns_client):
        error_response = {"Error": {"Code": "NotFound", "Message": "not found"}}
        mock_sns_client.publish.side_effect = ClientError(error_response, "Publish")
        with pytest.raises(ValueError, match="tópico no existe"):
            publish_message(topic_arn="arn:bad", message="Hello")

    def test_handles_authorization_error(self, mock_sns_client):
        error_response = {"Error": {"Code": "AuthorizationError", "Message": "denied"}}
        mock_sns_client.publish.side_effect = ClientError(error_response, "Publish")
        with pytest.raises(PermissionError, match="Acceso denegado"):
            publish_message(topic_arn="arn:topic", message="Hello")

    def test_handles_invalid_parameter_error(self, mock_sns_client):
        error_response = {"Error": {"Code": "InvalidParameter", "Message": "bad param"}}
        mock_sns_client.publish.side_effect = ClientError(error_response, "Publish")
        with pytest.raises(ValueError, match="Parámetro inválido"):
            publish_message(topic_arn="arn:topic", message="Hello")
