#!/usr/bin/env python3
"""
Example demonstrating direct usage of the metadata tool.

📚 **Related Documentation:**
   - User Guide: docs/examples/metadata-patterns.md
   - Metadata Management: docs/user-guide/metadata-management.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_metadata_tool_direct.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example shows how to use the metadata tool directly without
relying on the agent's interpretation.
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
    print_section("Direct Metadata Tool Usage Example")
    
    # Create session manager
    session_id = f"direct-tool-demo-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    session_manager = create_mongodb_session_manager(
        session_id=session_id,
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="direct_tool_sessions"
    )
    
    # Get the metadata tool
    metadata_tool = session_manager.get_metadata_tool()
    
    try:
        # Step 1: Direct tool usage - Set metadata
        print_section("Step 1: Setting Metadata with Tool")
        
        result = metadata_tool(
            action="set",
            metadata={
                "user_name": "Bob Smith",
                "session_type": "demo",
                "preferences": {
                    "theme": "dark",
                    "language": "en",
                    "notifications": True
                },
                "created_at": datetime.now().isoformat()
            }
        )
        print(f"Tool result: {result}")
        
        # Step 2: Get all metadata
        print_section("Step 2: Getting All Metadata")
        
        result = metadata_tool(action="get")
        print(f"Tool result: {result}")
        
        # Step 3: Get specific keys
        print_section("Step 3: Getting Specific Keys")
        
        result = metadata_tool(
            action="get",
            keys=["user_name", "preferences"]
        )
        print(f"Tool result: {result}")
        
        # Step 4: Update metadata (preserves existing)
        print_section("Step 4: Updating Metadata")
        
        result = metadata_tool(
            action="update",
            metadata={
                "session_type": "production",
                "last_activity": datetime.now().isoformat(),
                "interaction_count": 5
            }
        )
        print(f"Tool result: {result}")
        
        # Check the update preserved existing data
        result = metadata_tool(action="get")
        print(f"\nAfter update: {result}")
        
        # Step 5: Delete specific keys
        print_section("Step 5: Deleting Specific Keys")
        
        result = metadata_tool(
            action="delete",
            keys=["created_at", "last_activity"]
        )
        print(f"Tool result: {result}")
        
        # Final state
        result = metadata_tool(action="get")
        print(f"\nFinal metadata: {result}")
        
        # Step 6: Use with an agent
        print_section("Step 6: Agent Using Metadata Tool")
        
        # Create agent with the tool
        agent = Agent(
            model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
            agent_id="tool-demo-agent",
            session_manager=session_manager,
            tools=[metadata_tool],
            system_prompt="You are a helpful assistant with metadata access."
        )
        
        # Agent can now use the metadata
        response = await agent.invoke_async(
            "Check the metadata and tell me about the user's preferences."
        )
        print(f"Agent response: {response}")
        
        # Sync agent
        session_manager.sync_agent(agent)
        
        print_section("Tool Usage Summary")
        print("✓ Direct tool invocation for metadata operations")
        print("✓ Set complex nested metadata structures")
        print("✓ Retrieve all or specific metadata fields")
        print("✓ Update preserves existing metadata")
        print("✓ Delete removes only specified keys")
        print("✓ Tool can be used by agents for dynamic metadata access")
        
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