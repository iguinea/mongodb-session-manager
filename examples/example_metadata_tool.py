#!/usr/bin/env python3
"""
Example demonstrating the metadata tool for agents.

📚 **Related Documentation:**
   - User Guide: docs/examples/metadata-patterns.md
   - Metadata Management: docs/user-guide/metadata-management.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_metadata_tool.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example shows how agents can use the metadata tool to dynamically
manage session metadata during conversations.
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
DATABASE_NAME = os.getenv("DATABASE_NAME", "metadata_tool_demo")

def print_section(title: str):
    """Helper to print formatted section headers."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}\n")

async def main():
    print_section("MongoDB Session Manager - Metadata Tool Example")
    
    # Create session manager
    session_id = f"metadata-tool-demo-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    session_manager = create_mongodb_session_manager(
        session_id=session_id,
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="sessions_with_tools"
    )
    
    # Get the metadata tool
    metadata_tool = session_manager.get_metadata_tool()
    
    # Create agent with the metadata tool
    agent = Agent(
        model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
        agent_id="metadata-tool-agent",
        session_manager=session_manager,
        tools=[metadata_tool],
        system_prompt="""You are a helpful assistant with access to session metadata management.
        
        You can use the manage_metadata tool to:
        - Get current metadata: manage_metadata("get")
        - Get specific keys: manage_metadata("get", keys=["key1", "key2"])
        - Set/update metadata: manage_metadata("set", {"key": "value"})
        - Delete metadata keys: manage_metadata("delete", keys=["key1", "key2"])
        
        Use metadata to track conversation context, user preferences, and session state."""
    )
    
    try:
        # Step 1: Agent sets initial metadata
        print_section("Step 1: Agent Setting Initial Metadata")
        
        response = await agent.invoke_async(
            "Please set up initial metadata for our conversation. "
            "Set my name as 'Alice', language preference as 'English', "
            "and conversation topic as 'AI Technology'."
        )
        print("User: Please set up initial metadata...")
        print(f"Agent: {response}")
        
        # Step 2: Agent retrieves metadata
        print_section("Step 2: Agent Retrieving Metadata")
        
        response = await agent.invoke_async(
            "Can you check what metadata we have stored so far?"
        )
        print("User: Can you check what metadata we have stored so far?")
        print(f"Agent: {response}")
        
        # Step 3: Agent updates specific fields
        print_section("Step 3: Agent Updating Metadata")
        
        response = await agent.invoke_async(
            "I'd like to change my language preference to Spanish and "
            "add a new field for timezone set to 'UTC-5'."
        )
        print("User: I'd like to change my language preference...")
        print(f"Agent: {response}")
        
        # Step 4: Agent retrieves specific keys
        print_section("Step 4: Agent Getting Specific Keys")
        
        response = await agent.invoke_async(
            "What are my current language preference and timezone?"
        )
        print("User: What are my current language preference and timezone?")
        print(f"Agent: {response}")
        
        # Step 5: Agent uses metadata in conversation
        print_section("Step 5: Agent Using Metadata Context")
        
        response = await agent.invoke_async(
            "Based on what you know about me from the metadata, "
            "can you greet me appropriately?"
        )
        print("User: Based on what you know about me...")
        print(f"Agent: {response}")
        
        # Step 6: Agent cleans up metadata
        print_section("Step 6: Agent Cleaning Up Metadata")
        
        response = await agent.invoke_async(
            "Please remove the conversation topic from metadata as we're "
            "finishing up, but keep my name and preferences."
        )
        print("User: Please remove the conversation topic...")
        print(f"Agent: {response}")
        
        # Step 7: Final metadata check
        print_section("Step 7: Final Metadata State")
        
        response = await agent.invoke_async(
            "Show me the final state of our metadata."
        )
        print("User: Show me the final state of our metadata.")
        print(f"Agent: {response}")
        
        # Sync agent to persist everything
        session_manager.sync_agent(agent)
        
        print_section("Summary")
        print("Key features demonstrated:")
        print("✓ Agent can autonomously manage session metadata")
        print("✓ Metadata persists throughout the conversation")
        print("✓ Agent can retrieve all or specific metadata fields")
        print("✓ Agent can update and delete metadata as needed")
        print("✓ Metadata provides context for personalized responses")
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        session_manager.close()
        print("\n✅ Example completed!")

if __name__ == "__main__":
    asyncio.run(main())