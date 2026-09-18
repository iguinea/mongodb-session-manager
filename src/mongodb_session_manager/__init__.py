"""MongoDB Session Manager for Strands Agents."""

from .hooks.background_work import BackgroundWorkStats
from .hooks.utils_async import (
    hooks_background_stats,
    shutdown_hooks,
    shutdown_hooks_async,
)
from .message_identity import MessageRef, ref_of
from .mongodb_connection_pool import MongoDBConnectionPool
from .mongodb_session_factory import (
    MongoDBSessionManagerFactory,
    close_global_factory,
    get_global_factory,
    initialize_global_factory,
)
from .mongodb_session_manager import (
    GUARDRAIL_STOP_REASONS,
    MongoDBSessionManager,
    create_mongodb_session_manager,
)
from .mongodb_session_repository import MongoDBSessionRepository

# Hook imports - wrapped in try/except to handle optional dependencies
try:
    from .hooks.feedback_sns_hook import (
        FeedbackSNSHook,
    )
    from .hooks.feedback_sns_hook import (
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
    )
    from .hooks.metadata_sqs_hook import (
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
    )
    from .hooks.metadata_websocket_hook import (
        create_metadata_hook as create_metadata_websocket_hook,
    )

    _metadata_websocket_available = True
except ImportError:
    _metadata_websocket_available = False
    MetadataWebSocketHook = None
    create_metadata_websocket_hook = None


__all__ = [  # noqa: RUF022  agrupado por categorías a propósito; ordenarlo alfabéticamente pierde los grupos
    # Core classes
    "MongoDBSessionManager",
    "MongoDBSessionRepository",
    "MongoDBConnectionPool",
    "MongoDBSessionManagerFactory",
    # Value objects
    "MessageRef",
    "ref_of",
    # Background work of the hooks
    "BackgroundWorkStats",
    "hooks_background_stats",
    "shutdown_hooks",
    "shutdown_hooks_async",
    # Constants
    "GUARDRAIL_STOP_REASONS",
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
    """Check if the feedback SNS hook is available (boto3 installed)."""
    return _feedback_sns_available


def is_metadata_sqs_hook_available() -> bool:
    """Check if the metadata SQS hook is available (boto3 installed)."""
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

__version__ = "1.0.0"
__author__ = "Iñaki Guinea Beristain"
__author_email__ = "iguinea@gmail.com"
