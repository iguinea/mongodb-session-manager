"""
MongoDB Session Manager Hooks - AWS Integration Modules.

This package contains hook implementations for integrating MongoDB Session Manager
with AWS services for real-time notifications and event propagation.

Available Hooks:
    - feedback_sns_hook: Send feedback notifications to AWS SNS
    - metadata_sqs_hook: Propagate metadata changes to AWS SQS for SSE

Note: These hooks require the `custom_aws` package (python-helpers) to be installed.
"""

# Import hook creators if available
try:
    from .feedback_sns_hook import FeedbackSNSHook, create_feedback_hook
    feedback_sns_available = True
except ImportError:
    feedback_sns_available = False
    FeedbackSNSHook = None
    create_feedback_hook = None

try:
    from .metadata_sqs_hook import MetadataSQSHook, create_metadata_hook
    metadata_sqs_available = True
except ImportError:
    metadata_sqs_available = False
    MetadataSQSHook = None
    create_metadata_hook = None

__all__ = []

if feedback_sns_available:
    __all__.extend(["FeedbackSNSHook", "create_feedback_hook"])

if metadata_sqs_available:
    __all__.extend(["MetadataSQSHook", "create_metadata_hook"])