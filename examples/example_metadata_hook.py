#!/usr/bin/env python3
"""
Example demonstrating the metadata hook functionality.

📚 **Related Documentation:**
   - User Guide: docs/examples/metadata-patterns.md
   - Metadata Management: docs/user-guide/metadata-management.md
   - API Reference: docs/api-reference/hooks.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_metadata_hook.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example shows how to use the metadataHook parameter to intercept
and enhance metadata operations with custom logic like auditing,
validation, caching, or synchronization.
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
DATABASE_NAME = os.getenv("DATABASE_NAME", "metadata_hook_demo")

# Example 1: Audit Hook - Logs all metadata operations
def metadata_audit_hook(original_func: Callable, action: str, session_id: str, **kwargs):
    """
    Hook that audits all metadata operations.
    
    Args:
        original_func: The original function (update_metadata, get_metadata, or delete_metadata)
        action: The action being performed ("update", "get", "delete")
        session_id: ID of the session
        **kwargs: Additional arguments (metadata for update, keys for delete)
    """
    # Log before operation
    logger.info(f"[METADATA AUDIT] Starting {action} on session {session_id}")
    if action == "update" and "metadata" in kwargs:
        logger.info(f"[METADATA AUDIT] Update data: {json.dumps(kwargs['metadata'], default=str)}")
    elif action == "delete" and "keys" in kwargs:
        logger.info(f"[METADATA AUDIT] Delete keys: {kwargs['keys']}")
    
    start_time = time.time()
    
    try:
        # Execute original function
        if action == "update":
            result = original_func(kwargs["metadata"])
        elif action == "delete":
            result = original_func(kwargs["keys"])
        else:  # get
            result = original_func()
        
        # Log after operation
        elapsed_time = time.time() - start_time
        logger.info(f"[METADATA AUDIT] {action} completed in {elapsed_time:.3f}s")
        
        if action == "get" and result:
            logger.info(f"[METADATA AUDIT] Retrieved {len(result.get('metadata', {}))} metadata fields")
        
        return result
        
    except Exception as e:
        logger.error(f"[METADATA AUDIT] Error in {action}: {str(e)}")
        raise


# Example 2: Validation Hook - Validates metadata before operations
def metadata_validation_hook(original_func: Callable, action: str, session_id: str, **kwargs):
    """
    Hook that validates metadata operations before executing them.
    """
    # Define validation rules
    PROTECTED_FIELDS = ["_id", "session_id", "created_at", "internal_status"]
    REQUIRED_FIELDS = ["last_updated", "updated_by"]
    MAX_VALUE_LENGTH = 1000
    
    if action == "update" and "metadata" in kwargs:
        metadata = kwargs["metadata"]
        
        # Check for protected fields
        for field in PROTECTED_FIELDS:
            if field in metadata:
                raise ValueError(f"Cannot update protected field: {field}")
        
        # Check for required fields
        for field in REQUIRED_FIELDS:
            if field not in metadata:
                # Auto-add required fields
                metadata[field] = "system" if field == "updated_by" else datetime.now().isoformat()
        
        # Validate value lengths
        for key, value in metadata.items():
            if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
                raise ValueError(f"Value for '{key}' exceeds maximum length of {MAX_VALUE_LENGTH}")
        
        # Add validation timestamp
        metadata["_validated_at"] = datetime.now().isoformat()
        
        logger.info(f"[VALIDATION] Metadata validated for session {session_id}")
        return original_func(metadata)
    
    elif action == "delete" and "keys" in kwargs:
        # Prevent deletion of protected fields
        protected_deletions = [key for key in kwargs["keys"] if key in PROTECTED_FIELDS]
        if protected_deletions:
            raise ValueError(f"Cannot delete protected fields: {protected_deletions}")
        
        return original_func(kwargs["keys"])
    
    else:  # get
        return original_func()


# Example 3: Cache Hook - Implements simple caching for metadata reads
class MetadataCacheHook:
    """Hook that implements caching for metadata operations."""
    
    def __init__(self, ttl_seconds: int = 60):
        self.cache = {}
        self.ttl_seconds = ttl_seconds
    
    def __call__(self, original_func: Callable, action: str, session_id: str, **kwargs):
        if action == "get":
            # Check cache
            cache_key = f"{session_id}:metadata"
            if cache_key in self.cache:
                cached_data, timestamp = self.cache[cache_key]
                if time.time() - timestamp < self.ttl_seconds:
                    logger.info(f"[CACHE] Hit for session {session_id}")
                    return cached_data
            
            # Cache miss - fetch and cache
            logger.info(f"[CACHE] Miss for session {session_id}")
            result = original_func()
            self.cache[cache_key] = (result, time.time())
            return result
        
        elif action in ["update", "delete"]:
            # Invalidate cache on write operations
            cache_key = f"{session_id}:metadata"
            if cache_key in self.cache:
                del self.cache[cache_key]
                logger.info(f"[CACHE] Invalidated for session {session_id}")
            
            # Execute operation
            if action == "update":
                return original_func(kwargs["metadata"])
            else:  # delete
                return original_func(kwargs["keys"])


# Example 4: Combined Hook - Chains multiple hooks together
def create_combined_hook(*hooks):
    """Creates a hook that chains multiple hooks together."""
    def combined_hook(original_func: Callable, action: str, session_id: str, **kwargs):
        # Apply hooks in reverse order to maintain proper chaining
        def apply_hook(func, hook):
            def wrapped_func(*args, **kw):
                # For the innermost function, we need to handle different call signatures
                if args:
                    # This is for the original function calls
                    return func(*args, **kw)
                else:
                    # This is for hook calls
                    return hook(func, action, session_id, **kw)
            return wrapped_func
        
        # Build the chain
        current_func = original_func
        for hook in reversed(hooks):
            current_func = apply_hook(current_func, hook)
        
        # Execute with the kwargs
        if action == "update":
            return current_func(kwargs["metadata"])
        elif action == "delete":
            return current_func(kwargs["keys"])
        else:  # get
            return current_func()
    
    return combined_hook


def print_section(title: str):
    """Helper to print formatted section headers."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}\n")


async def main():
    print_section("MongoDB Session Manager - Metadata Hook Examples")
    
    # Example 1: Using audit hook
    print_section("Example 1: Audit Hook")
    
    session_manager = MongoDBSessionManager(
        session_id="audit-demo-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="audit_sessions",
        metadataHook=metadata_audit_hook
    )
    
    # All operations will be audited
    session_manager.update_metadata({
        "user_id": "user-123",
        "status": "active",
        "preferences": {"theme": "dark"}
    })
    
    metadata = session_manager.get_metadata()
    print(f"Retrieved metadata: {json.dumps(metadata.get('metadata', {}), indent=2)}")
    
    session_manager.delete_metadata(["preferences"])
    session_manager.close()
    
    # Example 2: Using validation hook
    print_section("Example 2: Validation Hook")
    
    session_manager = MongoDBSessionManager(
        session_id="validation-demo-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="validated_sessions",
        metadataHook=metadata_validation_hook
    )
    
    try:
        # This will auto-add required fields
        session_manager.update_metadata({
            "user_name": "Alice",
            "department": "Engineering"
        })
        
        # This will fail - protected field
        session_manager.update_metadata({
            "_id": "cannot-change-this"
        })
    except ValueError as e:
        print(f"Validation error (expected): {e}")
    
    session_manager.close()
    
    # Example 3: Using cache hook
    print_section("Example 3: Cache Hook")
    
    cache_hook = MetadataCacheHook(ttl_seconds=5)
    session_manager = MongoDBSessionManager(
        session_id="cache-demo-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="cached_sessions",
        metadataHook=cache_hook
    )
    
    # First call - cache miss
    session_manager.update_metadata({"data": "initial"})
    metadata1 = session_manager.get_metadata()  # Cache miss
    
    # Second call - cache hit
    metadata2 = session_manager.get_metadata()  # Cache hit
    
    # Update invalidates cache
    session_manager.update_metadata({"data": "updated"})
    metadata3 = session_manager.get_metadata()  # Cache miss
    
    session_manager.close()
    
    # Example 4: Combined hooks
    print_section("Example 4: Combined Hooks")
    
    # Combine audit and validation
    combined_hook = create_combined_hook(
        metadata_audit_hook,
        metadata_validation_hook
    )
    
    session_manager = MongoDBSessionManager(
        session_id="combined-demo-session",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="combined_sessions",
        metadataHook=combined_hook
    )
    
    # Operations will be both audited and validated
    session_manager.update_metadata({
        "project": "metadata-hooks",
        "version": "1.0.0"
    })
    
    # Show that validation added required fields
    metadata = session_manager.get_metadata()
    print(f"Combined hook result: {json.dumps(metadata.get('metadata', {}), indent=2, default=str)}")
    
    session_manager.close()
    
    # Example 5: Using hook with agent
    print_section("Example 5: Hook with Agent Integration")
    
    session_manager = MongoDBSessionManager(
        session_id="agent-hook-demo",
        connection_string=MONGO_CONNECTION,
        database_name=DATABASE_NAME,
        collection_name="agent_sessions",
        metadataHook=metadata_audit_hook
    )
    
    # Create agent
    agent = Agent(
        model="eu.anthropic.claude-sonnet-4-20250514-v1:0",
        agent_id="hooked-agent",
        session_manager=session_manager,
        tools=[session_manager.get_metadata_tool()],
        system_prompt="You are a helpful assistant. Use the metadata tool when asked."
    )
    
    # Agent operations will trigger the hook
    response = await agent.invoke_async(
        "Please set metadata field 'conversation_topic' to 'metadata hooks demo'"
    )
    print(f"Agent response: {response}")
    
    session_manager.close()
    
    print_section("Summary")
    print("Demonstrated metadata hooks:")
    print("✓ Audit Hook - Logs all operations")
    print("✓ Validation Hook - Validates and enriches metadata")
    print("✓ Cache Hook - Improves read performance")
    print("✓ Combined Hooks - Chain multiple behaviors")
    print("✓ Agent Integration - Hooks work with metadata tool")


if __name__ == "__main__":
    asyncio.run(main())