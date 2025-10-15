# Feedback Collection and Processing Patterns

## 🚀 Runnable Examples

This guide includes multiple code examples. For complete, executable scripts, see:

| Script | Description | Run Command |
|--------|-------------|-------------|
| [example_feedback_hook.py](../../examples/example_feedback_hook.py) | Feedback hooks (audit, validation, notifications) | `uv run python examples/example_feedback_hook.py` |

📁 **All examples**: [View examples directory](../../examples/)

---

This guide demonstrates comprehensive feedback collection patterns with MongoDB Session Manager. Learn how to collect user feedback, validate it, send notifications, analyze patterns, and integrate with FastAPI applications.

## Table of Contents

- [Understanding Feedback System](#understanding-feedback-system)
- [Simple Feedback Collection](#simple-feedback-collection)
- [Feedback with Validation](#feedback-with-validation)
- [Real-time Notification Hooks](#real-time-notification-hooks)
- [Analytics Aggregation](#analytics-aggregation)
- [Combined Feedback and Metadata Tracking](#combined-feedback-and-metadata-tracking)
- [FastAPI Feedback Endpoints](#fastapi-feedback-endpoints)
- [Feedback Analysis Patterns](#feedback-analysis-patterns)
- [Production Best Practices](#production-best-practices)

---

## Understanding Feedback System

The feedback system in MongoDB Session Manager allows you to capture user ratings and comments about agent interactions. It's designed for:

- **User Satisfaction Tracking**: Thumbs up/down ratings
- **Detailed Comments**: User explanations and suggestions
- **Analytics**: Aggregate feedback patterns over time
- **Quality Monitoring**: Identify issues quickly
- **Integration**: Send alerts to support teams

**Feedback Structure:**
```python
{
    "rating": "up" | "down" | None,
    "comment": "User feedback text",
    "created_at": "2024-01-26T10:00:00.123456"  # Auto-added
}
```

**Key Features:**
- Automatic timestamp generation
- Hook system for custom processing
- Support for positive, negative, and neutral feedback
- Analytics-ready storage format
- Non-blocking notification systems

---

## Simple Feedback Collection

Basic feedback collection without hooks or validation.

```python
"""
Simple feedback collection example.
"""

from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent
import asyncio

async def main():
    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="feedback-simple",
        connection_string="mongodb://localhost:27017/",
        database_name="examples"
    )

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager,
        system_prompt="You are a helpful customer service assistant."
    )

    # Have a conversation
    print("=== Conversation ===")
    response = await agent.invoke_async("How do I reset my password?")
    print(f"User: How do I reset my password?")
    print(f"Agent: {response}\n")

    # User provides positive feedback
    print("=== User Feedback: Positive ===")
    session_manager.add_feedback({
        "rating": "up",
        "comment": "Very helpful! Clear instructions."
    })
    print("✓ Positive feedback recorded\n")

    # Another conversation
    response = await agent.invoke_async("Where is my order?")
    print(f"User: Where is my order?")
    print(f"Agent: {response}\n")

    # User provides negative feedback
    print("=== User Feedback: Negative ===")
    session_manager.add_feedback({
        "rating": "down",
        "comment": "Couldn't find my order number."
    })
    print("✓ Negative feedback recorded\n")

    # Get all feedback
    print("=== All Feedback ===")
    feedbacks = session_manager.get_feedbacks()
    print(f"Total feedback entries: {len(feedbacks)}\n")

    for i, feedback in enumerate(feedbacks, 1):
        rating_icon = "👍" if feedback["rating"] == "up" else "👎" if feedback["rating"] == "down" else "➖"
        print(f"{i}. {rating_icon} {feedback['rating'] or 'neutral'}")
        print(f"   Comment: {feedback['comment']}")
        print(f"   Created: {feedback.get('created_at', 'N/A')}\n")

    session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**Expected Output:**
```
=== Conversation ===
User: How do I reset my password?
Agent: To reset your password, go to the login page and click "Forgot Password"...

=== User Feedback: Positive ===
✓ Positive feedback recorded

User: Where is my order?
Agent: To check your order status, you'll need your order number...

=== User Feedback: Negative ===
✓ Negative feedback recorded

=== All Feedback ===
Total feedback entries: 2

1. 👍 up
   Comment: Very helpful! Clear instructions.
   Created: 2024-01-26T10:00:00.123456

2. 👎 down
   Comment: Couldn't find my order number.
   Created: 2024-01-26T10:00:15.789012
```

---

## Feedback with Validation

Validate feedback before storage to ensure data quality.

Reference: `/workspace/examples/example_feedback_hook.py`

```python
"""
Feedback validation using hooks.
Based on /workspace/examples/example_feedback_hook.py
"""

import logging
from datetime import datetime
from mongodb_session_manager import MongoDBSessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def feedback_validation_hook(original_func, action: str, session_id: str, **kwargs):
    """
    Hook that validates feedback before saving.

    Validation rules:
    - Rating must be "up", "down", or None
    - Comment length max 1000 characters
    - Negative feedback must have a comment
    - Comments are trimmed
    - Validation timestamp is added
    """
    if "feedback" in kwargs:
        feedback = kwargs["feedback"]

        # Validate rating
        valid_ratings = ["up", "down", None]
        if feedback.get("rating") not in valid_ratings:
            raise ValueError(
                f"Invalid rating: {feedback.get('rating')}. "
                f"Must be 'up', 'down', or None"
            )

        # Validate comment length
        comment = feedback.get("comment", "")
        MAX_COMMENT_LENGTH = 1000
        if len(comment) > MAX_COMMENT_LENGTH:
            raise ValueError(
                f"Comment too long: {len(comment)} characters "
                f"(max: {MAX_COMMENT_LENGTH})"
            )

        # Ensure comment for negative feedback
        if feedback.get("rating") == "down" and not comment.strip():
            raise ValueError("Please provide a comment when giving negative feedback")

        # Sanitize comment
        feedback["comment"] = comment.strip()

        # Add validation timestamp
        feedback["_validated_at"] = datetime.now().isoformat()

        logger.info(f"[VALIDATION] Feedback validated for session {session_id}")

    return original_func(kwargs["feedback"])


# Usage
session_manager = MongoDBSessionManager(
    session_id="validated-feedback-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples",
    feedbackHook=feedback_validation_hook
)

# Valid feedback
print("=== Adding Valid Feedback ===")
try:
    session_manager.add_feedback({
        "rating": "up",
        "comment": "Great job!"
    })
    print("✓ Positive feedback accepted\n")
except ValueError as e:
    print(f"✗ Error: {e}\n")

# Invalid: Negative feedback without comment
print("=== Testing Validation: No Comment ===")
try:
    session_manager.add_feedback({
        "rating": "down",
        "comment": ""
    })
    print("✓ Feedback accepted\n")
except ValueError as e:
    print(f"✗ Validation caught error: {e}\n")

# Invalid: Bad rating
print("=== Testing Validation: Invalid Rating ===")
try:
    session_manager.add_feedback({
        "rating": "maybe",
        "comment": "Not sure"
    })
    print("✓ Feedback accepted\n")
except ValueError as e:
    print(f"✗ Validation caught error: {e}\n")

# Check what was stored
feedbacks = session_manager.get_feedbacks()
print(f"=== Stored Feedbacks: {len(feedbacks)} ===")
for feedback in feedbacks:
    print(f"Rating: {feedback['rating']}")
    print(f"Comment: {feedback['comment']}")
    print(f"Validated at: {feedback.get('_validated_at', 'N/A')}\n")

session_manager.close()
```

**Expected Output:**
```
=== Adding Valid Feedback ===
[VALIDATION] Feedback validated for session validated-feedback-session
✓ Positive feedback accepted

=== Testing Validation: No Comment ===
✗ Validation caught error: Please provide a comment when giving negative feedback

=== Testing Validation: Invalid Rating ===
✗ Validation caught error: Invalid rating: maybe. Must be 'up', 'down', or None

=== Stored Feedbacks: 1 ===
Rating: up
Comment: Great job!
Validated at: 2024-01-26T10:00:00.123456
```

---

## Real-time Notification Hooks

Send alerts when feedback is received, especially for negative feedback.

Reference: `/workspace/examples/example_feedback_hook.py`

```python
"""
Real-time notification hook for feedback.
Based on /workspace/examples/example_feedback_hook.py
"""

import logging
from typing import Dict, Any, Callable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
                    logger.warning(f"🚨 [ALERT] Negative feedback received for session {session_id}")
                    logger.warning(f"[ALERT] Total negative feedback count: {self.negative_count[session_id]}")
                    logger.warning(f"[ALERT] Comment: {feedback.get('comment', 'No comment')}")

                    # In production, send to:
                    # - Slack channel
                    # - Email to support team
                    # - PagerDuty for critical issues
                    # - Dashboard update
                    self._send_alert(session_id, feedback)

            # Track positive feedback
            elif feedback.get("rating") == "up":
                logger.info(f"✅ [NOTIFICATION] Positive feedback received for session {session_id}")

        return original_func(kwargs["feedback"])

    def _send_alert(self, session_id: str, feedback: Dict[str, Any]):
        """Simulate sending an alert."""
        logger.info(f"[NOTIFICATION] Alert sent for session {session_id}")

        # In production:
        # send_slack_message(channel="#support", text=f"Negative feedback: {feedback['comment']}")
        # send_email(to="support@company.com", subject=f"Negative feedback: {session_id}")


# Usage
from mongodb_session_manager import MongoDBSessionManager

notification_hook = FeedbackNotificationHook(alert_on_negative=True)

session_manager = MongoDBSessionManager(
    session_id="notification-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples",
    feedbackHook=notification_hook
)

# Add positive feedback
print("=== Positive Feedback ===")
session_manager.add_feedback({
    "rating": "up",
    "comment": "Perfect solution!"
})

# Add negative feedback - triggers alert
print("\n=== Negative Feedback ===")
session_manager.add_feedback({
    "rating": "down",
    "comment": "The code had syntax errors"
})

# Multiple negative feedbacks
print("\n=== Multiple Negative Feedbacks ===")
session_manager.add_feedback({
    "rating": "down",
    "comment": "Still doesn't work after fix"
})

session_manager.close()
```

**Expected Output:**
```
=== Positive Feedback ===
✅ [NOTIFICATION] Positive feedback received for session notification-session

=== Negative Feedback ===
🚨 [ALERT] Negative feedback received for session notification-session
[ALERT] Total negative feedback count: 1
[ALERT] Comment: The code had syntax errors
[NOTIFICATION] Alert sent for session notification-session

=== Multiple Negative Feedbacks ===
🚨 [ALERT] Negative feedback received for session notification-session
[ALERT] Total negative feedback count: 2
[ALERT] Comment: Still doesn't work after fix
[NOTIFICATION] Alert sent for session notification-session
```

---

## Analytics Aggregation

Collect feedback metrics and patterns over time.

Reference: `/workspace/examples/example_feedback_hook.py`

```python
"""
Feedback analytics with hooks.
Based on /workspace/examples/example_feedback_hook.py
"""

import logging
from datetime import datetime
from typing import Dict, Any, Callable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
            self.metrics["avg_comment_length"] = (
                ((current_avg * (total - 1)) + comment_length) / total
            )

            # Track by hour
            hour = datetime.now().hour
            self.metrics["feedback_by_hour"][hour] = (
                self.metrics["feedback_by_hour"].get(hour, 0) + 1
            )

            logger.info(f"[ANALYTICS] Feedback recorded - Total: {self.metrics['total_feedback']}")

        return original_func(kwargs["feedback"])

    def get_metrics(self) -> Dict[str, Any]:
        """Get current analytics metrics."""
        return self.metrics.copy()

    def get_satisfaction_score(self) -> float:
        """Calculate satisfaction score (0-100)."""
        total = self.metrics["positive"] + self.metrics["negative"]
        if total == 0:
            return 0.0
        return (self.metrics["positive"] / total) * 100


# Usage
from mongodb_session_manager import MongoDBSessionManager
import json

analytics_hook = FeedbackAnalyticsHook()

session_manager = MongoDBSessionManager(
    session_id="analytics-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples",
    feedbackHook=analytics_hook
)

# Simulate various feedback
print("=== Collecting Feedback ===\n")

feedbacks = [
    {"rating": "up", "comment": "Excellent!"},
    {"rating": "down", "comment": "Could be better with more examples"},
    {"rating": None, "comment": "Just saving this for later"},
    {"rating": "up", "comment": "Very clear explanation"},
    {"rating": "up", "comment": "Thanks!"},
    {"rating": "down", "comment": "The response was incomplete"},
    {"rating": "up", "comment": "Perfect, exactly what I needed"},
]

for i, feedback in enumerate(feedbacks, 1):
    session_manager.add_feedback(feedback)
    print(f"{i}. Added feedback: {feedback['rating'] or 'neutral'}")

# Get final analytics
print("\n=== Final Analytics ===\n")
metrics = analytics_hook.get_metrics()
print(json.dumps(metrics, indent=2))

print(f"\n=== Satisfaction Score ===")
score = analytics_hook.get_satisfaction_score()
print(f"Satisfaction: {score:.1f}%")
print(f"Positive: {metrics['positive']}")
print(f"Negative: {metrics['negative']}")
print(f"Neutral: {metrics['neutral']}")

session_manager.close()
```

**Expected Output:**
```
=== Collecting Feedback ===

1. Added feedback: up
2. Added feedback: down
3. Added feedback: neutral
4. Added feedback: up
5. Added feedback: up
6. Added feedback: down
7. Added feedback: up

=== Final Analytics ===

{
  "total_feedback": 7,
  "positive": 4,
  "negative": 2,
  "neutral": 1,
  "avg_comment_length": 28.7,
  "feedback_by_hour": {
    "10": 7
  }
}

=== Satisfaction Score ===
Satisfaction: 66.7%
Positive: 4
Negative: 2
Neutral: 1
```

---

## Combined Feedback and Metadata Tracking

Track feedback alongside session metadata for richer analytics.

```python
"""
Combined feedback and metadata tracking.
"""

from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent
import asyncio

async def main():
    session_manager = create_mongodb_session_manager(
        session_id="combined-tracking",
        connection_string="mongodb://localhost:27017/",
        database_name="examples"
    )

    # Set user context in metadata
    session_manager.update_metadata({
        "user_id": "user-123",
        "user_tier": "premium",
        "user_name": "Alice",
        "agent_version": "1.5.0"
    })

    # Create agent
    agent = Agent(
        model="claude-3-sonnet-20240229",
        agent_id="assistant",
        session_manager=session_manager
    )

    # Conversation
    response = await agent.invoke_async("Help me debug this error")
    print(f"User: Help me debug this error")
    print(f"Agent: {response}\n")

    # Add feedback with context
    session_manager.add_feedback({
        "rating": "up",
        "comment": "Solved my problem quickly!"
    })

    # Update metadata to track satisfaction
    session_manager.update_metadata({
        "last_feedback_rating": "up",
        "satisfaction_history": ["up"]
    })

    # Another interaction
    response = await agent.invoke_async("Can you explain more?")
    print(f"User: Can you explain more?")
    print(f"Agent: {response}\n")

    # Another feedback
    session_manager.add_feedback({
        "rating": "up",
        "comment": "Clear explanation"
    })

    # Update metadata
    current_metadata = session_manager.get_metadata().get("metadata", {})
    satisfaction_history = current_metadata.get("satisfaction_history", [])
    satisfaction_history.append("up")

    session_manager.update_metadata({
        "last_feedback_rating": "up",
        "satisfaction_history": satisfaction_history,
        "total_positive_feedback": len([r for r in satisfaction_history if r == "up"])
    })

    # View combined data
    print("=== Session Summary ===")
    print("\nMetadata:")
    for key, value in current_metadata.items():
        print(f"  {key}: {value}")

    print("\nFeedback:")
    feedbacks = session_manager.get_feedbacks()
    for i, feedback in enumerate(feedbacks, 1):
        print(f"  {i}. {feedback['rating']}: {feedback['comment']}")

    # Analytics
    positive_count = len([f for f in feedbacks if f["rating"] == "up"])
    print(f"\nAnalytics:")
    print(f"  User Tier: {current_metadata.get('user_tier')}")
    print(f"  Total Feedback: {len(feedbacks)}")
    print(f"  Positive Feedback: {positive_count}")
    print(f"  Satisfaction Rate: {(positive_count/len(feedbacks)*100):.0f}%")

    session_manager.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## FastAPI Feedback Endpoints

Production-ready FastAPI endpoints for feedback collection.

Reference: `/workspace/examples/example_feedback_hook.py`

```python
"""
FastAPI feedback endpoints with validation and notifications.
Based on /workspace/examples/example_feedback_hook.py
"""

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import datetime
import logging

from mongodb_session_manager import (
    get_global_factory,
    initialize_global_factory,
    close_global_factory
)
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Models
class FeedbackRequest(BaseModel):
    rating: Optional[str] = None
    comment: str = ""

    @validator('rating')
    def validate_rating(cls, v):
        if v not in ["up", "down", None]:
            raise ValueError('Rating must be "up", "down", or null')
        return v

    @validator('comment')
    def validate_comment(cls, v):
        if len(v) > 1000:
            raise ValueError('Comment too long (max 1000 characters)')
        return v.strip()

class FeedbackResponse(BaseModel):
    status: str
    message: str
    feedback_id: Optional[str] = None

class FeedbackListResponse(BaseModel):
    session_id: str
    total_feedbacks: int
    feedbacks: List[dict]

# Validation hook
def feedback_validation_hook(original_func, action: str, session_id: str, **kwargs):
    """Validate feedback before storage."""
    if "feedback" in kwargs:
        feedback = kwargs["feedback"]

        # Ensure negative feedback has comment
        if feedback.get("rating") == "down" and not feedback.get("comment", "").strip():
            raise ValueError("Please provide a comment when giving negative feedback")

        feedback["_validated_at"] = datetime.now().isoformat()

    return original_func(kwargs["feedback"])

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup."""
    logger.info("Starting FastAPI application...")

    factory = initialize_global_factory(
        connection_string="mongodb://localhost:27017/",
        database_name="feedback_api",
        collection_name="sessions"
    )

    app.state.session_factory = factory
    logger.info("Initialized")

    yield

    logger.info("Shutting down...")
    close_global_factory()

# App
app = FastAPI(title="Feedback API", lifespan=lifespan)

@app.post("/api/sessions/{session_id}/feedback", response_model=FeedbackResponse)
async def add_feedback(
    session_id: str,
    feedback_data: FeedbackRequest
):
    """
    Add feedback to a session.

    Args:
        session_id: Session identifier
        feedback_data: Feedback rating and comment

    Returns:
        FeedbackResponse with status
    """
    try:
        factory = get_global_factory()
        session_manager = factory.create_session_manager(
            session_id=session_id,
            feedbackHook=feedback_validation_hook
        )

        # Add feedback
        session_manager.add_feedback({
            "rating": feedback_data.rating,
            "comment": feedback_data.comment
        })

        return FeedbackResponse(
            status="success",
            message="Feedback recorded successfully"
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding feedback: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/sessions/{session_id}/feedback", response_model=FeedbackListResponse)
async def get_feedback(session_id: str):
    """
    Get all feedback for a session.

    Args:
        session_id: Session identifier

    Returns:
        List of feedback entries
    """
    try:
        factory = get_global_factory()
        session_manager = factory.create_session_manager(session_id)

        feedbacks = session_manager.get_feedbacks()

        return FeedbackListResponse(
            session_id=session_id,
            total_feedbacks=len(feedbacks),
            feedbacks=feedbacks
        )

    except Exception as e:
        logger.error(f"Error getting feedback: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/sessions/{session_id}/feedback/stats")
async def get_feedback_stats(session_id: str):
    """
    Get feedback statistics for a session.

    Args:
        session_id: Session identifier

    Returns:
        Feedback statistics
    """
    try:
        factory = get_global_factory()
        session_manager = factory.create_session_manager(session_id)

        feedbacks = session_manager.get_feedbacks()

        # Calculate stats
        total = len(feedbacks)
        positive = len([f for f in feedbacks if f.get("rating") == "up"])
        negative = len([f for f in feedbacks if f.get("rating") == "down"])
        neutral = total - positive - negative

        satisfaction = (positive / (positive + negative) * 100) if (positive + negative) > 0 else 0

        return {
            "session_id": session_id,
            "total_feedbacks": total,
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "satisfaction_score": round(satisfaction, 1)
        }

    except Exception as e:
        logger.error(f"Error getting feedback stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**Client Usage:**

```python
# Python client
import requests

# Add feedback
response = requests.post(
    "http://localhost:8000/api/sessions/user-123/feedback",
    json={
        "rating": "up",
        "comment": "Great response!"
    }
)
print(response.json())
# {"status": "success", "message": "Feedback recorded successfully"}

# Get feedback
response = requests.get("http://localhost:8000/api/sessions/user-123/feedback")
data = response.json()
print(f"Total feedbacks: {data['total_feedbacks']}")

# Get stats
response = requests.get("http://localhost:8000/api/sessions/user-123/feedback/stats")
print(response.json())
# {"satisfaction_score": 75.0, "positive": 3, "negative": 1, ...}
```

---

## Feedback Analysis Patterns

Advanced patterns for analyzing feedback data.

```python
"""
Feedback analysis and reporting.
"""

from mongodb_session_manager import create_mongodb_session_manager
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

def analyze_feedback_trends(session_manager):
    """Analyze feedback trends over time."""
    feedbacks = session_manager.get_feedbacks()

    # Group by date
    feedback_by_date = defaultdict(lambda: {"positive": 0, "negative": 0, "neutral": 0})

    for feedback in feedbacks:
        created_at = datetime.fromisoformat(feedback.get("created_at", datetime.now().isoformat()))
        date_key = created_at.date()

        rating = feedback.get("rating")
        if rating == "up":
            feedback_by_date[date_key]["positive"] += 1
        elif rating == "down":
            feedback_by_date[date_key]["negative"] += 1
        else:
            feedback_by_date[date_key]["neutral"] += 1

    return dict(feedback_by_date)

def identify_common_issues(session_manager):
    """Identify common themes in negative feedback."""
    feedbacks = session_manager.get_feedbacks()

    negative_comments = [
        f.get("comment", "")
        for f in feedbacks
        if f.get("rating") == "down"
    ]

    # Simple keyword analysis (in production, use NLP)
    keywords = ["error", "slow", "unclear", "incomplete", "wrong", "confused"]
    keyword_counts = defaultdict(int)

    for comment in negative_comments:
        comment_lower = comment.lower()
        for keyword in keywords:
            if keyword in comment_lower:
                keyword_counts[keyword] += 1

    return dict(keyword_counts)

def calculate_response_quality_score(session_manager):
    """Calculate overall response quality score."""
    feedbacks = session_manager.get_feedbacks()

    if not feedbacks:
        return 0.0

    # Weight: positive = +1, negative = -1, neutral = 0
    scores = []
    for feedback in feedbacks:
        rating = feedback.get("rating")
        if rating == "up":
            scores.append(100)
        elif rating == "down":
            scores.append(0)
        else:
            scores.append(50)

    return statistics.mean(scores)

# Usage
session_manager = create_mongodb_session_manager(
    session_id="analysis-session",
    connection_string="mongodb://localhost:27017/",
    database_name="examples"
)

# Add sample data
sample_feedbacks = [
    {"rating": "up", "comment": "Perfect!"},
    {"rating": "down", "comment": "Too slow and unclear"},
    {"rating": "up", "comment": "Great explanation"},
    {"rating": "down", "comment": "Incomplete answer with errors"},
    {"rating": "up", "comment": "Exactly what I needed"},
]

for feedback in sample_feedbacks:
    session_manager.add_feedback(feedback)

# Analyze
print("=== Feedback Analysis ===\n")

# Trends
trends = analyze_feedback_trends(session_manager)
print("Trends by date:")
for date, counts in trends.items():
    print(f"  {date}: +{counts['positive']} -{counts['negative']} ={counts['neutral']}")

# Common issues
issues = identify_common_issues(session_manager)
print(f"\nCommon issues in negative feedback:")
for keyword, count in sorted(issues.items(), key=lambda x: x[1], reverse=True):
    print(f"  {keyword}: {count} mentions")

# Quality score
quality = calculate_response_quality_score(session_manager)
print(f"\nOverall Quality Score: {quality:.1f}/100")

session_manager.close()
```

---

## Production Best Practices

Best practices for production feedback systems.

```python
"""
Production best practices for feedback systems.
"""

# 1. Rate Limiting
from fastapi import FastAPI, HTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/feedback")
@limiter.limit("5/minute")  # Max 5 feedbacks per minute
async def add_feedback(request: Request, ...):
    pass

# 2. Sanitization
import bleach

def sanitize_feedback(comment: str) -> str:
    """Remove HTML and dangerous content."""
    return bleach.clean(comment, tags=[], strip=True)

# 3. Spam Detection
def is_spam(comment: str) -> bool:
    """Simple spam detection."""
    spam_indicators = ["viagra", "casino", "click here", "limited offer"]
    comment_lower = comment.lower()
    return any(indicator in comment_lower for indicator in spam_indicators)

# 4. Sentiment Analysis (optional)
from textblob import TextBlob

def analyze_sentiment(comment: str) -> dict:
    """Analyze comment sentiment."""
    blob = TextBlob(comment)
    return {
        "polarity": blob.sentiment.polarity,  # -1 to 1
        "subjectivity": blob.sentiment.subjectivity  # 0 to 1
    }

# 5. Combined Production Endpoint
@app.post("/api/feedback")
@limiter.limit("5/minute")
async def add_feedback_production(
    request: Request,
    session_id: str,
    feedback_data: FeedbackRequest
):
    """Production-ready feedback endpoint."""
    try:
        # Sanitize
        comment = sanitize_feedback(feedback_data.comment)

        # Spam check
        if is_spam(comment):
            raise HTTPException(status_code=400, detail="Spam detected")

        # Sentiment analysis
        sentiment = analyze_sentiment(comment)

        # Store feedback
        factory = get_global_factory()
        session_manager = factory.create_session_manager(session_id)

        session_manager.add_feedback({
            "rating": feedback_data.rating,
            "comment": comment,
            "sentiment": sentiment,
            "ip_address": get_remote_address(request),
            "user_agent": request.headers.get("user-agent")
        })

        return {"status": "success"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
```

---

## Try It Yourself

1. **Build a feedback dashboard** that visualizes satisfaction trends
2. **Implement automatic response** to negative feedback
3. **Create a feedback moderation system** with approval workflow
4. **Build a sentiment analysis pipeline** for feedback comments
5. **Set up alerts** for feedback patterns (e.g., 3 negative in a row)

## Troubleshooting

### Feedback Not Saving
```python
# Problem: Feedback doesn't appear
# Solution: Check hook isn't raising exceptions

def my_hook(original_func, action, session_id, **kwargs):
    try:
        # Your logic
        pass
    except Exception as e:
        logger.error(f"Hook error: {e}")
        # Don't raise - let original function proceed

    return original_func(kwargs["feedback"])
```

### Duplicate Feedback
```python
# Problem: Same feedback saved multiple times
# Solution: Implement idempotency

session_manager.update_metadata({
    "last_feedback_id": "unique-id-123"
})

# Check before adding
last_id = session_manager.get_metadata().get("metadata", {}).get("last_feedback_id")
if feedback_id != last_id:
    session_manager.add_feedback(...)
```

## Next Steps

- Explore [AWS Patterns](aws-patterns.md) for SNS feedback notifications
- See [Metadata Patterns](metadata-patterns.md) for context tracking
- Check [FastAPI Integration](fastapi-integration.md) for production APIs

## Reference Files

- `/workspace/examples/example_feedback_hook.py` - Comprehensive hook examples
- `/workspace/src/mongodb_session_manager/mongodb_session_manager.py` - Implementation
- `/workspace/src/mongodb_session_manager/hooks/feedback_sns_hook.py` - SNS integration
