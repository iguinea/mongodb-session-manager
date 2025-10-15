#!/usr/bin/env python3
"""
Example demonstrating agent configuration persistence (model and system_prompt).

📚 **Related Documentation:**
   - User Guide: docs/examples/basic-usage.md
   - API Reference: docs/api-reference/mongodb-session-manager.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_agent_config.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example shows:
1. Automatic capture of model and system_prompt during sync_agent()
2. Retrieving agent configuration with get_agent_config()
3. Updating agent configuration with update_agent_config()
4. Listing all agents with list_agents()
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to access src module
sys.path.insert(0, str(Path(__file__).parent.parent))

from strands import Agent
from mongodb_session_manager import create_mongodb_session_manager


async def main():
    """Demonstrate agent configuration persistence."""

    print("=" * 70)
    print("Agent Configuration Persistence Example")
    print("=" * 70)
    print()

    # Create session manager
    session_manager = create_mongodb_session_manager(
        session_id="config-demo-session",
        connection_string="mongodb://mongodb:mongodb@host.docker.internal:8550/",
        database_name="itzulbira_examples",
        collection_name="config_sessions"
    )
    print(f"✅ Session created: {session_manager.session_id}\n")

    # =========================================================================
    # Part 1: Create agents with different configurations
    # =========================================================================
    print("📝 Part 1: Creating agents with different configurations")
    print("-" * 70)

    # Agent 1: Customer support
    support_agent = Agent(
        agent_id="support-agent",
        name="Customer Support",
        model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
        system_prompt="You are a friendly customer support agent. Help users with their questions.",
        session_manager=session_manager
    )

    # Agent 2: Technical analyst (same model, different system prompt)
    analyst_agent = Agent(
        agent_id="analyst-agent",
        name="Technical Analyst",
        model="eu.anthropic.claude-sonnet-4-20250514-v1:0",  # Same model as support agent
        system_prompt="You are a technical analyst. Provide detailed technical analysis.",
        session_manager=session_manager
    )

    # Use the agents (this triggers sync_agent which captures configuration)
    print("Using support agent...")
    response1 = support_agent("What is your role?")
    print(f"  Response: {str(response1)[:80]}...")

    print("Using analyst agent...")
    response2 = analyst_agent("What is your expertise?")
    print(f"  Response: {str(response2)[:80]}...")
    print()

    # =========================================================================
    # Part 2: Retrieve agent configurations
    # =========================================================================
    print("🔍 Part 2: Retrieving agent configurations")
    print("-" * 70)

    # Get configuration for specific agent
    support_config = session_manager.get_agent_config("support-agent")
    if support_config:
        print("Support Agent Configuration:")
        print(f"  Agent ID: {support_config['agent_id']}")
        print(f"  Model: {support_config.get('model', 'N/A')}")
        print(f"  System Prompt: {support_config.get('system_prompt', 'N/A')[:60]}...")

    print()

    analyst_config = session_manager.get_agent_config("analyst-agent")
    if analyst_config:
        print("Analyst Agent Configuration:")
        print(f"  Agent ID: {analyst_config['agent_id']}")
        print(f"  Model: {analyst_config.get('model', 'N/A')}")
        print(f"  System Prompt: {analyst_config.get('system_prompt', 'N/A')[:60]}...")

    print()

    # =========================================================================
    # Part 3: List all agents in the session
    # =========================================================================
    print("📋 Part 3: Listing all agents in session")
    print("-" * 70)

    all_agents = session_manager.list_agents()
    print(f"Found {len(all_agents)} agents in session:\n")

    for i, agent in enumerate(all_agents, 1):
        print(f"Agent {i}:")
        print(f"  Agent ID: {agent['agent_id']}")
        print(f"  Model: {agent.get('model', 'Not captured yet')}")
        print(f"  System Prompt: {agent.get('system_prompt', 'Not captured yet')[:50]}...")
        print()

    # =========================================================================
    # Part 4: Update agent configuration
    # =========================================================================
    print("✏️  Part 4: Updating agent configuration")
    print("-" * 70)

    print("Updating support agent to use a different model...")
    session_manager.update_agent_config(
        "support-agent",
        model="eu.anthropic.claude-haiku-4-20250514-v1:0"  # Faster model
    )

    print("Updating analyst agent's system prompt...")
    session_manager.update_agent_config(
        "analyst-agent",
        system_prompt="You are a senior technical analyst with 10 years of experience. Provide in-depth analysis."
    )

    print("\nVerifying updates:")
    updated_support = session_manager.get_agent_config("support-agent")
    print(f"  Support agent model: {updated_support.get('model', 'N/A')}")

    updated_analyst = session_manager.get_agent_config("analyst-agent")
    print(f"  Analyst agent prompt: {updated_analyst.get('system_prompt', 'N/A')[:60]}...")
    print()

    # =========================================================================
    # Part 5: Use case - Audit trail
    # =========================================================================
    print("🔍 Part 5: Audit trail use case")
    print("-" * 70)
    print("You can use these methods to:")
    print("  1. Track which models were used for which conversations")
    print("  2. Reproduce agent behavior by recreating with same config")
    print("  3. Analyze model usage patterns and costs")
    print("  4. Ensure compliance by tracking system prompts")
    print()

    print("Example audit output:")
    for agent in session_manager.list_agents():
        print(f"  [{agent['agent_id']}] used model: {agent.get('model', 'Unknown')}")

    print()

    # Clean up
    session_manager.close()
    print("✅ Session closed. Configuration persisted in MongoDB!")
    print()
    print("=" * 70)
    print("To verify, check MongoDB collection:")
    print("  db.config_sessions.find({'_id': 'config-demo-session'})")
    print("  Look for agents.<agent_id>.agent_data.model and .system_prompt")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
