# Connection Pooling User Guide

## Overview

Connection pooling is a critical performance optimization for MongoDB applications, especially in stateless environments like FastAPI. This guide explains how the MongoDB Session Manager implements connection pooling, its benefits, configuration options, and best practices.

## Table of Contents

1. [What is Connection Pooling?](#what-is-connection-pooling)
2. [The Problem Without Pooling](#the-problem-without-pooling)
3. [MongoDBConnectionPool Class](#mongodbconnectionpool-class)
4. [Performance Benefits](#performance-benefits)
5. [Configuration Options](#configuration-options)
6. [Pool Statistics and Monitoring](#pool-statistics-and-monitoring)
7. [When to Use Pooling](#when-to-use-pooling)
8. [Production Settings](#production-settings)
9. [Troubleshooting](#troubleshooting)

## What is Connection Pooling?

Connection pooling is a technique that **reuses existing database connections** instead of creating new ones for each request. The MongoDB Session Manager implements a **singleton pattern** to ensure all session managers share the same connection pool.

### How It Works

```mermaid
graph LR
    A[Request 1] --> B[Connection Pool]
    C[Request 2] --> B
    D[Request 3] --> B
    E[Request N] --> B
    B --> F[MongoDB Connection 1]
    B --> G[MongoDB Connection 2]
    B --> H[MongoDB Connection 3]
    B --> I[...]
    F --> J[(MongoDB)]
    G --> J
    H --> J
    I --> J
```

### Key Concepts

- **Pool**: A collection of pre-established MongoDB connections
- **Singleton**: Only one pool instance exists per application
- **Reuse**: Connections are borrowed from the pool and returned after use
- **Sizing**: Control min/max connections based on workload
- **Timeout**: Control how long to wait for an available connection

## The Problem Without Pooling

### Naive Approach (Anti-Pattern)

```python
# DON'T DO THIS - Creates new connection per request!
@app.post("/chat")
async def chat(session_id: str, message: str):
    # New connection created here
    session_manager = MongoDBSessionManager(
        session_id=session_id,
        connection_string="mongodb://localhost:27017/",
        database_name="chat_db"
    )

    agent = Agent(session_manager=session_manager, ...)
    response = agent(message)

    # Connection closed here
    session_manager.close()

    return {"response": response}
```

### Problems

1. **Connection Overhead**: 10-50ms per request to establish connection
2. **Resource Exhaustion**: Too many connections to MongoDB
3. **Poor Scalability**: Limited concurrent requests
4. **Increased Latency**: Users experience slower response times
5. **Higher Costs**: More CPU and memory usage

### Performance Impact

```
Without Pooling:
- Request 1: 45ms connection + 100ms processing = 145ms total
- Request 2: 42ms connection + 100ms processing = 142ms total
- Request 3: 48ms connection + 100ms processing = 148ms total

With Pooling:
- Request 1: 0ms connection + 100ms processing = 100ms total
- Request 2: 0ms connection + 100ms processing = 100ms total
- Request 3: 0ms connection + 100ms processing = 100ms total

Result: 30-45% faster response times!
```

## MongoDBConnectionPool Class

The `MongoDBConnectionPool` class implements a thread-safe singleton pattern for connection management.

### Architecture

```mermaid
classDiagram
    class MongoDBConnectionPool {
        -_instance: MongoDBConnectionPool
        -_lock: Lock
        -_client: MongoClient
        -_connection_string: str
        -_client_kwargs: dict
        +initialize(connection_string, **kwargs) MongoClient
        +get_client() MongoClient
        +get_pool_stats() dict
        +close() void
    }

    class SessionManager1
    class SessionManager2
    class SessionManagerN

    SessionManager1 --> MongoDBConnectionPool : uses
    SessionManager2 --> MongoDBConnectionPool : uses
    SessionManagerN --> MongoDBConnectionPool : uses
    MongoDBConnectionPool --> MongoClient : manages
    MongoClient --> MongoDB : connects to
```

### Singleton Pattern

```python
from mongodb_session_manager import MongoDBConnectionPool

# First call initializes the pool
client1 = MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=100
)

# Subsequent calls return the same instance
client2 = MongoDBConnectionPool.get_client()

# Both are the same client!
assert client1 is client2
```

### Initialization

```python
from mongodb_session_manager import MongoDBConnectionPool

# Initialize pool with custom settings
client = MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=100,        # Maximum connections
    minPoolSize=10,         # Minimum connections to maintain
    maxIdleTimeMS=30000,    # Close idle connections after 30s
    waitQueueTimeoutMS=5000,# Wait 5s for available connection
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,
    socketTimeoutMS=30000,
    retryWrites=True,
    retryReads=True
)

# Use the client
db = client["my_database"]
collection = db["my_collection"]
```

### Thread Safety

The connection pool is **thread-safe** and uses a lock to prevent race conditions:

```python
import threading
from mongodb_session_manager import MongoDBConnectionPool

def create_session_manager(session_id):
    # Safe to call from multiple threads
    client = MongoDBConnectionPool.get_client()
    # ... create session manager

# Create multiple threads
threads = []
for i in range(10):
    t = threading.Thread(target=create_session_manager, args=(f"session-{i}",))
    threads.append(t)
    t.start()

# All threads share the same connection pool safely
for t in threads:
    t.join()
```

### Default Configuration

The pool initializes with optimized defaults for high concurrency:

```python
{
    "maxPoolSize": 100,              # Max connections in pool
    "minPoolSize": 10,               # Min connections to maintain
    "maxIdleTimeMS": 30000,          # 30s idle timeout
    "waitQueueTimeoutMS": 5000,      # 5s wait timeout
    "serverSelectionTimeoutMS": 5000,# 5s server selection timeout
    "connectTimeoutMS": 10000,       # 10s initial connection timeout
    "socketTimeoutMS": 30000,        # 30s socket operation timeout
    "retryWrites": True,             # Auto-retry write operations
    "retryReads": True               # Auto-retry read operations
}
```

## Performance Benefits

### Connection Overhead Elimination

```python
# Without pooling
import time

start = time.time()
for i in range(100):
    client = MongoClient("mongodb://localhost:27017/")
    db = client["test"]
    collection = db["sessions"]
    collection.find_one({"_id": "test"})
    client.close()
end = time.time()
print(f"Without pooling: {end - start:.2f}s")  # ~4.5 seconds

# With pooling
from mongodb_session_manager import MongoDBConnectionPool

MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
start = time.time()
for i in range(100):
    client = MongoDBConnectionPool.get_client()
    db = client["test"]
    collection = db["sessions"]
    collection.find_one({"_id": "test"})
end = time.time()
print(f"With pooling: {end - start:.2f}s")  # ~1.2 seconds
```

### Concurrent Request Handling

```python
import asyncio
from mongodb_session_manager import MongoDBConnectionPool, MongoDBSessionManager

# Initialize pool once
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=100
)

async def handle_request(session_id: str):
    # Reuses connection from pool - no overhead!
    client = MongoDBConnectionPool.get_client()
    session_manager = MongoDBSessionManager(
        session_id=session_id,
        client=client,  # Pass shared client
        database_name="chat_db"
    )
    # Process request...
    return "done"

# Handle 100 concurrent requests efficiently
async def main():
    tasks = [handle_request(f"session-{i}") for i in range(100)]
    await asyncio.gather(*tasks)

asyncio.run(main())
```

### Reduced Resource Usage

```
Resource Comparison (100 concurrent requests):

Without Pooling:
- MongoDB Connections: 100 (1 per request)
- Connection Time: 4500ms total
- Memory Usage: ~500MB
- CPU Usage: High (connection setup)

With Pooling:
- MongoDB Connections: 10-20 (from pool)
- Connection Time: 0ms (reuse)
- Memory Usage: ~100MB
- CPU Usage: Low (no setup overhead)

Savings: 80% less memory, 95% faster connection time
```

## Configuration Options

### Pool Size Settings

```python
from mongodb_session_manager import MongoDBConnectionPool

# Low traffic application
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=20,   # Small pool
    minPoolSize=2     # Minimal connections
)

# Medium traffic application
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=50,   # Medium pool
    minPoolSize=10    # Keep some ready
)

# High traffic application
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=200,  # Large pool
    minPoolSize=50    # Many ready connections
)
```

### Timeout Settings

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    # How long to wait for an available connection
    waitQueueTimeoutMS=5000,  # 5 seconds

    # How long to wait for server selection
    serverSelectionTimeoutMS=5000,  # 5 seconds

    # Initial connection timeout
    connectTimeoutMS=10000,  # 10 seconds

    # Socket operation timeout
    socketTimeoutMS=30000,  # 30 seconds

    # Close idle connections after
    maxIdleTimeMS=45000  # 45 seconds
)
```

### Write Concern Settings

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    # Write concern
    w="majority",      # Wait for majority of replica set
    journal=True,      # Wait for journal sync
    wtimeoutMS=5000,   # Write timeout

    # Read concern
    readConcernLevel="majority",

    # Retry settings
    retryWrites=True,  # Auto-retry failed writes
    retryReads=True    # Auto-retry failed reads
)
```

### Compression Settings

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    # Enable compression for network efficiency
    compressors=["snappy", "zlib", "zstd"]
)
```

## Pool Statistics and Monitoring

### Getting Pool Stats

```python
from mongodb_session_manager import MongoDBConnectionPool

# Initialize pool
MongoDBConnectionPool.initialize("mongodb://localhost:27017/")

# Get statistics
stats = MongoDBConnectionPool.get_pool_stats()
print(stats)

# Output:
# {
#     "status": "connected",
#     "connection_string": "mongodb://localhost:27017/",
#     "server_version": "7.0.4",
#     "pool_config": {
#         "maxPoolSize": 100,
#         "minPoolSize": 10
#     }
# }
```

### Health Check Example

```python
from fastapi import FastAPI
from mongodb_session_manager import MongoDBConnectionPool

app = FastAPI()

@app.get("/health")
async def health_check():
    """Check MongoDB connection pool health."""
    try:
        stats = MongoDBConnectionPool.get_pool_stats()

        if stats["status"] == "connected":
            return {
                "status": "healthy",
                "mongodb": stats
            }
        else:
            return {
                "status": "unhealthy",
                "mongodb": stats
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
```

### Monitoring Dashboard

```python
from fastapi import FastAPI
from mongodb_session_manager import MongoDBConnectionPool

app = FastAPI()

@app.get("/metrics/mongodb")
async def mongodb_metrics():
    """Get detailed MongoDB connection metrics."""
    stats = MongoDBConnectionPool.get_pool_stats()

    return {
        "connection_pool": {
            "status": stats.get("status"),
            "server_version": stats.get("server_version"),
            "max_pool_size": stats.get("pool_config", {}).get("maxPoolSize"),
            "min_pool_size": stats.get("pool_config", {}).get("minPoolSize"),
        },
        "recommendations": {
            "increase_pool": stats.get("pool_config", {}).get("maxPoolSize", 0) < 50,
            "check_connection": stats.get("status") != "connected"
        }
    }
```

## When to Use Pooling

### Use Connection Pooling When:

1. **Stateless Applications**: FastAPI, Flask, Django
2. **High Traffic**: Many concurrent requests
3. **Microservices**: Each service needs efficient connections
4. **Serverless Functions**: Lambda, Cloud Functions (with caveats)
5. **Long-Running Services**: Continuous operation

### Don't Use Connection Pooling When:

1. **Single-Request Scripts**: One-off data processing
2. **Very Low Traffic**: < 10 requests per minute
3. **Short-Lived Processes**: Process exits immediately

## Production Settings

### FastAPI Application

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager
from mongodb_session_manager import (
    MongoDBConnectionPool,
    close_global_factory
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    # Startup: Initialize connection pool
    MongoDBConnectionPool.initialize(
        connection_string="mongodb://replica1:27017,replica2:27017,replica3:27017/",
        # Production settings
        maxPoolSize=200,                    # High for many concurrent requests
        minPoolSize=50,                     # Keep connections ready
        maxIdleTimeMS=45000,                # 45s idle timeout
        waitQueueTimeoutMS=5000,            # 5s wait for connection
        serverSelectionTimeoutMS=5000,      # 5s server selection
        connectTimeoutMS=10000,             # 10s initial connection
        socketTimeoutMS=30000,              # 30s socket timeout
        retryWrites=True,                   # Auto-retry writes
        retryReads=True,                    # Auto-retry reads
        w="majority",                       # Write concern
        journal=True,                       # Journal sync
        compressors=["snappy", "zlib"]      # Network compression
    )

    yield

    # Shutdown: Close connection pool
    MongoDBConnectionPool.close()

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(session_id: str, message: str):
    # Reuse connection from pool
    client = MongoDBConnectionPool.get_client()
    session_manager = MongoDBSessionManager(
        session_id=session_id,
        client=client,
        database_name="chat_db"
    )
    # ... handle request
```

### High-Availability Configuration

```python
MongoDBConnectionPool.initialize(
    # Replica set connection string
    connection_string=(
        "mongodb://user:pass@replica1:27017,replica2:27017,replica3:27017/"
        "?replicaSet=rs0"
        "&readPreference=primaryPreferred"
        "&maxStalenessSeconds=120"
    ),

    # High availability settings
    maxPoolSize=300,
    minPoolSize=100,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,

    # Retry and failover
    retryWrites=True,
    retryReads=True,

    # Write concern for consistency
    w="majority",
    journal=True,
    wtimeoutMS=5000
)
```

### Resource-Constrained Environments

```python
# For Fargate with 1 vCPU or similar
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=20,      # Smaller pool
    minPoolSize=5,       # Fewer minimum connections
    maxIdleTimeMS=30000, # Close idle connections faster
    waitQueueTimeoutMS=3000
)
```

### Development Settings

```python
# Local development
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=10,      # Small pool
    minPoolSize=2,       # Minimal connections
    maxIdleTimeMS=60000  # Keep connections longer
)
```

## Troubleshooting

### Problem: Connection Pool Exhausted

**Symptoms**: Requests timeout waiting for connections

**Solution**: Increase pool size

```python
# Check current stats
stats = MongoDBConnectionPool.get_pool_stats()
print(f"Max pool size: {stats['pool_config']['maxPoolSize']}")

# Increase if needed
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=200,  # Increased from 100
    waitQueueTimeoutMS=10000  # Longer timeout
)
```

### Problem: Too Many Open Connections

**Symptoms**: MongoDB complains about too many connections

**Solution**: Reduce pool size or increase idle timeout

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=50,      # Reduced from 200
    maxIdleTimeMS=15000  # Close idle connections faster
)
```

### Problem: Slow Connection Establishment

**Symptoms**: First request is slow, then fast

**Solution**: Increase minimum pool size

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    minPoolSize=25,  # More pre-established connections
    maxPoolSize=100
)
```

### Problem: Connection Timeouts

**Symptoms**: Requests fail with timeout errors

**Solution**: Increase timeout settings

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    waitQueueTimeoutMS=10000,         # Increased from 5000
    serverSelectionTimeoutMS=10000,   # Increased from 5000
    socketTimeoutMS=60000             # Increased from 30000
)
```

### Problem: Memory Usage Too High

**Symptoms**: Application uses too much memory

**Solution**: Reduce pool size and idle timeout

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=30,      # Reduced pool
    maxIdleTimeMS=20000  # Close idle connections faster
)
```

### Debugging Connection Issues

```python
import logging

# Enable MongoDB logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("pymongo").setLevel(logging.DEBUG)

# Initialize pool with logging
client = MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/"
)

# Check connection
try:
    client.admin.command('ping')
    print("Connection successful!")
except Exception as e:
    print(f"Connection failed: {e}")

# Get detailed stats
stats = MongoDBConnectionPool.get_pool_stats()
print(f"Pool status: {stats}")
```

## Best Practices

1. **Initialize Once**: Create the pool during application startup
2. **Share Globally**: Use the singleton instance everywhere
3. **Monitor Stats**: Track pool usage and adjust sizing
4. **Set Timeouts**: Always configure appropriate timeouts
5. **Handle Errors**: Implement retry logic for transient failures
6. **Clean Shutdown**: Close the pool during application shutdown
7. **Size Appropriately**: Match pool size to workload
8. **Use Compression**: Enable for better network efficiency
9. **Configure Retries**: Enable automatic retry for resilience
10. **Test Under Load**: Verify pool settings with realistic traffic

## Next Steps

- **[Factory Pattern](factory-pattern.md)**: Learn how to use the factory pattern with connection pooling
- **[Session Management](session-management.md)**: Understand session lifecycle
- **[Production Deployment](../deployment/production.md)**: Deploy with optimal settings

## Additional Resources

- [MongoDB Connection Pool Documentation](https://pymongo.readthedocs.io/en/stable/api/pymongo/mongo_client.html)
- [Performance Benchmarks](../examples/performance-benchmarks.md)
- [Architecture Overview](../architecture/connection-management.md)
