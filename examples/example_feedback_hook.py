#!/usr/bin/env python3
"""
Example demonstrating the feedback hook functionality.

This example shows how to use the feedbackHook parameter to intercept
and enhance feedback operations with custom logic like auditing,
validation, notifications, and FastAPI integration.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from mongodb_session_manager import MongoDBSessionManager
from strands import Agent
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get MongoDB connection from environment or use local
MONGO_CONNECTION = os.getenv(
    "MONGODB_URI", "mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/"
)
DATABASE_NAME = os.getenv("DATABASE_NAME", "feedback_hook_demo")


# Example 1: Audit Hook - Logs all feedback operations
def feedback_audit_hook(original_func: Callable, action: str, session_id: str, **kwargs):
    """
    Hook that audits all feedback operations.
    
    Args:
        original_func: The original add_feedback function
        action: The action being performed ("add" for feedback)
        session_id: ID of the session
        **kwargs: Additional arguments (feedback object)
    """
    # Log before operation
    logger.info(f"[FEEDBACK AUDIT] Starting {action} feedback on session {session_id}")
    if "feedback" in kwargs:
        feedback = kwargs["feedback"]
        logger.info(f"[FEEDBACK AUDIT] Feedback data: {json.dumps(feedback, default=str)}")
        logger.info(f"[FEEDBACK AUDIT] Rating: {feedback.get('rating', 'none')}, Comment length: {len(feedback.get('comment', ''))}")
    
    start_time = time.time()
    
    try:
        # Execute original function
        result = original_func(kwargs["feedback"])
        
        # Log after operation
        elapsed_time = time.time() - start_time
        logger.info(f"[FEEDBACK AUDIT] Feedback {action} completed in {elapsed_time:.3f}s")
        
        return result
        
    except Exception as e:
        logger.error(f"[FEEDBACK AUDIT] Error in {action}: {str(e)}")
        raise


# Example 2: Validation Hook - Validates feedback before saving
def feedback_validation_hook(original_func: Callable, action: str, session_id: str, **kwargs):
    """
    Hook that validates feedback before saving.
    """
    if "feedback" in kwargs:
        feedback = kwargs["feedback"]
        
        # Validate rating
        valid_ratings = ["up", "down", None]
        if feedback.get("rating") not in valid_ratings:
            raise ValueError(f"Invalid rating: {feedback.get('rating')}. Must be 'up', 'down', or None")
        
        # Validate comment length
        comment = feedback.get("comment", "")
        MAX_COMMENT_LENGTH = 1000
        if len(comment) > MAX_COMMENT_LENGTH:
            raise ValueError(f"Comment too long: {len(comment)} characters (max: {MAX_COMMENT_LENGTH})")
        
        # Ensure comment is not empty if rating is down
        if feedback.get("rating") == "down" and not comment.strip():
            raise ValueError("Please provide a comment when giving negative feedback")
        
        # Sanitize comment (basic example)
        feedback["comment"] = comment.strip()
        
        # Add validation timestamp
        feedback["_validated_at"] = datetime.now().isoformat()
        
        logger.info(f"[VALIDATION] Feedback validated for session {session_id}")
        
    return original_func(kwargs["feedback"])


# Example 3: Notification Hook - Alerts on specific feedback patterns
class FeedbackNotificationHook:
    """Hook that sends notifications for specific feedback patterns."""
    
    def __init__(self, alert_on_negative: bool = True):
        self.alert_on_negative = alert_on_negative
        self.negative_count = {}
    
    def __call__(self, original_func: Callable, action: str, session_id: str, **kwargs):
        if "feedback" in kwargs:
            feedback = kwargs["feedback"]
            
            # Track negative feedback
            if feedback.get("rating") == "down":
                self.negative_count[session_id] = self.negative_count.get(session_id, 0) + 1
                
                if self.alert_on_negative:
                    logger.warning(f"[ALERT] Negative feedback received for session {session_id}")
                    logger.warning(f"[ALERT] Total negative feedback count: {self.negative_count[session_id]}")
                    logger.warning(f"[ALERT] Comment: {feedback.get('comment', 'No comment')}")
                    
                    # In production, this could send email, Slack notification, etc.
                    self._send_alert(session_id, feedback)
            
            # Track positive feedback
            elif feedback.get("rating") == "up":
                logger.info(f"[NOTIFICATION] Positive feedback received for session {session_id}")
        
        return original_func(kwargs["feedback"])
    
    def _send_alert(self, session_id: str, feedback: Dict[str, Any]):
        """Simulate sending an alert (in production, this would integrate with notification services)."""
        logger.info(f"[NOTIFICATION] Alert sent for session {session_id} - would notify support team")


# Example 4: Analytics Hook - Collects feedback metrics
class FeedbackAnalyticsHook:
    """Hook that collects analytics on feedback patterns."""
    
    def __init__(self):
        self.metrics = {
            "total_feedback": 0,
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "avg_comment_length": 0,
            "feedback_by_hour": {}
        }
    
    def __call__(self, original_func: Callable, action: str, session_id: str, **kwargs):
        if "feedback" in kwargs:
            feedback = kwargs["feedback"]
            
            # Update metrics
            self.metrics["total_feedback"] += 1
            
            rating = feedback.get("rating")
            if rating == "up":
                self.metrics["positive"] += 1
            elif rating == "down":
                self.metrics["negative"] += 1
            else:
                self.metrics["neutral"] += 1
            
            # Track comment length
            comment_length = len(feedback.get("comment", ""))
            current_avg = self.metrics["avg_comment_length"]
            total = self.metrics["total_feedback"]
            self.metrics["avg_comment_length"] = ((current_avg * (total - 1)) + comment_length) / total
            
            # Track by hour
            hour = datetime.now().hour
            self.metrics["feedback_by_hour"][hour] = self.metrics["feedback_by_hour"].get(hour, 0) + 1
            
            logger.info(f"[ANALYTICS] Current metrics: {json.dumps(self.metrics, indent=2)}")
        
        return original_func(kwargs["feedback"])
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current analytics metrics."""
        return self.metrics.copy()


# Example 5: Combined Hook - Chains multiple hooks
def create_combined_feedback_hook(*hooks):
    """Creates a hook that chains multiple feedback hooks together."""
    def combined_hook(original_func: Callable, action: str, session_id: str, **kwargs):
        # Apply hooks in sequence
        current_func = original_func
        
        # Build the chain in reverse order
        for hook in reversed(hooks):
            # Create a closure to capture the current hook
            def make_wrapped(hook, next_func):
                def wrapped(feedback):
                    # Call the hook with the proper signature
                    return hook(next_func, action, session_id, feedback=feedback)
                return wrapped
            
            current_func = make_wrapped(hook, current_func)
        
        # Execute with the feedback
        return current_func(kwargs["feedback"])
    
    return combined_hook


def print_section(title: str):
    """Helper to print formatted section headers."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}\n")


async def main():
    print_section("MongoDB Session Manager - Feedback Hook Examples")
    
    # Example 1: Using audit hook
    print_section("Example 1: Audit Hook")
    
    session_manager = MongoDBSessionManager(
        session_id="audit-feedback-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="audit_sessions",
        feedbackHook=feedback_audit_hook
    )
    
    # Add some feedback
    session_manager.add_feedback({
        "rating": "up",
        "comment": "The assistant was very helpful!"
    })
    
    session_manager.add_feedback({
        "rating": "down",
        "comment": "The response was not accurate."
    })
    
    # Get all feedback
    feedbacks = session_manager.get_feedbacks()
    print(f"Total feedbacks: {len(feedbacks)}")
    
    session_manager.close()
    
    # Example 2: Using validation hook
    print_section("Example 2: Validation Hook")
    
    session_manager = MongoDBSessionManager(
        session_id="validation-feedback-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="validated_sessions",
        feedbackHook=feedback_validation_hook
    )
    
    try:
        # This will pass validation
        session_manager.add_feedback({
            "rating": "up",
            "comment": "Great job!"
        })
        
        # This will fail - negative feedback without comment
        session_manager.add_feedback({
            "rating": "down",
            "comment": ""
        })
    except ValueError as e:
        print(f"Validation error (expected): {e}")
    
    try:
        # This will fail - invalid rating
        session_manager.add_feedback({
            "rating": "maybe",
            "comment": "Not sure"
        })
    except ValueError as e:
        print(f"Validation error (expected): {e}")
    
    session_manager.close()
    
    # Example 3: Using notification hook
    print_section("Example 3: Notification Hook")
    
    notification_hook = FeedbackNotificationHook(alert_on_negative=True)
    session_manager = MongoDBSessionManager(
        session_id="notification-feedback-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="notification_sessions",
        feedbackHook=notification_hook
    )
    
    # Add feedback that triggers notifications
    session_manager.add_feedback({
        "rating": "down",
        "comment": "The code had syntax errors"
    })
    
    session_manager.add_feedback({
        "rating": "up",
        "comment": "Perfect solution!"
    })
    
    session_manager.close()
    
    # Example 4: Using analytics hook
    print_section("Example 4: Analytics Hook")
    
    analytics_hook = FeedbackAnalyticsHook()
    session_manager = MongoDBSessionManager(
        session_id="analytics-feedback-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="analytics_sessions",
        feedbackHook=analytics_hook
    )
    
    # Add various feedback
    feedbacks = [
        {"rating": "up", "comment": "Excellent!"},
        {"rating": "down", "comment": "Could be better with more examples"},
        {"rating": None, "comment": "Just saving this for later"},
        {"rating": "up", "comment": "Very clear explanation"},
        {"rating": "up", "comment": "Thanks!"},
    ]
    
    for feedback in feedbacks:
        session_manager.add_feedback(feedback)
    
    print("\nFinal Analytics:")
    print(json.dumps(analytics_hook.get_metrics(), indent=2))
    
    session_manager.close()
    
    # Example 5: Combined hooks
    print_section("Example 5: Combined Hooks")
    
    # Combine validation, audit, and notification
    combined_hook = create_combined_feedback_hook(
        feedback_validation_hook,
        feedback_audit_hook,
        FeedbackNotificationHook(alert_on_negative=True)
    )
    
    session_manager = MongoDBSessionManager(
        session_id="combined-feedback-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="combined_sessions",
        feedbackHook=combined_hook
    )
    
    # This will go through all hooks
    session_manager.add_feedback({
        "rating": "down",
        "comment": "The response was incomplete and unclear"
    })
    
    session_manager.close()
    
    # Example 6: FastAPI Integration Example
    print_section("Example 6: FastAPI Integration Pattern")
    
    print("""
# In your FastAPI application:

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class FeedbackRequest(BaseModel):
    rating: Optional[str] = None
    comment: str = ""

@app.post("/api/sessions/{session_id}/feedback")
async def add_feedback(session_id: str, feedback_data: FeedbackRequest):
    try:
        # Get or create session manager with hooks
        session_manager = factory.create_session_manager(
            session_id=session_id,
            feedbackHook=create_combined_feedback_hook(
                feedback_validation_hook,
                feedback_audit_hook,
                FeedbackNotificationHook()
            )
        )
        
        # Add feedback
        session_manager.add_feedback({
            "rating": feedback_data.rating,
            "comment": feedback_data.comment
        })
        
        return {"status": "success", "message": "Feedback recorded"}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding feedback: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
""")
    
    print_section("Summary")
    print("Demonstrated feedback hooks:")
    print("✓ Audit Hook - Logs all feedback operations")
    print("✓ Validation Hook - Validates feedback before saving")
    print("✓ Notification Hook - Alerts on negative feedback")
    print("✓ Analytics Hook - Collects feedback metrics")
    print("✓ Combined Hooks - Chain multiple behaviors")
    print("✓ FastAPI Pattern - Integration with web endpoints")


if __name__ == "__main__":
    asyncio.run(main())