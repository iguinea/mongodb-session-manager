"""
AWS SQS Integration Hook for MongoDB Session Manager Metadata Real-time Propagation.

This module provides an SQS (Simple Queue Service) integration hook that captures metadata
changes in MongoDB Session Manager and sends them to an SQS queue for Server-Sent Events (SSE)
back-propagation. This enables real-time synchronization of session metadata across distributed
systems and allows connected clients to receive live updates when session metadata changes.

Key Features:
    - Real-time metadata change capture (create, update, delete operations)
    - Selective field propagation to minimize message size and processing overhead
    - Non-blocking async operation ensures metadata operations aren't delayed
    - Graceful error handling - metadata operations succeed even if SQS fails
    - Message attributes for efficient queue filtering and routing
    - Support for both async and sync execution contexts
    - Thread-safe operation for high-concurrency environments

Architecture:
    The hook integrates with MongoDB Session Manager's metadataHook system to:
    1. Intercept all metadata operations (update, delete)
    2. Execute the original metadata operation first (ensuring data consistency)
    3. Extract relevant metadata fields for propagation
    4. Send changes to SQS queue asynchronously
    5. Handle both async/await and synchronous contexts automatically

    The SQS messages can then be processed by a separate service that:
    - Reads messages from the queue
    - Propagates changes to connected SSE clients
    - Maintains real-time synchronization across systems

Usage:
    ```python
    from mongodb_session_manager import MongoDBSessionManager
    from mongodb_session_manager.hooks.metadata_sqs_hook import create_metadata_hook

    # Create the SQS hook with specific fields to propagate
    sqs_hook = create_metadata_hook(
        queue_url="https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates",
        metadata_fields=["status", "agent_state", "last_action", "priority"]
    )

    # Create session manager with SQS propagation
    session_manager = MongoDBSessionManager(
        session_id="user-session-123",
        connection_string="mongodb://...",
        metadataHook=sqs_hook
    )

    # Metadata changes are automatically sent to SQS
    session_manager.update_metadata({
        "status": "processing",
        "agent_state": "thinking",
        "internal_field": "not propagated"  # This won't be sent to SQS
    })
    ```

SQS Message Format:
    Message Body (JSON):
    ```json
    {
        "session_id": "user-session-123",
        "operation": "update",
        "metadata": {
            "status": "processing",
            "agent_state": "thinking"
        },
        "timestamp": "2024-01-26T10:30:45.123456"
    }
    ```

    Message Attributes:
        - session_id: String attribute with the session identifier
        - operation: String attribute with "update" or "delete"

Use Cases:
    - **Real-time Dashboards**: Update monitoring dashboards when session state changes
    - **Multi-client Synchronization**: Keep multiple connected clients in sync
    - **Workflow Orchestration**: Trigger workflows based on metadata changes
    - **Audit Logging**: Stream metadata changes to audit systems
    - **Event-driven Architecture**: Enable reactive systems based on session state

Requirements:
    - boto3 package for AWS SDK
    - AWS credentials configured with SQS SendMessage permissions
    - Valid SQS queue URL with appropriate access policies
    - Queue should have appropriate visibility timeout and retention settings

Error Handling:
    - ImportError: Raised during initialization if custom_aws.sqs is not available
    - All other errors: Logged but not raised to ensure metadata operations succeed
    - Failed SQS sends don't block or fail the metadata operation

Performance Considerations:
    - Only specified metadata fields are propagated (reduces message size)
    - Async operation prevents blocking the main thread
    - Daemon threads in sync contexts prevent process hanging
    - Consider SQS queue throughput limits for high-volume applications
    - Message deduplication may be needed at the consumer level

Security Considerations:
    - Only propagate non-sensitive metadata fields
    - Ensure SQS queue has appropriate access policies
    - Consider encryption at rest and in transit for sensitive data
    - Implement message validation at the consumer level
"""

import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List

try:
    from .utils_sqs import send_message
except ImportError:
    logging.warning(
        "utils_sqs not available. Please ensure boto3 is installed."
    )
    send_message = None

logger = logging.getLogger(__name__)


class MetadataSQSHook:
    """Hook to send metadata changes to SQS for SSE back-propagation"""

    def __init__(self, queue_url: str, metadata_fields: List[str]):
        """
        Initialize the metadata SQS hook

        Args:
            queue_url: Full SQS queue URL (e.g., https://sqs.eu-west-1.amazonaws.com/123456789/sse-back-propagation)
        """
        if not send_message:
            raise ImportError(
                "SQS utilities not available. "
                "Please ensure boto3 is installed: pip install boto3"
            )

        self.queue_url = queue_url
        self.metadata_fields = metadata_fields
        logger.info(f"Initialized MetadataSQSHook with queue: {queue_url}")

    async def on_metadata_change(
        self, session_id: str, metadata: Dict[str, Any], operation: str
    ) -> None:
        """
        Hook called when metadata changes (set, update, delete)

        Args:
            session_id: The session identifier
            metadata: The current metadata dictionary
            operation: The operation type (set, update, delete)
        """
        try:
            # Extract only the relevant fields for SSE propagation
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
                # If no specific fields configured, send all metadata
                relevant_metadata = metadata.copy()

            # Prepare the message
            message_data = {
                "session_id": session_id,
                "event": "metadata_update",
                "operation": operation,
                "metadata": relevant_metadata,
                "timestamp": datetime.now().isoformat(),
            }

            # Convert to JSON string
            message_body = json.dumps(message_data)

            # Log the message for debugging
            logger.debug(f"Sending metadata update to SQS: {message_body}")

            # Send to SQS using asyncio.to_thread for non-blocking operation
            # This ensures the hook doesn't block the main metadata operation
            await asyncio.to_thread(
                send_message,
                queue_url=self.queue_url,
                message_body=message_body,
                message_attributes={
                    "session_id": {"DataType": "String", "StringValue": session_id},
                    "event": {"DataType": "String", "StringValue": "metadata_update"},
                },
            )

            logger.info(
                f"Sent metadata {operation} to SQS for session {session_id} "
                f"with fields: {list(relevant_metadata.keys())}"
            )

        except ImportError as e:
            logger.error(f"Import error in metadata SQS hook: {e}")
        except Exception as e:
            # Log error but don't raise to avoid breaking the main operation
            # The metadata update should succeed even if the hook fails
            logger.error(
                f"Error sending metadata to SQS for session {session_id}: {e}",
                exc_info=True,
            )


# Helper function to create hook configuration
def create_metadata_hooks(queue_url: str) -> Dict[str, Any]:
    """
    Create hook configuration for mongodb-session-manager

    Args:
        queue_url: Full SQS queue URL

    Returns:
        Dictionary with hook functions for set, update, and delete operations
    """
    try:
        hook = MetadataSQSHook(queue_url)
        return {
            "on_metadata_set": hook.on_metadata_change,
            "on_metadata_update": hook.on_metadata_change,
            "on_metadata_delete": hook.on_metadata_change,
        }
    except Exception as e:
        logger.error(f"Failed to create metadata hooks: {e}")
        return {}


def create_metadata_hook(queue_url: str, metadata_fields: List[str] = None):
    """
    Create a single metadata hook function for mongodb-session-manager

    Args:
        queue_url: Full SQS queue URL
        metadata_fields: List of metadata field names to propagate (if None, all fields are sent)

    Returns:
        Hook function that handles metadata operations
    """
    try:
        sqs_hook = MetadataSQSHook(queue_url, metadata_fields or [])

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
                            sqs_hook.on_metadata_change(
                                session_id, kwargs["metadata"], action
                            )
                        )
                    except RuntimeError:
                        # No running loop, run in a new thread to avoid blocking
                        import threading

                        def run_hook():
                            asyncio.run(
                                sqs_hook.on_metadata_change(
                                    session_id, kwargs["metadata"], action
                                )
                            )

                        thread = threading.Thread(target=run_hook, daemon=True)
                        thread.start()
                except Exception as e:
                    logger.error(f"Error sending metadata update to SQS: {e}")
            elif action == "delete" and "keys" in kwargs:
                result = original_func(kwargs["keys"])
                # For delete, send empty metadata for deleted keys
                deleted_metadata = {key: None for key in kwargs["keys"]}
                try:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(
                            sqs_hook.on_metadata_change(
                                session_id, deleted_metadata, action
                            )
                        )
                    except RuntimeError:
                        import threading

                        def run_hook():
                            asyncio.run(
                                sqs_hook.on_metadata_change(
                                    session_id, deleted_metadata, action
                                )
                            )

                        thread = threading.Thread(target=run_hook, daemon=True)
                        thread.start()
                except Exception as e:
                    logger.error(f"Error sending metadata delete to SQS: {e}")
            else:
                # For "get" or other operations, just call original
                result = original_func()

            return result

        return metadata_hook_wrapper

    except Exception as e:
        logger.error(f"Failed to create metadata hook: {e}")
        return None
