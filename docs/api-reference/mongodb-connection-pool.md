# MongoDBConnectionPool API Reference

## Overview

`MongoDBConnectionPool` is a singleton class that manages a shared MongoDB client instance for efficient connection reuse across multiple session managers. It's specifically designed for stateless environments like FastAPI where creating new connections for each request would be inefficient.

Key features:
- **Singleton Pattern**: Ensures only one MongoDB client instance exists application-wide
- **Thread-Safe**: Safe for concurrent access from multiple threads
- **Optimized Defaults**: Pre-configured with settings for high-concurrency environments
- **Connection Statistics**: Built-in monitoring and health checks
- **Lazy Initialization**: Client is created only when first needed
- **Parameter Change Detection**: Automatically recreates client if connection parameters change

## Class Definition

```python
class MongoDBConnectionPool:
    """Singleton MongoDB connection pool for efficient connection reuse."""
```

**Module**: `mongodb_session_manager.mongodb_connection_pool`

**Pattern**: Singleton (only one instance can exist)

---

## Architecture

### Singleton Pattern

The connection pool uses the double-checked locking singleton pattern to ensure thread-safe initialization:

```python
_instance: Optional[MongoDBConnectionPool] = None
_lock: Lock = Lock()  # Thread synchronization

def __new__(cls) -> MongoDBConnectionPool:
    """Ensure singleton pattern."""
    if cls._instance is None:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
    return cls._instance
```

This guarantees:
- Only one instance exists across the application
- Thread-safe initialization even under high concurrency
- Minimal overhead after initial creation

### State Management

The pool maintains the following class-level state:
- `_client`: The shared `MongoClient` instance
- `_connection_string`: The connection string used to create the client
- `_client_kwargs`: The configuration parameters used
- `_lock`: Thread lock for synchronized access

---

## Class Methods

### `initialize`

```python
@classmethod
def initialize(
    cls,
    connection_string: str,
    **kwargs: Any
) -> MongoClient
```

Initialize or reinitialize the connection pool with given parameters.

This is the primary method for setting up the connection pool. It should be called once during application startup. If called multiple times with the same parameters, it returns the existing client. If parameters change, it recreates the client.

#### Parameters

- **connection_string** (`str`, required): MongoDB connection string (e.g., `"mongodb://localhost:27017/"`)

- **kwargs** (`Any`): MongoDB client configuration options. User-provided values override the optimized defaults.

#### Default Configuration

The pool uses optimized defaults for high-concurrency environments:

```python
{
    "maxPoolSize": 100,           # Maximum connections in the pool
    "minPoolSize": 10,            # Minimum connections to maintain
    "maxIdleTimeMS": 30000,       # Close idle connections after 30s
    "waitQueueTimeoutMS": 5000,   # Timeout waiting for connection (5s)
    "serverSelectionTimeoutMS": 5000,  # Server selection timeout (5s)
    "connectTimeoutMS": 10000,    # Initial connection timeout (10s)
    "socketTimeoutMS": 30000,     # Socket operation timeout (30s)
    "retryWrites": True,          # Automatic retry for write operations
    "retryReads": True,           # Automatic retry for read operations
}
```

#### Common Configuration Options

You can override any default by passing it as a keyword argument:

**Connection Pool Settings**:
- `maxPoolSize` (int): Maximum connections in the pool (default: 100)
- `minPoolSize` (int): Minimum connections to maintain (default: 10)
- `maxIdleTimeMS` (int): Time before closing idle connections in ms (default: 30000)

**Timeout Settings**:
- `waitQueueTimeoutMS` (int): Max wait time for a connection (default: 5000)
- `serverSelectionTimeoutMS` (int): Max time to select a server (default: 5000)
- `connectTimeoutMS` (int): Initial connection timeout (default: 10000)
- `socketTimeoutMS` (int): Socket operation timeout (default: 30000)

**Reliability Settings**:
- `retryWrites` (bool): Enable automatic write retries (default: True)
- `retryReads` (bool): Enable automatic read retries (default: True)

**Compression**:
- `compressors` (list): Compression algorithms to use (e.g., `["snappy", "zlib"]`)

**Authentication**:
- `authSource` (str): Authentication database name
- `authMechanism` (str): Authentication mechanism (e.g., `"SCRAM-SHA-256"`)

**Write Concern**:
- `w` (int/str): Write concern acknowledgment
- `journal` (bool): Wait for journal sync
- `fsync` (bool): Wait for fsync

#### Returns

`MongoClient`: The shared MongoDB client instance.

#### Raises

- `PyMongoError`: If connection to MongoDB fails.

#### Behavior

1. **First Call**: Creates new MongoClient with provided parameters
2. **Subsequent Calls (same parameters)**: Returns existing client
3. **Subsequent Calls (different parameters)**: Closes old client, creates new one
4. **Connection Test**: Pings the database to verify connectivity

#### Example

```python
from mongodb_session_manager import MongoDBConnectionPool

# Initialize with defaults
client = MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/"
)

# Initialize with custom pool sizes
client = MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=200,
    minPoolSize=20
)

# Initialize with authentication
client = MongoDBConnectionPool.initialize(
    connection_string="mongodb://user:pass@localhost:27017/",
    authSource="admin",
    authMechanism="SCRAM-SHA-256"
)

# Initialize with compression
client = MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    compressors=["snappy", "zlib"]
)

# For production (all options)
client = MongoDBConnectionPool.initialize(
    connection_string="mongodb://prod-cluster:27017/",
    maxPoolSize=500,
    minPoolSize=50,
    maxIdleTimeMS=60000,
    retryWrites=True,
    retryReads=True,
    w="majority",
    journal=True
)
```

### `get_client`

```python
@classmethod
def get_client(cls) -> Optional[MongoClient]
```

Get the current MongoDB client instance.

Returns the existing client if the pool has been initialized, or `None` if not yet initialized.

#### Returns

`Optional[MongoClient]`: The MongoDB client if initialized, `None` otherwise.

#### Example

```python
# Check if pool is initialized
client = MongoDBConnectionPool.get_client()
if client is None:
    print("Pool not initialized yet")
    MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
    client = MongoDBConnectionPool.get_client()

# Use the client
db = client["my_database"]
collection = db["my_collection"]
```

### `close`

```python
@classmethod
def close(cls) -> None
```

Close the MongoDB connection pool and clean up resources.

This method should be called during application shutdown to ensure graceful cleanup of MongoDB connections.

#### Behavior

- Closes the MongoDB client if it exists
- Resets internal state (`_client`, `_connection_string`, `_client_kwargs`)
- Logs success or errors
- Safe to call multiple times

#### Example

```python
# During application shutdown
MongoDBConnectionPool.close()

# In FastAPI shutdown handler
from fastapi import FastAPI

app = FastAPI()

@app.on_event("shutdown")
async def shutdown_event():
    MongoDBConnectionPool.close()
    print("Connection pool closed")
```

### `get_pool_stats`

```python
@classmethod
def get_pool_stats(cls) -> Dict[str, Any]
```

Get connection pool statistics and status information.

Provides visibility into the pool's current state, useful for monitoring and debugging.

#### Returns

`Dict[str, Any]`: Dictionary containing pool statistics.

#### Response Structure

**When Not Initialized**:
```python
{
    "status": "not_initialized"
}
```

**When Connected**:
```python
{
    "status": "connected",
    "connection_string": "mongodb://localhost:27017/",
    "server_version": "7.0.5",
    "pool_config": {
        "maxPoolSize": 100,
        "minPoolSize": 10
    }
}
```

**When Error**:
```python
{
    "status": "error",
    "error": "error message"
}
```

#### Example

```python
# Check pool status
stats = MongoDBConnectionPool.get_pool_stats()

if stats["status"] == "not_initialized":
    print("Pool not yet initialized")
elif stats["status"] == "connected":
    print(f"Connected to MongoDB {stats['server_version']}")
    print(f"Max pool size: {stats['pool_config']['maxPoolSize']}")
elif stats["status"] == "error":
    print(f"Error: {stats['error']}")

# Health check endpoint
def health_check():
    stats = MongoDBConnectionPool.get_pool_stats()
    return {
        "mongodb": stats["status"] == "connected",
        "details": stats
    }
```

---

## Usage Patterns

### Basic Setup (FastAPI)

```python
from fastapi import FastAPI
from mongodb_session_manager import MongoDBConnectionPool

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """Initialize connection pool on startup"""
    MongoDBConnectionPool.initialize(
        connection_string="mongodb://localhost:27017/",
        maxPoolSize=100,
        minPoolSize=10
    )
    print("Connection pool initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """Close connection pool on shutdown"""
    MongoDBConnectionPool.close()
    print("Connection pool closed")

# In your endpoints, get the client
@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    client = MongoDBConnectionPool.get_client()
    db = client["chat_db"]
    collection = db["sessions"]
    session = collection.find_one({"_id": session_id})
    return session
```

### With Session Manager Factory

```python
from mongodb_session_manager import (
    MongoDBConnectionPool,
    MongoDBSessionManagerFactory
)

# Initialize pool first
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=100
)

# Create factory using the pool
client = MongoDBConnectionPool.get_client()
factory = MongoDBSessionManagerFactory(
    client=client,  # Reuses the pooled client
    database_name="chat_db",
    collection_name="sessions"
)

# Create session managers efficiently
manager1 = factory.create_session_manager("session-1")
manager2 = factory.create_session_manager("session-2")
# Both managers share the same connection pool
```

### Configuration for Different Environments

**Development**:
```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=10,  # Smaller pool for local dev
    minPoolSize=1
)
```

**Production**:
```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://prod-cluster:27017/",
    maxPoolSize=500,  # Large pool for production traffic
    minPoolSize=50,
    maxIdleTimeMS=60000,  # Keep connections longer
    retryWrites=True,
    retryReads=True,
    w="majority",  # Ensure durability
    journal=True
)
```

**High-Concurrency API**:
```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://cluster:27017/",
    maxPoolSize=1000,  # Very large pool
    minPoolSize=100,
    waitQueueTimeoutMS=10000,  # Longer wait for connections
    serverSelectionTimeoutMS=10000
)
```

### Monitoring and Health Checks

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health/mongodb")
async def mongodb_health():
    """Health check endpoint for MongoDB connection"""
    stats = MongoDBConnectionPool.get_pool_stats()

    if stats["status"] != "connected":
        return {
            "healthy": False,
            "status": stats["status"],
            "error": stats.get("error")
        }, 503

    return {
        "healthy": True,
        "status": "connected",
        "server_version": stats["server_version"],
        "pool_config": stats["pool_config"]
    }

@app.get("/health/mongodb/detailed")
async def mongodb_detailed_health():
    """Detailed MongoDB health with connection test"""
    stats = MongoDBConnectionPool.get_pool_stats()

    # Additional connection test
    try:
        client = MongoDBConnectionPool.get_client()
        if client:
            # Perform a ping
            client.admin.command('ping')
            stats["ping_successful"] = True
        else:
            stats["ping_successful"] = False
    except Exception as e:
        stats["ping_successful"] = False
        stats["ping_error"] = str(e)

    return stats
```

---

## Performance Characteristics

### Connection Overhead Reduction

**Without Connection Pool** (creating new client per request):
- Connection time: 10-50ms per request
- For 100 req/s: ~1-5 seconds wasted on connections alone
- Memory overhead: Multiple client instances

**With Connection Pool**:
- Connection time: ~0ms (reusing existing connections)
- For 100 req/s: Negligible overhead
- Memory overhead: Single client instance with managed pool

### Concurrent Request Handling

The pool can efficiently handle concurrent requests up to `maxPoolSize`:

```python
# Initialize pool for 100 concurrent requests
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=100
)

# All requests can proceed concurrently
# Request 1 gets connection #1
# Request 2 gets connection #2
# ...
# Request 100 gets connection #100
# Request 101 waits up to waitQueueTimeoutMS for available connection
```

### Memory Usage

Approximate memory usage:
- Each connection: ~1-5 MB depending on workload
- Pool of 100 connections: ~100-500 MB
- Single MongoClient instance: Minimal overhead (~10 MB)

---

## Thread Safety

The connection pool is fully thread-safe:

```python
from concurrent.futures import ThreadPoolExecutor
from mongodb_session_manager import MongoDBConnectionPool

# Initialize once
MongoDBConnectionPool.initialize("mongodb://localhost:27017/")

def worker(worker_id):
    # Each thread safely gets the same client
    client = MongoDBConnectionPool.get_client()
    db = client["test_db"]
    collection = db["test_collection"]

    # Perform operations
    collection.insert_one({"worker": worker_id})

# Safe concurrent access
with ThreadPoolExecutor(max_workers=50) as executor:
    executor.map(worker, range(100))
```

---

## Best Practices

1. **Initialize Early**: Call `initialize()` during application startup, before handling requests.

2. **Use with Factory**: Combine with `MongoDBSessionManagerFactory` for optimal session manager creation.

3. **Configure for Your Load**: Adjust `maxPoolSize` based on expected concurrent connections.

4. **Monitor Stats**: Regularly check `get_pool_stats()` to ensure healthy connections.

5. **Clean Shutdown**: Always call `close()` during application shutdown.

6. **Don't Reinitialize**: Avoid calling `initialize()` multiple times with different parameters during normal operation.

7. **Error Handling**: Handle initialization errors gracefully:
   ```python
   try:
       MongoDBConnectionPool.initialize(connection_string)
   except Exception as e:
       logger.error(f"Failed to initialize pool: {e}")
       # Implement fallback or exit
   ```

---

## Comparison with Direct Client Usage

### Without Connection Pool

```python
# Creating new client per request (INEFFICIENT)
def handle_request(session_id):
    client = MongoClient("mongodb://localhost:27017/")  # 10-50ms overhead
    db = client["chat_db"]
    # ... use client ...
    client.close()  # Resource cleanup
```

**Problems**:
- High latency per request
- Connection exhaustion under load
- Increased memory usage
- Slower application startup

### With Connection Pool

```python
# Reusing pooled client (EFFICIENT)
def handle_request(session_id):
    client = MongoDBConnectionPool.get_client()  # ~0ms overhead
    db = client["chat_db"]
    # ... use client ...
    # No close() needed - connection is pooled
```

**Benefits**:
- Minimal latency overhead
- Efficient resource usage
- Better performance under load
- Faster request handling

---

## Troubleshooting

### Pool Not Initialized

```python
client = MongoDBConnectionPool.get_client()
if client is None:
    # Initialize the pool
    MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
```

### Connection Timeout

If experiencing timeout errors, increase timeout values:

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    waitQueueTimeoutMS=10000,  # Increased from 5000
    serverSelectionTimeoutMS=10000,  # Increased from 5000
    connectTimeoutMS=20000  # Increased from 10000
)
```

### Pool Exhaustion

If all connections are busy, increase pool size:

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=200,  # Increased from 100
    minPoolSize=20    # Increased from 10
)
```

### Memory Issues

If experiencing high memory usage, decrease pool size:

```python
MongoDBConnectionPool.initialize(
    connection_string="mongodb://localhost:27017/",
    maxPoolSize=50,   # Decreased from 100
    maxIdleTimeMS=15000  # Close idle connections faster
)
```

---

## See Also

- [MongoDBSessionManager](./mongodb-session-manager.md) - High-level session manager
- [MongoDBSessionManagerFactory](./mongodb-session-factory.md) - Factory pattern using connection pool
- [MongoDBSessionRepository](./mongodb-session-repository.md) - Low-level repository
- [User Guide - Connection Pooling](../user-guide/connection-pooling.md)
- [User Guide - Performance Optimization](../user-guide/performance-optimization.md)
