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
    - The metadata operation succeeds even if SQS fails: the notification is
      already out of its way by then, and its failure is counted, not hidden
    - Message attributes for efficient queue filtering and routing
    - Notifications run on the event loop the hook is bound to, whatever
      thread calls it (pass `loop=`, or build the hook inside a running loop)
    - Thread-safe operation for high-concurrency environments

Architecture:
    The hook integrates with MongoDB Session Manager's metadata_hook system to:
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
        metadata_hook=sqs_hook
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
    - ImportError: Raised during initialization if boto3 cannot be imported
    - All other errors: raised out of the notification, which runs in the
      background — `background_work.BackgroundWork` counts them as `failed` and
      logs them once, with their context and their traceback
    - Failed SQS sends don't block or fail the metadata operation: by the time
      the notification runs, that operation has already returned

Performance Considerations:
    - Only specified metadata fields are propagated (reduces message size)
    - Async operation prevents blocking the main thread
    - A bound loop takes the notification without spawning a thread per event
    - Consider SQS queue throughput limits for high-volume applications
    - Message deduplication may be needed at the consumer level

Security Considerations:
    - Only propagate non-sensitive metadata fields
    - Ensure SQS queue has appropriate access policies
    - Consider encryption at rest and in transit for sensitive data
    - Implement message validation at the consumer level
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from .utils_async import capture_loop, dispatch_async

logger = logging.getLogger(__name__)

try:
    from .utils_sqs import send_message
except ImportError:
    logger.warning("utils_sqs not available. Please ensure boto3 is installed.")
    send_message = None


class MetadataSQSHook:
    """Hook to send metadata changes to SQS for SSE back-propagation"""

    def __init__(self, queue_url: str, metadata_fields: list[str]):
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
        self, session_id: str, metadata: dict[str, Any], operation: str
    ) -> None:
        """
        Hook called when metadata changes (set, update, delete)

        It does not swallow what SQS refuses. By the time this runs, the
        metadata write has already returned to its caller, so there is no main
        operation left to break — and `background_work.BackgroundWork` is
        waiting to count the failure and log it with its context.

        Args:
            session_id: The session identifier
            metadata: The current metadata dictionary
            operation: The operation type (set, update, delete)

        Raises:
            ClientError: If SQS refuses the message.
            ValueError, PermissionError: What `utils_sqs.send_message()` makes
                of a missing queue, invalid contents or a denied `SendMessage`.
        """
        # Extract only the relevant fields for SSE propagation
        if self.metadata_fields:
            # If specific fields are configured, only send those. On a delete
            # the metadata carries the deleted keys, so they are selected by
            # presence and kept: the consumer needs to know *what* was deleted
            # (#120). On an update, None values stay filtered out — projecting
            # the whole configuration instead would publish fields nobody
            # deleted.
            relevant_metadata = {
                field: metadata[field]
                for field in self.metadata_fields
                if field in metadata
                and (operation == "delete" or metadata[field] is not None)
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
            "timestamp": datetime.now(UTC).isoformat(),
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


def create_metadata_hook(
    queue_url: str,
    metadata_fields: list[str] | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
):
    """
    Create a single metadata hook function for mongodb-session-manager

    Args:
        queue_url: Full SQS queue URL
        metadata_fields: List of metadata field names to propagate (if None, all fields are sent)
        loop: Event loop the notifications run on. Defaults to the loop running
              when the hook is created, so a hook built in an async lifespan
              keeps sending on the server loop even when the metadata write is
              called from a worker thread. If there is none, the dispatch
              decides per call: a task on the loop of the calling thread, or
              the reserve loop the whole process shares.

    Returns:
        Hook function that handles metadata operations
    """
    try:
        sqs_hook = MetadataSQSHook(queue_url, metadata_fields or [])
        dispatch_loop = loop if loop is not None else capture_loop()

        def metadata_hook_wrapper(
            original_func, action: str, session_id: str, **kwargs
        ):
            """Wrapper that adapts to mongodb-session-manager hook interface."""
            if action == "update" and "metadata" in kwargs:
                result = original_func(kwargs["metadata"])
                dispatch_async(
                    sqs_hook.on_metadata_change(session_id, kwargs["metadata"], action),
                    f"sending metadata update to SQS for session {session_id}",
                    loop=dispatch_loop,
                    order_key=f"sqs:{session_id}",
                )
            elif action == "delete" and "keys" in kwargs:
                result = original_func(kwargs["keys"])
                deleted_metadata = {key: None for key in kwargs["keys"]}
                dispatch_async(
                    sqs_hook.on_metadata_change(session_id, deleted_metadata, action),
                    f"sending metadata delete to SQS for session {session_id}",
                    loop=dispatch_loop,
                    order_key=f"sqs:{session_id}",
                )
            else:
                result = original_func()

            return result

        return metadata_hook_wrapper

    except Exception as e:
        logger.error(f"Failed to create metadata hook: {e}")
        return None
