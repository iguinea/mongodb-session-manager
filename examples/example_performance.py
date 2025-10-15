"""Performance comparison example for MongoDB Session Manager.

📚 **Related Documentation:**
   - Architecture: docs/architecture/performance.md
   - Connection Pooling: docs/user-guide/connection-pooling.md

🚀 **How to Run:**
   ```bash
   uv run python examples/example_performance.py
   ```

🔗 **Learn More:** https://github.com/iguinea/mongodb-session-manager/tree/main/docs

This example demonstrates the performance difference between:
1. Creating new connections for each session (old approach)
2. Using connection pooling (optimized approach)
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

import sys
from pathlib import Path
# Add parent directory to path to access src module
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import (
    MongoDBSessionManager,
    MongoDBSessionManagerFactory,
    create_mongodb_session_manager
)


# Configuration
MONGODB_URL = "mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/"
DATABASE_NAME = "performance_test"
COLLECTION_NAME = "sessions"
NUM_SESSIONS = 100
NUM_OPERATIONS_PER_SESSION = 10


async def benchmark_without_pooling(session_ids: List[str]):
    """Benchmark creating new connections for each session."""
    print("\n=== Benchmark WITHOUT Connection Pooling ===")
    start_time = time.time()
    
    for session_id in session_ids:
        # Create new session manager (new connection each time)
        manager = create_mongodb_session_manager(
            session_id=session_id,
            connection_string=MONGODB_URL,
            database_name=DATABASE_NAME,
            collection_name=COLLECTION_NAME
        )
        
        # Perform some operations (simulated)
        # Note: check_session_exists() is not available in base manager
            
        # Close connection
        manager.close()
    
    elapsed = time.time() - start_time
    print(f"Total time: {elapsed:.2f} seconds")
    print(f"Average per session: {elapsed/len(session_ids):.3f} seconds")
    print(f"Operations per second: {(len(session_ids) * NUM_OPERATIONS_PER_SESSION) / elapsed:.2f}")
    
    return elapsed


async def benchmark_with_pooling(session_ids: List[str]):
    """Benchmark using connection pooling."""
    print("\n=== Benchmark WITH Connection Pooling ===")
    
    # Create factory with connection pooling
    factory = MongoDBSessionManagerFactory(
        connection_string=MONGODB_URL,
        database_name=DATABASE_NAME,
        collection_name=COLLECTION_NAME,
        maxPoolSize=50
    )
    
    start_time = time.time()
    
    for session_id in session_ids:
        # Create session manager (reuses connection from pool)
        manager = factory.create_session_manager(session_id)
        
        # Perform some operations
        for i in range(NUM_OPERATIONS_PER_SESSION):
            # Simulate some operations
            # Note: check_session_exists() is not available without cache wrapper
    
    elapsed = time.time() - start_time
    
    print(f"Total time: {elapsed:.2f} seconds")
    print(f"Average per session: {elapsed/len(session_ids):.3f} seconds")
    print(f"Operations per second: {(len(session_ids) * NUM_OPERATIONS_PER_SESSION) / elapsed:.2f}")
    
    # Cleanup
    factory.close()
    
    return elapsed


def simulate_concurrent_requests(session_ids: List[str], use_pooling: bool = True):
    """Simulate concurrent requests like in a real FastAPI application."""
    print(f"\n=== Simulating Concurrent Requests ({'WITH' if use_pooling else 'WITHOUT'} pooling) ===")
    
    factory = None
    if use_pooling:
        # Create shared factory
        factory = MongoDBSessionManagerFactory(
            connection_string=MONGODB_URL,
            database_name=DATABASE_NAME,
            collection_name=COLLECTION_NAME,
            maxPoolSize=50
        )
    
    def process_session(session_id: str):
        """Process a single session (simulates an API request)."""
        if use_pooling:
            manager = factory.create_session_manager(session_id)
        else:
            manager = create_mongodb_session_manager(
                session_id=session_id,
                connection_string=MONGODB_URL,
                database_name=DATABASE_NAME,
                collection_name=COLLECTION_NAME
            )
        
        # Simulate some work
        # Note: check_session_exists() is not available without cache wrapper
        
        if not use_pooling:
            manager.close()
    
    # Use ThreadPoolExecutor to simulate concurrent requests
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(process_session, session_ids))
    
    elapsed = time.time() - start_time
    
    print(f"Total time: {elapsed:.2f} seconds")
    print(f"Requests per second: {len(session_ids) / elapsed:.2f}")
    
    if factory:
        factory.close()
    
    return elapsed


async def main():
    """Run performance benchmarks."""
    print("MongoDB Session Manager Performance Comparison")
    print("=" * 50)
    
    # Generate session IDs
    session_ids = [f"session_{i}" for i in range(NUM_SESSIONS)]
    
    # Sequential benchmarks
    time_without_pooling = await benchmark_without_pooling(session_ids[:20])  # Fewer sessions due to overhead
    time_with_pooling = await benchmark_with_pooling(session_ids)
    
    print(f"\n=== Performance Improvement ===")
    improvement = (time_without_pooling / 20) / (time_with_pooling / NUM_SESSIONS)
    print(f"Speedup: {improvement:.2f}x faster with pooling")
    
    # Concurrent benchmarks
    print("\n" + "=" * 50)
    time_concurrent_without = simulate_concurrent_requests(session_ids[:20], use_pooling=False)
    time_concurrent_with = simulate_concurrent_requests(session_ids, use_pooling=True)
    
    print(f"\n=== Concurrent Performance Improvement ===")
    concurrent_improvement = (time_concurrent_without / 20) / (time_concurrent_with / NUM_SESSIONS)
    print(f"Speedup: {concurrent_improvement:.2f}x faster with pooling")
    
    print("\n=== Summary ===")
    print("Connection pooling provides:")
    print("1. Reduced connection overhead")
    print("2. Better resource utilization")
    print("3. Higher throughput under concurrent load")


if __name__ == "__main__":
    asyncio.run(main())