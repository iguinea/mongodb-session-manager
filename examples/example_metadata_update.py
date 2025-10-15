#!/usr/bin/env python3
"""
Example demonstrating metadata update functionality with field preservation.

📚 **Related Documentation:**
   - User Guide: docs/examples/metadata-patterns.md
   - Metadata Management: docs/user-guide/metadata-management.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_metadata_update.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example shows how the updated metadata methods preserve existing metadata fields
while only updating specified fields.
"""

import asyncio
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent
import os
from datetime import datetime

# Get MongoDB connection from environment or use local

MONGO_CONNECTION = os.getenv(
    "MONGODB_URI", "mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/"
)
DATABASE_NAME = os.getenv("DATABASE_NAME", "metadata_demo")


def print_section(title: str):
    """Helper to print formatted section headers."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}\n")


async def main():
    print_section("MongoDB Session Manager - Metadata Update Example")

    # Create session manager
    session_id = f"metadata-demo-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    session_manager = create_mongodb_session_manager(
        session_id=session_id,
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="sessions_with_metadata",
    )

    # Create agent
    agent = Agent(
        model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
        agent_id="metadata-demo-agent",
        session_manager=session_manager,
        system_prompt="You are a helpful assistant for metadata demonstration.",
    )

    try:
        # Step 1: Initialize with some metadata
        print_section("Step 1: Setting Initial Metadata")

        initial_metadata = {
            "user_id": "user-12345",
            "user_name": "Alice Johnson",
            "session_type": "support",
            "priority": "high",
            "department": "customer_service",
            "created_by": "system",
        }

        session_manager.update_metadata(initial_metadata)
        print("Initial metadata set:")
        for key, value in initial_metadata.items():
            print(f"  {key}: {value}")

        # Retrieve and display metadata
        metadata = session_manager.get_metadata()
        print(f"\nRetrieved metadata: {metadata}")

        # Step 2: Update only specific fields (preserving others)
        print_section("Step 2: Updating Specific Fields")

        update_fields = {
            "priority": "medium",  # Changed from high
            "assigned_to": "agent-bob",  # New field
            "last_updated": datetime.now().isoformat(),  # New field
        }

        session_manager.update_metadata(update_fields)
        print("Updated fields:")
        for key, value in update_fields.items():
            print(f"  {key}: {value}")

        # Retrieve and display updated metadata
        metadata = session_manager.get_metadata()
        print(f"\nFull metadata after update:")
        if metadata and "metadata" in metadata:
            for key, value in metadata["metadata"].items():
                print(f"  {key}: {value}")

        # Step 3: Add more fields without affecting existing ones
        print_section("Step 3: Adding New Fields")

        additional_fields = {
            "tags": ["vip", "technical", "resolved"],
            "resolution_notes": "Issue resolved with password reset",
            "satisfaction_score": 4.5,
        }

        session_manager.update_metadata(additional_fields)
        print("Added fields:")
        for key, value in additional_fields.items():
            print(f"  {key}: {value}")

        # Show complete metadata
        metadata = session_manager.get_metadata()
        print(f"\nComplete metadata:")
        if metadata and "metadata" in metadata:
            for key, value in metadata["metadata"].items():
                print(
                    f"  {key}: {value if not isinstance(value, list) else ', '.join(map(str, value))}"
                )

        # Step 4: Delete specific metadata fields
        print_section("Step 4: Deleting Specific Fields")

        fields_to_delete = ["created_by", "resolution_notes"]
        session_manager.delete_metadata(fields_to_delete)
        print(f"Deleted fields: {', '.join(fields_to_delete)}")

        # Show final metadata
        metadata = session_manager.get_metadata()
        print(f"\nFinal metadata after deletion:")
        if metadata and "metadata" in metadata:
            for key, value in metadata["metadata"].items():
                print(
                    f"  {key}: {value if not isinstance(value, list) else ', '.join(map(str, value))}"
                )

        # Step 5: Use metadata in conversation context
        print_section("Step 5: Using Metadata in Conversation")

        # Have a conversation
        response = await agent.invoke_async(
            "What's my priority level and who is assigned to help me?"
        )
        print(f"User: What's my priority level and who is assigned to help me?")
        print(f"Agent: {response}")

        # Update metadata based on conversation
        conversation_metadata = {
            "last_interaction": datetime.now().isoformat(),
            "messages_count": 1,
            "agent_responded": True,
        }
        session_manager.update_metadata(conversation_metadata)

        # Sync agent to persist everything
        session_manager.sync_agent(agent)

        print_section("Summary")
        print("Key features demonstrated:")
        print("✓ Partial metadata updates preserve existing fields")
        print("✓ New fields can be added without affecting others")
        print("✓ Specific fields can be deleted")
        print("✓ Metadata persists across session operations")
        print("✓ Complex data types (lists, numbers) are supported")

    except Exception as e:
        print(f"\nError: {e}")

    finally:
        # Clean up
        session_manager.close()
        print("\n✅ Example completed!")


if __name__ == "__main__":
    asyncio.run(main())
