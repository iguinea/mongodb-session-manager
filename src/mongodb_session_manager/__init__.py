"""MongoDB Session Manager for Strands Agents."""

from .mongodb_session_manager import (
    MongoDBSessionManager,
    create_mongodb_session_manager,
)
from .mongodb_session_repository import MongoDBSessionRepository
from .mongodb_connection_pool import MongoDBConnectionPool
from .mongodb_session_factory import (
    MongoDBSessionManagerFactory,
    initialize_global_factory,
    get_global_factory,
    close_global_factory,
)

# Hook imports - wrapped in try/except to handle optional dependencies
try:
    from .hooks.feedback_sns_hook import (
        FeedbackSNSHook,
        create_feedback_hook as create_feedback_sns_hook,
    )

    _feedback_sns_available = True
except ImportError:
    _feedback_sns_available = False
    FeedbackSNSHook = None
    create_feedback_sns_hook = None

try:
    from .hooks.metadata_sqs_hook import (
        MetadataSQSHook,
        create_metadata_hook as create_metadata_sqs_hook,
    )

    _metadata_sqs_available = True
except ImportError:
    _metadata_sqs_available = False
    MetadataSQSHook = None
    create_metadata_sqs_hook = None

try:
    from .hooks.metadata_websocket_hook import (
        MetadataWebSocketHook,
        create_metadata_hook as create_metadata_websocket_hook,
    )

    _metadata_websocket_available = True
except ImportError:
    _metadata_websocket_available = False
    MetadataWebSocketHook = None
    create_metadata_websocket_hook = None

__all__ = [
    # Core classes
    "MongoDBSessionManager",
    "MongoDBSessionRepository",
    "MongoDBConnectionPool",
    "MongoDBSessionManagerFactory",
    # Factory functions
    "create_mongodb_session_manager",
    "initialize_global_factory",
    "get_global_factory",
    "close_global_factory",
]

# Add hook exports if available
if _feedback_sns_available:
    __all__.extend(
        [
            "FeedbackSNSHook",
            "create_feedback_sns_hook",
        ]
    )

if _metadata_sqs_available:
    __all__.extend(
        [
            "MetadataSQSHook",
            "create_metadata_sqs_hook",
        ]
    )

if _metadata_websocket_available:
    __all__.extend(
        [
            "MetadataWebSocketHook",
            "create_metadata_websocket_hook",
        ]
    )


# Helper functions to check hook availability
def is_feedback_sns_hook_available() -> bool:
    """Check if the feedback SNS hook is available (custom_aws.sns installed)."""
    return _feedback_sns_available


def is_metadata_sqs_hook_available() -> bool:
    """Check if the metadata SQS hook is available (custom_aws.sqs installed)."""
    return _metadata_sqs_available


def is_metadata_websocket_hook_available() -> bool:
    """Check if the metadata WebSocket hook is available (boto3 installed)."""
    return _metadata_websocket_available


# Export availability checkers
__all__.extend(
    [
        "is_feedback_sns_hook_available",
        "is_metadata_sqs_hook_available",
        "is_metadata_websocket_hook_available",
    ]
)

__version__ = "0.2.8"
__author__ = "Iñaki Guinea Beristain"
__author_email__ = "iguinea@gmail.com"
