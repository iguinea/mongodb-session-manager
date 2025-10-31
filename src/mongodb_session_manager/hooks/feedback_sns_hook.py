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

    # Basic usage: Create the SNS hook with three separate topics
    sns_hook = create_feedback_hook(
        topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
        topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
        topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
    )

    # Advanced usage: With configurable message templates and prefixes
    sns_hook_with_templates = create_feedback_hook(
        topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
        topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
        topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral",
        subject_prefix_good="[PROD] ✅ ",
        subject_prefix_bad="[PROD] ⚠️ URGENT: ",
        subject_prefix_neutral="[PROD] ℹ️ ",
        body_prefix_bad="🚨 NEGATIVE FEEDBACK ALERT 🚨\nEnvironment: Production\nSession: {session_id}\nTimestamp: {timestamp}\n---\n"
    )

    # Optional: Disable notifications for specific feedback types by using "none"
    sns_hook_selective = create_feedback_hook(
        topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
        topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
        topic_arn_neutral="none"  # Neutral feedback won't trigger SNS
    )

    # Create session manager with SNS notifications
    session_manager = MongoDBSessionManager(
        session_id="user-session-123",
        connection_string="mongodb://...",
        feedbackHook=sns_hook_with_templates
    )

    # Feedback is routed to the appropriate topic based on rating
    session_manager.add_feedback({
        "rating": "down",  # Routes to topic_arn_bad with custom prefix
        "comment": "The response was incomplete"
    })

    session_manager.add_feedback({
        "rating": "up",  # Routes to topic_arn_good with custom prefix
        "comment": "Great response!"
    })
    ```

Template Variables:
    The following variables are available in prefix templates:
    - {session_id}: The session identifier
    - {rating}: The feedback rating as text ("positive", "negative", or "neutral")
    - {timestamp}: ISO 8601 timestamp of when the feedback was processed

SNS Message Format:
    Subject: "{subject_prefix}Virtual Agents Feedback {positive|negative|neutral} on session {session_id}"

    Message Body:
        {body_prefix}Session: {session_id}

        {comment}

    Note: Prefixes are optional and only included when configured. Without prefixes, the format
    matches the traditional simple format.

    Message Attributes:
        - session_id: String attribute with the session identifier
        - rating: String attribute with "positive", "negative", or "neutral"

    Topic Routing:
        - rating="up" → topic_arn_good (with subject_prefix_good and body_prefix_good)
        - rating="down" → topic_arn_bad (with subject_prefix_bad and body_prefix_bad)
        - rating=None → topic_arn_neutral (with subject_prefix_neutral and body_prefix_neutral)

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
from typing import Dict, Any, Optional
from datetime import datetime, timezone

try:
    from .utils_sns import publish_message
except ImportError:
    logging.warning(
        "custom_aws.sns not available. Please install python-helpers package."
    )
    publish_message = None

logger = logging.getLogger(__name__)


class FeedbackSNSHook:
    """Hook to send feedback notifications to SNS with configurable message templates"""

    def __init__(
        self,
        topic_arn_good: str,
        topic_arn_bad: str,
        topic_arn_neutral: str,
        subject_prefix_good: Optional[str] = None,
        subject_prefix_bad: Optional[str] = None,
        subject_prefix_neutral: Optional[str] = None,
        body_prefix_good: Optional[str] = None,
        body_prefix_bad: Optional[str] = None,
        body_prefix_neutral: Optional[str] = None,
    ):
        """
        Initialize the feedback SNS hook with optional message templates

        Args:
            topic_arn_good: SNS topic ARN for positive feedback (rating="up"). Use "none" to disable.
            topic_arn_bad: SNS topic ARN for negative feedback (rating="down"). Use "none" to disable.
            topic_arn_neutral: SNS topic ARN for neutral feedback (rating=None). Use "none" to disable.
            subject_prefix_good: Optional prefix template for subject when rating="up".
                                Supports variables: {session_id}, {rating}, {timestamp}
            subject_prefix_bad: Optional prefix template for subject when rating="down".
                               Supports variables: {session_id}, {rating}, {timestamp}
            subject_prefix_neutral: Optional prefix template for subject when rating=None.
                                   Supports variables: {session_id}, {rating}, {timestamp}
            body_prefix_good: Optional prefix template for message body when rating="up".
                             Supports variables: {session_id}, {rating}, {timestamp}
            body_prefix_bad: Optional prefix template for message body when rating="down".
                            Supports variables: {session_id}, {rating}, {timestamp}
            body_prefix_neutral: Optional prefix template for message body when rating=None.
                                Supports variables: {session_id}, {rating}, {timestamp}

        Example:
            hook = FeedbackSNSHook(
                topic_arn_good="arn:...",
                topic_arn_bad="arn:...",
                topic_arn_neutral="arn:...",
                subject_prefix_good="[PROD] ✅ ",
                subject_prefix_bad="[PROD] ⚠️ URGENT: ",
                subject_prefix_neutral="[PROD] ℹ️ ",
                body_prefix_bad="🚨 ALERT 🚨\\nEnv: Production\\nSession: {session_id}\\n---\\n",
            )
        """
        if not publish_message:
            raise ImportError(
                "custom_aws.sns module not available. "
                "Please install python-helpers package: pip install python-helpers"
            )

        self.topic_arn_good = topic_arn_good
        self.topic_arn_bad = topic_arn_bad
        self.topic_arn_neutral = topic_arn_neutral

        # Store prefix templates
        self.subject_prefix_good = subject_prefix_good
        self.subject_prefix_bad = subject_prefix_bad
        self.subject_prefix_neutral = subject_prefix_neutral
        self.body_prefix_good = body_prefix_good
        self.body_prefix_bad = body_prefix_bad
        self.body_prefix_neutral = body_prefix_neutral

        logger.info(
            f"Initialized FeedbackSNSHook with topics - "
            f"good: {topic_arn_good}, bad: {topic_arn_bad}, neutral: {topic_arn_neutral}"
        )

    def _apply_template(
        self, template: Optional[str], variables: Dict[str, str]
    ) -> str:
        """
        Apply variable substitution to a template string

        Args:
            template: The template string with {variable} placeholders
            variables: Dictionary of variable values to substitute

        Returns:
            The template with variables replaced, or empty string if template is None
        """
        if template is None:
            return ""

        try:
            return template.format(**variables)
        except KeyError as e:
            logger.warning(f"Template variable {e} not found in variables: {variables}")
            return template
        except Exception as e:
            logger.error(f"Error applying template: {e}")
            return template

    async def on_feedback_add(self, session_id: str, feedback: Dict[str, Any], **kwargs) -> None:
        """
        Hook called when feedback is added

        Args:
            session_id: The session identifier
            feedback: The feedback dictionary with rating and comment
            **kwargs: Additional parameters (session_manager instance for password retrieval)
        """
        try:
            # Extract rating and comment
            rating = feedback.get("rating")
            comment = feedback.get("comment", "")

            # Select the appropriate topic and prefixes based on rating
            if rating == "up":
                topic_arn = self.topic_arn_good
                rating_text = "positive"
                subject_prefix = self.subject_prefix_good
                body_prefix = self.body_prefix_good
            elif rating == "down":
                topic_arn = self.topic_arn_bad
                rating_text = "negative"
                subject_prefix = self.subject_prefix_bad
                body_prefix = self.body_prefix_bad
            else:
                topic_arn = self.topic_arn_neutral
                rating_text = "neutral"
                subject_prefix = self.subject_prefix_neutral
                body_prefix = self.body_prefix_neutral

            # Prepare template variables
            timestamp = datetime.now(timezone.utc).isoformat()
            template_vars = {
                "session_id": session_id,
                "rating": rating_text,
                "timestamp": timestamp,
            }

            # Apply prefixes to subject and body
            subject_prefix_text = self._apply_template(subject_prefix, template_vars)
            body_prefix_text = self._apply_template(body_prefix, template_vars)

            # Create subject with prefix
            base_subject = f"on session {session_id}"
            subject = f"{subject_prefix_text}{base_subject}"

            # Retrieve session viewer password from session_manager
            session_manager = kwargs.get('session_manager')
            session_viewer_password = session_manager.get_session_viewer_password() if session_manager else "N/A"

            # Format message with prefix
            base_message = f"Password: {session_viewer_password}\n\nSession: {session_id}\n\n{comment}"
            message = f"{body_prefix_text}{base_message}"

            message = message.replace("_SESSION_ID_", session_id)
            # Log the message for debugging
            logger.debug(
                f"Sending feedback notification to SNS topic {topic_arn}: {subject}"
            )

            # Send to SNS using asyncio.to_thread for non-blocking operation
            if topic_arn != "none":
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
            else:
                logger.info(
                    f"Skipping feedback notification to SNS topic {topic_arn} for session {session_id} "
                    f"with rating: {rating_text} because topic_arn is none"
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


def create_feedback_hook(
    topic_arn_good: str,
    topic_arn_bad: str,
    topic_arn_neutral: str,
    subject_prefix_good: Optional[str] = None,
    subject_prefix_bad: Optional[str] = None,
    subject_prefix_neutral: Optional[str] = None,
    body_prefix_good: Optional[str] = None,
    body_prefix_bad: Optional[str] = None,
    body_prefix_neutral: Optional[str] = None,
):
    """
    Create a feedback hook function for mongodb-session-manager with optional message templates

    Args:
        topic_arn_good: SNS topic ARN for positive feedback (rating="up"). Use "none" to disable.
        topic_arn_bad: SNS topic ARN for negative feedback (rating="down"). Use "none" to disable.
        topic_arn_neutral: SNS topic ARN for neutral feedback (rating=None). Use "none" to disable.
        subject_prefix_good: Optional prefix template for subject when rating="up".
                            Supports variables: {session_id}, {rating}, {timestamp}
        subject_prefix_bad: Optional prefix template for subject when rating="down".
                           Supports variables: {session_id}, {rating}, {timestamp}
        subject_prefix_neutral: Optional prefix template for subject when rating=None.
                               Supports variables: {session_id}, {rating}, {timestamp}
        body_prefix_good: Optional prefix template for message body when rating="up".
                         Supports variables: {session_id}, {rating}, {timestamp}
        body_prefix_bad: Optional prefix template for message body when rating="down".
                        Supports variables: {session_id}, {rating}, {timestamp}
        body_prefix_neutral: Optional prefix template for message body when rating=None.
                            Supports variables: {session_id}, {rating}, {timestamp}

    Returns:
        Hook function that handles feedback operations

    Example:
        hook = create_feedback_hook(
            topic_arn_good="arn:aws:sns:eu-west-1:123:feedback-good",
            topic_arn_bad="arn:aws:sns:eu-west-1:123:feedback-bad",
            topic_arn_neutral="arn:aws:sns:eu-west-1:123:feedback-neutral",
            subject_prefix_good="[PROD] ✅ ",
            subject_prefix_bad="[PROD] ⚠️ URGENT: ",
            body_prefix_bad="🚨 NEGATIVE FEEDBACK\\nEnv: Production\\nSession: {session_id}\\n---\\n",
        )
    """
    try:
        sns_hook = FeedbackSNSHook(
            topic_arn_good,
            topic_arn_bad,
            topic_arn_neutral,
            subject_prefix_good,
            subject_prefix_bad,
            subject_prefix_neutral,
            body_prefix_good,
            body_prefix_bad,
            body_prefix_neutral,
        )

        def feedback_hook_wrapper(
            original_func, action: str, session_id: str, **kwargs
        ):
            """
            Wrapper that adapts to mongodb-session-manager hook interface

            Args:
                original_func: The original method being wrapped
                action: The action being performed (e.g., "add")
                session_id: The current session ID
                **kwargs: Additional arguments (feedback data, session_manager instance)
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
                            sns_hook.on_feedback_add(session_id, kwargs["feedback"],
                                                    session_manager=kwargs.get("session_manager"))
                        )
                    except RuntimeError:
                        # No running loop, run in a new thread to avoid blocking
                        import threading

                        def run_hook():
                            asyncio.run(
                                sns_hook.on_feedback_add(session_id, kwargs["feedback"],
                                                        session_manager=kwargs.get("session_manager"))
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
