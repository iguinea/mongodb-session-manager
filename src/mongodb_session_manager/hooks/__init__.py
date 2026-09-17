"""
MongoDB Session Manager Hooks - AWS Integration Modules.

This package contains hook implementations for integrating MongoDB Session Manager
with AWS services for real-time notifications and event propagation.

Available Hooks:
    - feedback_sns_hook: Send feedback notifications to AWS SNS
    - metadata_sqs_hook: Propagate metadata changes to AWS SQS for SSE
    - metadata_websocket_hook: Push metadata changes to WebSocket clients via API Gateway

The notifications they send travel in the background, bounded by
`background_work`: `shutdown_hooks()` closes that work where the process closes,
and `hooks_background_stats()` reports it.

Note: All AWS hooks require `boto3` to be installed.
"""

from .background_work import BackgroundWork, BackgroundWorkStats, Delivery
from .utils_async import (
    capture_loop,
    dispatch_async,
    hooks_background_stats,
    shutdown_hooks,
)

# Import hook creators if available
try:
    from .feedback_sns_hook import FeedbackSNSHook, create_feedback_hook

    feedback_sns_available = True
except ImportError:
    feedback_sns_available = False
    FeedbackSNSHook = None
    create_feedback_hook = None

try:
    from .metadata_sqs_hook import (
        MetadataSQSHook,
    )
    from .metadata_sqs_hook import (
        create_metadata_hook as create_metadata_sqs_hook,
    )

    metadata_sqs_available = True
except ImportError:
    metadata_sqs_available = False
    MetadataSQSHook = None
    create_metadata_sqs_hook = None

try:
    from .metadata_websocket_hook import (
        MetadataWebSocketHook,
    )
    from .metadata_websocket_hook import (
        create_metadata_hook as create_metadata_websocket_hook,
    )

    metadata_websocket_available = True
except ImportError:
    metadata_websocket_available = False
    MetadataWebSocketHook = None
    create_metadata_websocket_hook = None

__all__ = [
    "BackgroundWork",
    "BackgroundWorkStats",
    "Delivery",
    "capture_loop",
    "dispatch_async",
    "hooks_background_stats",
    "shutdown_hooks",
]

if feedback_sns_available:
    __all__.extend(["FeedbackSNSHook", "create_feedback_hook"])

if metadata_sqs_available:
    __all__.extend(["MetadataSQSHook", "create_metadata_sqs_hook"])

if metadata_websocket_available:
    __all__.extend(["MetadataWebSocketHook", "create_metadata_websocket_hook"])
