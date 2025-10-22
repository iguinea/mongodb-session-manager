#!/usr/bin/env python3
"""
Example demonstrating the metadata WebSocket hook functionality.

📚 **Related Documentation:**
   - User Guide: docs/examples/aws-patterns.md
   - AWS Integrations: docs/user-guide/aws-integrations.md
   - API Reference: docs/api-reference/hooks.md

🚀 **How to Run:**
   ```bash
   # Set AWS credentials (if not using IAM role)
   export AWS_ACCESS_KEY_ID=your_access_key
   export AWS_SECRET_ACCESS_KEY=your_secret_key
   export AWS_REGION=us-east-1

   # Set API Gateway WebSocket endpoint
   export WEBSOCKET_ENDPOINT=https://abc123.execute-api.us-east-1.amazonaws.com/prod

   uv run python examples/example_metadata_websocket.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example shows how to use the metadata WebSocket hook to send real-time
metadata updates directly to connected WebSocket clients via AWS API Gateway.

**Prerequisites:**
1. AWS API Gateway WebSocket API deployed
2. AWS credentials configured with execute-api:ManageConnections permission
3. WebSocket client connected with connection_id stored in metadata.ws_connection_id

**Use Cases:**
- Real-time session viewer updates
- Live agent state monitoring in dashboards
- Instant progress updates for multi-step workflows
- Chat interfaces showing agent thinking state
"""

import logging
import os
import time
from mongodb_session_manager import (
    MongoDBSessionManager,
    create_metadata_websocket_hook,
    is_metadata_websocket_hook_available,
)
from strands import Agent

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Get configuration from environment
MONGO_CONNECTION = os.getenv(
    "MONGODB_URI", "mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/"
)
DATABASE_NAME = os.getenv("DATABASE_NAME", "websocket_hook_demo")
WEBSOCKET_ENDPOINT = os.getenv(
    "WEBSOCKET_ENDPOINT", "https://abc123.execute-api.us-east-1.amazonaws.com/prod"
)
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Simulated connection ID for demo (in production, this comes from WebSocket $connect event)
DEMO_CONNECTION_ID = os.getenv("DEMO_CONNECTION_ID", "demo-connection-id-123")


def demo_websocket_hook():
    """
    Demonstrates the metadata WebSocket hook for real-time updates.

    This example shows:
    1. How to create a WebSocket hook with API Gateway endpoint
    2. How to store connection_id in metadata
    3. How metadata updates are automatically sent to WebSocket clients
    4. Field filtering to minimize message size
    """
    print("\n" + "=" * 80)
    print("DEMO: Metadata WebSocket Hook - Real-time Updates via API Gateway")
    print("=" * 80)

    # Check if WebSocket hook is available
    if not is_metadata_websocket_hook_available():
        print("❌ WebSocket hook not available (boto3 not installed)")
        print("   Install: pip install boto3")
        return

    print("\n✅ WebSocket hook is available")

    # Step 1: Create WebSocket hook with selective field propagation
    print(
        f"\n📡 Creating WebSocket hook with endpoint: {WEBSOCKET_ENDPOINT[:50]}..."
    )
    print("   Only propagating fields: status, agent_state, progress, last_action")

    websocket_hook = create_metadata_websocket_hook(
        api_gateway_endpoint=WEBSOCKET_ENDPOINT,
        metadata_fields=[
            "status",
            "agent_state",
            "progress",
            "last_action",
        ],  # Only send these fields
        region=AWS_REGION,
    )

    if not websocket_hook:
        print("❌ Failed to create WebSocket hook")
        return

    print("✅ WebSocket hook created successfully")

    # Step 2: Create session manager with WebSocket hook
    print(f"\n🔧 Creating session manager with database: {DATABASE_NAME}")

    session_manager = MongoDBSessionManager(
        session_id="websocket-demo-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        metadataHook=websocket_hook,
    )

    print("✅ Session manager created with WebSocket hook")

    # Step 3: Store WebSocket connection ID in metadata
    print(f"\n🔌 Storing WebSocket connection ID: {DEMO_CONNECTION_ID}")
    print(
        "   ⚠️  NOTE: This simulates a real WebSocket connection. In production,"
    )
    print(
        "      the connection_id comes from API Gateway $connect event."
    )

    session_manager.update_metadata(
        {
            "ws_connection_id": DEMO_CONNECTION_ID,
            "status": "connected",
            "user_id": "demo-user",
            "session_type": "demo",
        }
    )

    print("✅ Connection ID stored in metadata")

    # Step 4: Simulate agent workflow with metadata updates
    print("\n🤖 Simulating agent workflow with real-time metadata updates...")
    print("   Each update will be sent to the WebSocket connection\n")

    # Create a simple agent
    agent = Agent(
        agent_id="demo-agent",
        model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
        session_manager=session_manager,
    )

    # Workflow steps with metadata updates
    workflow_steps = [
        {
            "status": "processing",
            "agent_state": "analyzing",
            "progress": 0,
            "last_action": "User request received",
        },
        {
            "status": "processing",
            "agent_state": "thinking",
            "progress": 25,
            "last_action": "Analyzing context",
        },
        {
            "status": "processing",
            "agent_state": "planning",
            "progress": 50,
            "last_action": "Planning response",
        },
        {
            "status": "processing",
            "agent_state": "executing",
            "progress": 75,
            "last_action": "Generating response",
        },
        {
            "status": "completed",
            "agent_state": "idle",
            "progress": 100,
            "last_action": "Response delivered",
        },
    ]

    for i, step in enumerate(workflow_steps, 1):
        print(f"   Step {i}/{len(workflow_steps)}: {step['last_action']}")
        print(f"      → Status: {step['status']}, State: {step['agent_state']}, Progress: {step['progress']}%")

        # Update metadata - this will trigger WebSocket send
        session_manager.update_metadata(
            {
                "ws_connection_id": DEMO_CONNECTION_ID,  # Always include connection_id
                **step,
                "internal_debug": f"Step {i}",  # This won't be sent (not in metadata_fields)
            }
        )

        print(f"      ✉️  WebSocket message sent to connection {DEMO_CONNECTION_ID}")
        time.sleep(0.5)  # Simulate processing time

    print("\n✅ Workflow completed - all updates sent via WebSocket")

    # Step 5: Demonstrate metadata deletion (sends null values)
    print("\n🗑️  Demonstrating metadata field deletion...")

    session_manager.delete_metadata(["progress", "last_action"])
    print("   ✉️  WebSocket message sent with null values for deleted fields")

    # Step 6: Get final metadata state
    print("\n📊 Final metadata state:")
    final_metadata = session_manager.get_metadata()

    for key, value in final_metadata.items():
        if key != "ws_connection_id":  # Don't print connection_id twice
            print(f"   {key}: {value}")

    print("\n" + "=" * 80)
    print("Demo completed successfully!")
    print("=" * 80)
    print("\n💡 Key Takeaways:")
    print("   1. ws_connection_id must be stored in metadata for hook to work")
    print("   2. Only fields in metadata_fields are sent (minimizes bandwidth)")
    print("   3. Updates are sent asynchronously (non-blocking)")
    print("   4. Connection errors (GoneException) are logged, not raised")
    print("   5. Perfect for real-time UIs (Session Viewer, dashboards, chat)")
    print(
        "\n📖 For production usage, see: docs/user-guide/aws-integrations.md\n"
    )


def demo_without_connection_id():
    """
    Demonstrates what happens when ws_connection_id is not in metadata.
    """
    print("\n" + "=" * 80)
    print("DEMO: Missing ws_connection_id Warning")
    print("=" * 80)

    if not is_metadata_websocket_hook_available():
        return

    print("\n⚠️  Testing behavior when ws_connection_id is missing...")

    websocket_hook = create_metadata_websocket_hook(
        api_gateway_endpoint=WEBSOCKET_ENDPOINT,
        metadata_fields=["status"],
        region=AWS_REGION,
    )

    session_manager = MongoDBSessionManager(
        session_id="no-connection-demo",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        metadataHook=websocket_hook,
    )

    # Try to update metadata without ws_connection_id
    print("\n🔄 Updating metadata WITHOUT ws_connection_id...")

    session_manager.update_metadata({"status": "test"})

    print(
        "   ⚠️  Check logs above - should see warning: 'No ws_connection_id found in metadata'"
    )
    print("   ✅ Metadata still saved to MongoDB (hook failure doesn't block)")
    print("\n" + "=" * 80 + "\n")


def demo_production_pattern():
    """
    Demonstrates production pattern with both WebSocket and SQS hooks.
    """
    print("\n" + "=" * 80)
    print("DEMO: Production Pattern - WebSocket + SQS Hooks")
    print("=" * 80)

    print("\n💼 Production Recommendation:")
    print("   Use BOTH WebSocket and SQS hooks for:")
    print("   - WebSocket: Real-time UI updates (Session Viewer, dashboards)")
    print(
        "   - SQS: Backend processing, auditing, analytics, multi-consumer events"
    )

    print("\n📋 Example Configuration:")
    print(
        """
    from mongodb_session_manager import (
        create_metadata_websocket_hook,
        create_metadata_sqs_hook
    )

    # WebSocket for real-time UI
    websocket_hook = create_metadata_websocket_hook(
        api_gateway_endpoint="https://xyz.execute-api.us-east-1.amazonaws.com/prod",
        metadata_fields=["status", "progress"]
    )

    # SQS for backend processing
    sqs_hook = create_metadata_sqs_hook(
        queue_url="https://sqs.us-east-1.amazonaws.com/123/metadata-events",
        metadata_fields=["status", "priority", "assignee"]
    )

    # Combine hooks with a wrapper
    def combined_hook(original_func, action, session_id, **kwargs):
        # Apply WebSocket hook first (fast, non-blocking)
        result = websocket_hook(original_func, action, session_id, **kwargs)

        # Then apply SQS hook (for backend processing)
        sqs_hook(lambda: result, action, session_id, **kwargs)

        return result

    session_manager = MongoDBSessionManager(
        session_id="prod-session",
        metadataHook=combined_hook
    )
    """
    )

    print("\n🎯 Benefits:")
    print("   ✓ Ultra-low latency for connected users (WebSocket)")
    print("   ✓ Guaranteed delivery for backend systems (SQS)")
    print("   ✓ Multi-consumer support (multiple services read from SQS)")
    print("   ✓ Selective field propagation for each use case")

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    print("\n🚀 Starting Metadata WebSocket Hook Examples\n")

    # Run demos
    demo_websocket_hook()
    demo_without_connection_id()
    demo_production_pattern()

    print("✅ All examples completed!\n")
