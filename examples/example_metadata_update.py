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


def _format_value(value):
    """Format a metadata value for display."""
    if isinstance(value, list):
        return ", ".join(map(str, value))
    return value


def _print_metadata_dict(label, fields):
    """Print a dictionary of metadata fields."""
    print(label)
    for key, value in fields.items():
        print(f"  {key}: {_format_value(value)}")


def _print_stored_metadata(label, session_manager):
    """Retrieve and print stored metadata from session."""
    metadata = session_manager.get_metadata()
    if metadata and "metadata" in metadata:
        _print_metadata_dict(label, metadata["metadata"])


async def _run_demo(session_manager, agent):
    """Run the metadata update demonstration steps."""
    # Step 1: Initialize with some metadata
    print_section("Step 1: Setting Initial Metadata")
    initial_metadata = {
        "user_id": "user-12345", "user_name": "Alice Johnson",
        "session_type": "support", "priority": "high",
        "department": "customer_service", "created_by": "system",
    }
    session_manager.update_metadata(initial_metadata)
    _print_metadata_dict("Initial metadata set:", initial_metadata)
    print(f"\nRetrieved metadata: {session_manager.get_metadata()}")

    # Step 2: Update only specific fields (preserving others)
    print_section("Step 2: Updating Specific Fields")
    update_fields = {
        "priority": "medium", "assigned_to": "agent-bob",
        "last_updated": datetime.now().isoformat(),
    }
    session_manager.update_metadata(update_fields)
    _print_metadata_dict("Updated fields:", update_fields)
    _print_stored_metadata("\nFull metadata after update:", session_manager)

    # Step 3: Add more fields without affecting existing ones
    print_section("Step 3: Adding New Fields")
    additional_fields = {
        "tags": ["vip", "technical", "resolved"],
        "resolution_notes": "Issue resolved with password reset",
        "satisfaction_score": 4.5,
    }
    session_manager.update_metadata(additional_fields)
    _print_metadata_dict("Added fields:", additional_fields)
    _print_stored_metadata("\nComplete metadata:", session_manager)

    # Step 4: Delete specific metadata fields
    print_section("Step 4: Deleting Specific Fields")
    fields_to_delete = ["created_by", "resolution_notes"]
    session_manager.delete_metadata(fields_to_delete)
    print(f"Deleted fields: {', '.join(fields_to_delete)}")
    _print_stored_metadata("\nFinal metadata after deletion:", session_manager)

    # Step 5: Use metadata in conversation context
    print_section("Step 5: Using Metadata in Conversation")
    response = await agent.invoke_async(
        "What's my priority level and who is assigned to help me?"
    )
    print("User: What's my priority level and who is assigned to help me?")
    print(f"Agent: {response}")

    session_manager.update_metadata({
        "last_interaction": datetime.now().isoformat(),
        "messages_count": 1, "agent_responded": True,
    })
    session_manager.sync_agent(agent)

    print_section("Summary")
    print("Key features demonstrated:")
    print("✓ Partial metadata updates preserve existing fields")
    print("✓ New fields can be added without affecting others")
    print("✓ Specific fields can be deleted")
    print("✓ Metadata persists across session operations")
    print("✓ Complex data types (lists, numbers) are supported")


async def main():
    print_section("MongoDB Session Manager - Metadata Update Example")

    session_id = f"metadata-demo-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    session_manager = create_mongodb_session_manager(
        session_id=session_id,
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="sessions_with_metadata",
    )
    agent = Agent(
        model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
        agent_id="metadata-demo-agent",
        session_manager=session_manager,
        system_prompt="You are a helpful assistant for metadata demonstration.",
    )

    try:
        await _run_demo(session_manager, agent)
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        session_manager.close()
        print("\n✅ Example completed!")


if __name__ == "__main__":
    asyncio.run(main())
