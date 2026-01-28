#!/usr/bin/env python3
"""
Production example demonstrating metadata management for customer support sessions.

📚 **Related Documentation:**
   - User Guide: docs/examples/metadata-patterns.md
   - Metadata Management: docs/user-guide/metadata-management.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_metadata_production.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example shows how to use metadata updates in a real-world customer support
scenario where metadata is gradually built up during the conversation.
"""

import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import json

# Configuration
MONGO_CONNECTION = os.getenv(
    "MONGODB_URI", "mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/"
)
DATABASE_NAME = os.getenv("DATABASE_NAME", "customer_support")


class CustomerSupportSession:
    """Manages a customer support session with progressive metadata updates."""

    def __init__(self, customer_id: str, issue_type: str):
        self.customer_id = customer_id
        self.session_id = (
            f"support-{customer_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        self.issue_type = issue_type
        self.start_time = datetime.now()

        # Create session manager
        self.session_manager = create_mongodb_session_manager(
            session_id=self.session_id,
            connection_string=MONGO_CONNECTION,
            database_name=DATABASE_NAME,
            collection_name="support_sessions",
            metadata_fields=[
                "customer_id",
                "session_start",
                "issue_type",
                "status",
                "channel",
                "language",
                "agent_type",
                "escalation_level",
            ],
        )

        # Create support agent
        self.agent = Agent(
            model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
            agent_id="support-agent",
            session_manager=self.session_manager,
            system_prompt="""You are a helpful customer support agent. 
            Be professional, empathetic, and solution-oriented.""",
        )

        # Initialize session metadata
        self._initialize_metadata()

    def _initialize_metadata(self):
        """Set initial metadata for the support session."""
        initial_metadata = {
            "customer_id": self.customer_id,
            "session_start": self.start_time.isoformat(),
            "issue_type": self.issue_type,
            "status": "active",
            "channel": "web_chat",
            "language": "en",
            "agent_type": "ai",
            "escalation_level": 0,
        }
        self.session_manager.update_metadata(initial_metadata)
        print(f"Session initialized: {self.session_id}")

    async def update_customer_info(self, customer_data: Dict[str, Any]):
        """Update session with customer information."""
        customer_metadata = {
            "customer_name": customer_data.get("name"),
            "customer_email": customer_data.get("email"),
            "customer_tier": customer_data.get("tier", "standard"),
            "account_age_days": customer_data.get("account_age_days", 0),
            "previous_tickets": customer_data.get("previous_tickets", 0),
        }
        self.session_manager.update_metadata(customer_metadata)
        print("Customer information updated in metadata")

    async def categorize_issue(self, category: str, subcategory: str, severity: str):
        """Categorize the support issue."""
        categorization = {
            "issue_category": category,
            "issue_subcategory": subcategory,
            "severity": severity,
            "categorized_at": datetime.now().isoformat(),
            "sla_deadline": (datetime.now() + timedelta(hours=24)).isoformat(),
        }
        self.session_manager.update_metadata(categorization)
        print(f"Issue categorized: {category}/{subcategory} - Severity: {severity}")

    async def add_interaction_metrics(self, sentiment: str, confidence: float):
        """Add metrics about the customer interaction."""
        metrics = {
            "customer_sentiment": sentiment,
            "sentiment_confidence": confidence,
            "last_interaction": datetime.now().isoformat(),
            "interaction_count": await self._get_interaction_count() + 1,
        }
        self.session_manager.update_metadata(metrics)

    async def _get_interaction_count(self) -> int:
        """Get current interaction count from metadata."""
        metadata = self.session_manager.get_metadata(self.session_id)
        if metadata and "metadata" in metadata:
            return metadata["metadata"].get("interaction_count", 0)
        return 0

    async def escalate_to_human(self, reason: str):
        """Escalate the session to a human agent."""
        escalation_data = {
            "escalated": True,
            "escalation_reason": reason,
            "escalation_time": datetime.now().isoformat(),
            "escalation_level": 1,
            "status": "escalated",
        }
        self.session_manager.update_metadata(escalation_data)
        print(f"Session escalated to human agent: {reason}")

    async def resolve_issue(
        self, resolution: str, satisfaction_score: Optional[int] = None
    ):
        """Mark the issue as resolved."""
        resolution_data = {
            "status": "resolved",
            "resolution": resolution,
            "resolved_at": datetime.now().isoformat(),
            "resolution_time_minutes": (datetime.now() - self.start_time).seconds // 60,
        }

        if satisfaction_score is not None:
            resolution_data["satisfaction_score"] = satisfaction_score

        self.session_manager.update_metadata(resolution_data)
        print(f"Issue resolved: {resolution}")

    async def chat(self, message: str) -> str:
        """Send a message to the agent and get response."""
        response = await self.agent(message)
        self.session_manager.sync_agent(self.agent)
        return response

    def get_session_summary(self) -> Dict[str, Any]:
        """Get a summary of the session metadata."""
        metadata = self.session_manager.get_metadata(self.session_id)
        if metadata and "metadata" in metadata:
            return metadata["metadata"]
        return {}

    def cleanup_sensitive_data(self):
        """Remove sensitive information from metadata before archival."""
        sensitive_fields = ["customer_email", "customer_name"]
        self.session_manager.delete_metadata(self.session_id, sensitive_fields)

        # Add archival marker
        archive_metadata = {
            "archived": True,
            "archived_at": datetime.now().isoformat(),
            "data_cleaned": True,
        }
        self.session_manager.update_metadata(archive_metadata)
        print("Sensitive data cleaned for archival")

    def close(self):
        """Close the session."""
        self.session_manager.close()


async def main():
    """Demonstrate a complete customer support workflow with metadata management."""

    print("\n🎯 Customer Support Session with Progressive Metadata Updates\n")

    # Create a support session
    session = CustomerSupportSession(customer_id="CUST-78234", issue_type="technical")

    try:
        # Step 1: Customer provides initial information
        print("\n1️⃣ Customer initiates chat...")

        # Update with customer data (simulating CRM lookup)
        await session.update_customer_info(
            {
                "name": "John Doe",
                "email": "john.doe@example.com",
                "tier": "premium",
                "account_age_days": 456,
                "previous_tickets": 3,
            }
        )

        # Step 2: Initial conversation
        print("\n2️⃣ Starting conversation...")

        response = session.chat(
            "Hi, I'm having trouble with my API integration. "
            "I'm getting 401 errors even though my API key is correct."
        )
        print("Customer: I'm having trouble with my API integration...")
        print(f"Agent: {response[:100]}...")

        # Categorize based on the issue
        await session.categorize_issue(
            category="API", subcategory="Authentication", severity="medium"
        )

        # Update interaction metrics
        await session.add_interaction_metrics(sentiment="frustrated", confidence=0.85)

        # Step 3: Follow-up conversation
        print("\n3️⃣ Troubleshooting...")

        response = session.chat(
            "I've checked the headers and they look correct. "
            "It was working yesterday but stopped this morning."
        )

        await session.add_interaction_metrics(sentiment="concerned", confidence=0.90)

        # Step 4: Check if escalation needed
        print("\n4️⃣ Checking resolution path...")

        # Simulate decision to escalate based on complexity
        current_metadata = session.get_session_summary()
        if (
            current_metadata.get("customer_tier") == "premium"
            and current_metadata.get("previous_tickets", 0) > 2
        ):
            await session.escalate_to_human(
                reason="Premium customer with recurring issues - requires specialized attention"
            )

        # Step 5: Resolution
        print("\n5️⃣ Resolving issue...")

        await session.resolve_issue(
            resolution="API key rotation required due to security update. Customer guided through process.",
            satisfaction_score=4,
        )

        # Step 6: Display final metadata
        print("\n6️⃣ Final Session Metadata:")
        summary = session.get_session_summary()

        print(
            json.dumps(
                {
                    "session_id": session.session_id,
                    "duration_minutes": summary.get("resolution_time_minutes"),
                    "status": summary.get("status"),
                    "escalated": summary.get("escalated", False),
                    "satisfaction_score": summary.get("satisfaction_score"),
                    "issue_category": f"{summary.get('issue_category')}/{summary.get('issue_subcategory')}",
                    "customer_tier": summary.get("customer_tier"),
                    "interaction_count": summary.get("interaction_count"),
                },
                indent=2,
            )
        )

        # Step 7: Clean sensitive data before archival
        print("\n7️⃣ Preparing for archival...")
        session.cleanup_sensitive_data()

        # Show cleaned metadata
        print("\nCleaned metadata (sensitive data removed):")
        final_summary = session.get_session_summary()
        print(f"  - Customer name: {final_summary.get('customer_name', '[REMOVED]')}")
        print(f"  - Customer email: {final_summary.get('customer_email', '[REMOVED]')}")
        print(f"  - Archived: {final_summary.get('archived')}")
        print(f"  - Data cleaned: {final_summary.get('data_cleaned')}")

    except Exception as e:
        print(f"\nError: {e}")

    finally:
        session.close()
        print("\n✅ Support session completed!\n")


if __name__ == "__main__":
    asyncio.run(main())
