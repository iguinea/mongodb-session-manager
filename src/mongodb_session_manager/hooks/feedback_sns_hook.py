"""
AWS SNS Notification Hook for MongoDB Session Manager Feedback System.

This module provides an SNS (Simple Notification Service) integration hook that sends
real-time notifications when users submit feedback for virtual agent sessions. The hook
is designed to work seamlessly with the MongoDB Session Manager's feedback system,
allowing teams to monitor user satisfaction and respond quickly to negative feedback.

Key Features:
    - Automatic SNS notifications on feedback submission
    - Non-blocking async operation to avoid impacting main feedback storage
    - Graceful error handling - feedback is always stored even if notification fails
    - Rich message attributes for SNS filtering and routing
    - Support for both async and sync execution contexts
    - Thread-safe operation for high-concurrency environments

Architecture:
    The hook integrates with MongoDB Session Manager's feedbackHook system and:
    1. Intercepts feedback add operations
    2. Stores feedback in MongoDB first (via original function)
    3. Sends SNS notification asynchronously
    4. Handles both async/await and synchronous contexts automatically

Usage:
    ```python
    from mongodb_session_manager import MongoDBSessionManager
    from mongodb_session_manager.hooks.feedback_sns_hook import create_feedback_hook

    # Create the SNS hook with three separate topics
    sns_hook = create_feedback_hook(
        topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
        topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
        topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
    )

    # Create session manager with SNS notifications
    session_manager = MongoDBSessionManager(
        session_id="user-session-123",
        connection_string="mongodb://...",
        feedbackHook=sns_hook
    )

    # Feedback is routed to the appropriate topic based on rating
    session_manager.add_feedback({
        "rating": "down",  # Routes to topic_arn_bad
        "comment": "The response was incomplete"
    })

    session_manager.add_feedback({
        "rating": "up",  # Routes to topic_arn_good
        "comment": "Great response!"
    })
    ```

SNS Message Format:
    Subject: "Virtual Agents Feedback {positive|negative|neutral} on session {session_id}"

    Message Body:
        Session: {session_id}

        {comment}

    Message Attributes:
        - session_id: String attribute with the session identifier
        - rating: String attribute with "positive", "negative", or "neutral"

    Topic Routing:
        - rating="up" → topic_arn_good
        - rating="down" → topic_arn_bad
        - rating=None → topic_arn_neutral

Requirements:
    - custom_aws.sns module (from python-helpers package)
    - AWS credentials configured with SNS publish permissions
    - Three valid SNS topic ARNs (for good, bad, and neutral feedback)

Error Handling:
    - ImportError: Raised during initialization if custom_aws.sns is not available
    - All other errors: Logged but not raised to ensure feedback storage succeeds

Thread Safety:
    The hook automatically detects the execution context:
    - In async context: Creates a task in the current event loop
    - In sync context: Spawns a daemon thread to run the async notification

Performance Considerations:
    - SNS notifications are sent asynchronously to avoid blocking
    - Failed notifications don't affect feedback storage
    - Daemon threads are used in sync contexts to prevent hanging on exit
"""

import logging
import asyncio
from typing import Dict, Any

try:
    from custom_aws.sns import publish_message
except ImportError:
    logging.warning(
        "custom_aws.sns not available. Please install python-helpers package."
    )
    publish_message = None

logger = logging.getLogger(__name__)


class FeedbackSNSHook:
    """Hook to send feedback notifications to SNS"""

    def __init__(self, topic_arn_good: str, topic_arn_bad: str, topic_arn_neutral: str):
        """
        Initialize the feedback SNS hook

        Args:
            topic_arn_good: SNS topic ARN for positive feedback (rating="up")
            topic_arn_bad: SNS topic ARN for negative feedback (rating="down")
            topic_arn_neutral: SNS topic ARN for neutral feedback (rating=None)
        """
        if not publish_message:
            raise ImportError(
                "custom_aws.sns module not available. "
                "Please install python-helpers package: pip install python-helpers"
            )

        self.topic_arn_good = topic_arn_good
        self.topic_arn_bad = topic_arn_bad
        self.topic_arn_neutral = topic_arn_neutral
        logger.info(
            f"Initialized FeedbackSNSHook with topics - "
            f"good: {topic_arn_good}, bad: {topic_arn_bad}, neutral: {topic_arn_neutral}"
        )

    async def on_feedback_add(self, session_id: str, feedback: Dict[str, Any]) -> None:
        """
        Hook called when feedback is added

        Args:
            session_id: The session identifier
            feedback: The feedback dictionary with rating and comment
        """
        try:
            # Extract rating and comment
            rating = feedback.get("rating")
            comment = feedback.get("comment", "")

            # Select the appropriate topic based on rating
            if rating == "up":
                topic_arn = self.topic_arn_good
                rating_text = "positive"
            elif rating == "down":
                topic_arn = self.topic_arn_bad
                rating_text = "negative"
            else:
                topic_arn = self.topic_arn_neutral
                rating_text = "neutral"

            # Create subject
            subject = f"Virtual Agents Feedback {rating_text} on session {session_id}"

            # Format message with session_id and comment
            message = f"Session: {session_id}\n\n{comment}"

            # Log the message for debugging
            logger.debug(f"Sending feedback notification to SNS topic {topic_arn}: {subject}")

            # Send to SNS using asyncio.to_thread for non-blocking operation
            await asyncio.to_thread(
                publish_message,
                topic_arn=topic_arn,
                message=message,
                subject=subject,
                message_attributes={
                    "session_id": {"DataType": "String", "StringValue": session_id},
                    "rating": {"DataType": "String", "StringValue": rating_text},
                },
            )

            logger.info(
                f"Sent feedback notification to SNS topic {topic_arn} for session {session_id} "
                f"with rating: {rating_text}"
            )

        except ImportError as e:
            logger.error(f"Import error in feedback SNS hook: {e}")
        except Exception as e:
            # Log error but don't raise to avoid breaking the main operation
            # The feedback should be stored even if the notification fails
            logger.error(
                f"Error sending feedback to SNS for session {session_id}: {e}",
                exc_info=True,
            )


def create_feedback_hook(topic_arn_good: str, topic_arn_bad: str, topic_arn_neutral: str):
    """
    Create a feedback hook function for mongodb-session-manager

    Args:
        topic_arn_good: SNS topic ARN for positive feedback (rating="up")
        topic_arn_bad: SNS topic ARN for negative feedback (rating="down")
        topic_arn_neutral: SNS topic ARN for neutral feedback (rating=None)

    Returns:
        Hook function that handles feedback operations
    """
    try:
        sns_hook = FeedbackSNSHook(topic_arn_good, topic_arn_bad, topic_arn_neutral)

        def feedback_hook_wrapper(
            original_func, action: str, session_id: str, **kwargs
        ):
            """
            Wrapper that adapts to mongodb-session-manager hook interface

            Args:
                original_func: The original method being wrapped
                action: The action being performed (e.g., "add")
                session_id: The current session ID
                **kwargs: Additional arguments (feedback data)
            """
            # Call the original function first to store the feedback
            if action == "add" and "feedback" in kwargs:
                result = original_func(kwargs["feedback"])

                # Send SNS notification asynchronously
                try:
                    # Get current event loop if available, otherwise create a new one
                    try:
                        loop = asyncio.get_running_loop()
                        # We're in an async context, create task
                        loop.create_task(
                            sns_hook.on_feedback_add(session_id, kwargs["feedback"])
                        )
                    except RuntimeError:
                        # No running loop, run in a new thread to avoid blocking
                        import threading

                        def run_hook():
                            asyncio.run(
                                sns_hook.on_feedback_add(session_id, kwargs["feedback"])
                            )

                        thread = threading.Thread(target=run_hook, daemon=True)
                        thread.start()
                except Exception as e:
                    logger.error(f"Error sending feedback notification to SNS: {e}")
            else:
                # For other operations, just call original
                result = original_func()

            return result

        return feedback_hook_wrapper

    except Exception as e:
        logger.error(f"Failed to create feedback hook: {e}")
        return None
