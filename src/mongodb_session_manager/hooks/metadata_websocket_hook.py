"""
AWS API Gateway WebSocket Integration Hook for MongoDB Session Manager Metadata Real-time Propagation.

This module provides a WebSocket integration hook that captures metadata changes in MongoDB Session
Manager and sends them directly to connected WebSocket clients through AWS API Gateway WebSocket API.
This enables instant, push-based real-time synchronization of session metadata with ultra-low latency.

Key Features:
    - Ultra-low latency push notifications directly to WebSocket clients
    - Real-time metadata change capture (create, update, delete operations)
    - Selective field propagation to minimize message size and bandwidth
    - Non-blocking async operation ensures metadata operations aren't delayed
    - Graceful error handling - metadata operations succeed even if WebSocket send fails
    - Automatic handling of disconnected clients (GoneException)
    - Support for both async and sync execution contexts
    - Thread-safe operation for high-concurrency environments

Architecture:
    The hook integrates with MongoDB Session Manager's metadataHook system to:
    1. Intercept all metadata operations (update, delete)
    2. Execute the original metadata operation first (ensuring data consistency)
    3. Extract connection_id from metadata.connection_id
    4. Extract relevant metadata fields for propagation
    5. Send changes directly to WebSocket client using API Gateway Management API
    6. Handle both async/await and synchronous contexts automatically

    The WebSocket messages are sent directly to connected clients:
    - No intermediate queue or polling required
    - Instant push notifications when metadata changes
    - Perfect for real-time dashboards, monitoring UIs, and chat interfaces

Usage:
    ```python
    from mongodb_session_manager import MongoDBSessionManager
    from mongodb_session_manager.hooks.metadata_websocket_hook import create_metadata_hook

    # Create the WebSocket hook with API Gateway endpoint
    websocket_hook = create_metadata_hook(
        api_gateway_endpoint="https://abc123.execute-api.us-east-1.amazonaws.com/prod",
        metadata_fields=["status", "agent_state", "last_action", "progress"],
        region="us-east-1"
    )

    # Create session manager with WebSocket propagation
    session_manager = MongoDBSessionManager(
        session_id="user-session-123",
        connection_string="mongodb://...",
        metadataHook=websocket_hook
    )

    # Metadata changes are automatically sent to connected WebSocket client
    # NOTE: connection_id MUST be present in metadata for hook to work
    session_manager.update_metadata({
        "connection_id": "abc123def456",  # Required!
        "status": "processing",
        "agent_state": "thinking",
        "internal_field": "not propagated"  # This won't be sent if not in metadata_fields
    })
    ```

WebSocket Message Format:
    Message Body (JSON):
    ```json
    {
        "event_type": "metadata_update",
        "session_id": "user-session-123",
        "operation": "update",
        "metadata": {
            "status": "processing",
            "agent_state": "thinking"
        },
        "timestamp": "2025-10-22T10:30:45.123456"
    }
    ```

Connection ID Management:
    The hook reads the WebSocket connection ID from `metadata.connection_id`.
    This field must be set when a WebSocket client connects:

    ```python
    # When WebSocket connects (e.g., in your $connect Lambda)
    connection_id = event['requestContext']['connectionId']
    session_id = extract_session_id(event)  # Your logic

    # Store connection ID in metadata
    session_manager.update_metadata({
        "connection_id": connection_id
    })

    # Now all subsequent metadata updates will be pushed to this connection
    ```

Use Cases:
    - **Real-time Session Viewer**: Session Viewer UI updates instantly when metadata changes
    - **Live Dashboards**: Monitoring dashboards show agent state changes in real-time
    - **Chat Interfaces**: Display agent thinking/processing state to users
    - **Workflow Progress**: Show multi-step workflow progress without polling
    - **Multi-user Collaboration**: Synchronize session state across multiple viewers

Requirements:
    - boto3 >= 1.26.0 (for API Gateway Management API support)
    - AWS credentials configured with execute-api:ManageConnections permission
    - Valid API Gateway WebSocket endpoint URL
    - Connection IDs must be stored in metadata.connection_id

Error Handling:
    - ImportError: Raised during initialization if boto3 is not available
    - GoneException: Logged (INFO) when connection is closed, operation continues
    - All other errors: Logged (ERROR) but not raised to ensure metadata operations succeed
    - Failed WebSocket sends don't block or fail the metadata operation

Performance Considerations:
    - Direct push to clients - no polling overhead
    - Only specified metadata fields are propagated (reduces message size)
    - Async operation prevents blocking the main thread
    - Daemon threads in sync contexts prevent process hanging
    - Ultra-low latency compared to SQS/SNS polling patterns

Security Considerations:
    - Only propagate non-sensitive metadata fields using metadata_fields parameter
    - Ensure API Gateway has appropriate IAM policies for execute-api:ManageConnections
    - Connection IDs should be validated before storage
    - Consider message encryption for sensitive data
    - Implement authentication at WebSocket connection time

Comparison with SQS Hook:
    - **WebSocket Hook**: Ultra-low latency, direct push, ideal for single-client real-time UIs
    - **SQS Hook**: Multi-consumer, guaranteed delivery, ideal for event-driven architectures
    - **Use both**: WebSocket for UI + SQS for backend processing is a common pattern
"""

import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    logging.warning(
        "boto3 not available. WebSocket hook requires boto3 to be installed."
    )
    boto3 = None
    ClientError = None

logger = logging.getLogger(__name__)


class MetadataWebSocketHook:
    """Hook to send metadata changes to WebSocket clients via API Gateway"""

    def __init__(
        self,
        api_gateway_endpoint: str,
        metadata_fields: Optional[List[str]] = None,
        region: str = "us-east-1",
    ):
        """
        Initialize the metadata WebSocket hook

        Args:
            api_gateway_endpoint: Full API Gateway WebSocket endpoint URL
                                 (e.g., https://abc123.execute-api.us-east-1.amazonaws.com/prod)
            metadata_fields: Optional list of metadata field names to propagate.
                           If None, all fields except connection_id are sent.
            region: AWS region for the API Gateway (default: us-east-1)

        Raises:
            ImportError: If boto3 is not available
        """
        if not boto3:
            raise ImportError(
                "boto3 module not available. " "Please install boto3: pip install boto3"
            )

        self.api_gateway_endpoint = api_gateway_endpoint
        self.metadata_fields = metadata_fields or []
        self.region = region

        # Create API Gateway Management API client
        self.client = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=api_gateway_endpoint,
            region_name=region,
        )

        logger.info(
            f"Initialized MetadataWebSocketHook with endpoint: {api_gateway_endpoint}, "
            f"region: {region}, fields: {metadata_fields or 'all'}"
        )

    async def on_metadata_change(
        self, session_id: str, metadata: Dict[str, Any], operation: str
    ) -> None:
        """
        Hook called when metadata changes (set, update, delete)

        Args:
            session_id: The session identifier
            metadata: The current metadata dictionary
            operation: The operation type (update, delete)
        """
        try:
            # Extract connection_id from metadata
            connection_id = metadata.get("connection_id")

            if not connection_id:
                logger.warning(
                    f"No connection_id found in metadata for session {session_id}. "
                    "WebSocket hook cannot send message without connection_id."
                )
                return

            # Extract only the relevant fields for WebSocket propagation
            if self.metadata_fields:
                # If specific fields are configured, only send those
                relevant_metadata = {
                    field: metadata.get(field) for field in self.metadata_fields
                }
                # Remove None values to keep message compact
                relevant_metadata = {
                    k: v for k, v in relevant_metadata.items() if v is not None
                }
            else:
                # If no specific fields configured, send all metadata except connection_id
                relevant_metadata = {
                    k: v for k, v in metadata.items() if k != "connection_id"
                }

            # Prepare the message
            message_data = {
                "event_type": "metadata_update",
                "session_id": session_id,
                "operation": operation,
                "metadata": relevant_metadata,
                "timestamp": datetime.now().isoformat(),
            }

            # Convert to JSON string
            message_body = json.dumps(message_data)

            # Log the message for debugging
            logger.debug(
                f"Sending metadata update to WebSocket connection {connection_id}: {message_body}"
            )

            # Send to WebSocket using asyncio.to_thread for non-blocking operation
            # This ensures the hook doesn't block the main metadata operation
            await asyncio.to_thread(
                self.client.post_to_connection,
                ConnectionId=connection_id,
                Data=message_body.encode("utf-8"),
            )

            logger.info(
                f"Sent metadata {operation} to WebSocket connection {connection_id} for session {session_id} "
                f"with fields: {list(relevant_metadata.keys())}"
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")

            if error_code == "GoneException":
                # Connection is closed/disconnected - this is expected, just log info
                logger.info(
                    f"WebSocket connection {connection_id} is disconnected (GoneException) "
                    f"for session {session_id}. Message not delivered."
                )
            else:
                # Other ClientError - log as error
                logger.error(
                    f"AWS ClientError sending metadata to WebSocket for session {session_id}: "
                    f"{error_code} - {e}",
                    exc_info=True,
                )

        except ImportError as e:
            logger.error(f"Import error in metadata WebSocket hook: {e}")

        except Exception as e:
            # Log error but don't raise to avoid breaking the main operation
            # The metadata update should succeed even if the hook fails
            logger.error(
                f"Error sending metadata to WebSocket for session {session_id}: {e}",
                exc_info=True,
            )


def create_metadata_hook(
    api_gateway_endpoint: str,
    metadata_fields: Optional[List[str]] = None,
    region: str = "eu-west-1",
):
    """
    Create a single metadata hook function for mongodb-session-manager

    Args:
        api_gateway_endpoint: Full API Gateway WebSocket endpoint URL
                             (e.g., https://abc123.execute-api.us-east-1.amazonaws.com/prod)
        metadata_fields: Optional list of metadata field names to propagate.
                        If None, all fields except connection_id are sent.
        region: AWS region for the API Gateway (default: us-east-1)

    Returns:
        Hook function that handles metadata operations, or None if hook creation fails

    Example:
        ```python
        websocket_hook = create_metadata_hook(
            api_gateway_endpoint="https://abc123.execute-api.us-east-1.amazonaws.com/prod",
            metadata_fields=["status", "progress", "agent_state"],
            region="us-east-1"
        )

        session_manager = MongoDBSessionManager(
            session_id="session-123",
            connection_string="mongodb://...",
            metadataHook=websocket_hook
        )
        ```
    """
    try:
        websocket_hook = MetadataWebSocketHook(
            api_gateway_endpoint, metadata_fields, region
        )

        def metadata_hook_wrapper(
            original_func, action: str, session_id: str, **kwargs
        ):
            """
            Wrapper that adapts to mongodb-session-manager hook interface

            Args:
                original_func: The original method being wrapped
                action: "update", "get", or "delete"
                session_id: The current session ID
                **kwargs: Additional arguments (metadata for update, keys for delete)
            """
            # Call the original function first
            if action == "update" and "metadata" in kwargs:
                result = original_func(kwargs["metadata"])
                # Get the updated metadata from the result to ensure we have the latest state
                try:
                    # Get current event loop if available, otherwise create a new one
                    try:
                        loop = asyncio.get_running_loop()
                        # We're in an async context, create task
                        loop.create_task(
                            websocket_hook.on_metadata_change(
                                session_id, kwargs["metadata"], action
                            )
                        )
                    except RuntimeError:
                        # No running loop, run in a new thread to avoid blocking
                        import threading

                        def run_hook():
                            asyncio.run(
                                websocket_hook.on_metadata_change(
                                    session_id, kwargs["metadata"], action
                                )
                            )

                        thread = threading.Thread(target=run_hook, daemon=True)
                        thread.start()
                except Exception as e:
                    logger.error(f"Error sending metadata update to WebSocket: {e}")

            elif action == "delete" and "keys" in kwargs:
                result = original_func(kwargs["keys"])
                # For delete, send empty metadata for deleted keys
                # But we still need the connection_id from current metadata
                # We'll need to get current metadata first
                try:
                    # Get current metadata to extract connection_id
                    current_metadata = original_func.__self__.get_metadata()
                    deleted_metadata = {
                        "connection_id": current_metadata.get("connection_id"),
                        **{key: None for key in kwargs["keys"]},
                    }

                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(
                            websocket_hook.on_metadata_change(
                                session_id, deleted_metadata, action
                            )
                        )
                    except RuntimeError:
                        import threading

                        def run_hook():
                            asyncio.run(
                                websocket_hook.on_metadata_change(
                                    session_id, deleted_metadata, action
                                )
                            )

                        thread = threading.Thread(target=run_hook, daemon=True)
                        thread.start()
                except Exception as e:
                    logger.error(f"Error sending metadata delete to WebSocket: {e}")

            else:
                # For "get" or other operations, just call original
                result = original_func()

            return result

        return metadata_hook_wrapper

    except Exception as e:
        logger.error(f"Failed to create metadata WebSocket hook: {e}")
        return None
