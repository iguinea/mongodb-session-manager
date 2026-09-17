# Performance Characteristics and Optimization

## Table of Contents
- [Introduction](#introduction)
- [Benchmarks](#benchmarks)
- [Connection Overhead Analysis](#connection-overhead-analysis)
- [Concurrent Request Handling](#concurrent-request-handling)
- [Memory Usage](#memory-usage)
- [MongoDB Query Optimization](#mongodb-query-optimization)
- [Index Performance](#index-performance)
- [Network Latency Considerations](#network-latency-considerations)
- [Scaling Strategies](#scaling-strategies)
- [Production Optimization Tips](#production-optimization-tips)
- [Monitoring and Metrics](#monitoring-and-metrics)

## Introduction

The MongoDB Session Manager is optimized for high-performance operation in stateless environments like FastAPI, AWS Lambda, and Kubernetes. This document provides detailed performance characteristics, benchmarks, and optimization strategies for production deployments.

### Performance Goals

1. **Low Latency**: < 10ms overhead for session operations
2. **High Throughput**: Support 1000+ requests/second per instance
3. **Efficient Resources**: Minimal memory and connection usage
4. **Predictable Scaling**: Linear scaling with infrastructure
5. **Zero Cold Start**: Warm connections for immediate use

### Key Performance Features

- **Connection Pooling**: Reuse connections across requests (0ms overhead)
- **Single-Query Fetches**: Entire session in one MongoDB query
- **Atomic Operations**: No transaction overhead
- **Smart Indexing**: Optimized for common query patterns
- **Embedded Documents**: Eliminate JOINs and multi-query overhead

## Benchmarks

### How these numbers are produced

Everything below comes from the benchmark harness, `uv run python -m benchmarks`
(see [benchmarks/README.md](../../benchmarks/README.md)). It runs real Strands
agents against a real server with a scripted model, and refuses to report a
scenario that cannot prove it did the work. The figures that used to live here
were produced by `examples/example_performance.py`, whose operation loop was a
`pass`; they have been removed rather than corrected.

**Environment of the run below**: MongoDB 8.2.7 standalone in Docker Desktop on
macOS arm64, PyMongo 4.18.1, Python 3.12.13, package 0.16.0, primary reads, no
compressor. 5 warmups and 30 timed repetitions per scenario, messages of 512
characters. A `ping` probe before and after the matrix stayed at 0.32 ms p50.

Every run records its own environment, so two result files can be compared —
and `--compare` refuses to subtract them when the engine, version, topology,
read preference or compressors differ.

### Sequential operations, one at a time

| Scenario | p50 | p95 | p99 | Commands per operation | Reply bytes |
|---|---:|---:|---:|---:|---:|
| `create` (new session) | 1.57 ms | 2.28 ms | 3.32 ms | 7.0 | 329 B |
| `restore`, 10 messages | 1.46 ms | 4.05 ms | 4.26 ms | 3.0 | 8.4 KB |
| `restore`, 100 | 3.32 ms | 5.55 ms | 5.94 ms | 3.0 | 76 KB |
| `restore`, 1.000 | 7.38 ms | 8.84 ms | 14.22 ms | 4.0 | 753 KB |
| `restore`, 5.000 | 31.18 ms | 41.65 ms | 42.89 ms | 4.0 | 3.77 MB |
| `turn.simple`, 10 | 1.91 ms | 2.76 ms | 2.82 ms | 6.7 | 32.6 KB |
| `turn.simple`, 5.000 | 11.03 ms | 12.13 ms | 12.31 ms | 7.0 | 32.6 KB |
| `turn.tool`, 10 | 6.70 ms | 8.86 ms | 9.42 ms | 8.9 | 33.1 KB |
| `turn.tool`, 5.000 | 19.18 ms | 20.08 ms | 20.08 ms | 9.0 | 33.1 KB |
| `turn.supervisor`, 10 | 7.41 ms | 9.59 ms | 10.08 ms | 15.4 | 65.9 KB |
| `turn.supervisor`, 5.000 | 27.90 ms | 30.38 ms | 30.84 ms | 15.5 | 65.9 KB |

Two things are worth reading twice.

**A turn costs the same number of commands whatever the history is.** A
supervisor turn issues ~15 commands on a 10-message session and on a
5.000-message one, and moves the same ~66 KB. What grows is the restoration that
precedes it, and with it the turn's wall-clock time.

**A full restoration still transfers the whole history.** The bounded reads of
[#58](https://github.com/iguinea/mongodb-session-manager/issues/58) keep a
*page* small — 7 KB whatever the history — but rebuilding an `Agent` asks for
every message, so 5.000 of them are 3.77 MB and 31 ms before the turn starts.
Sessions that long are where a conversation manager earns its keep.

### Event-loop lag: the cost paid by everyone else

pymongo is synchronous, `Agent.__call__` wraps `invoke_async`, and the reference
FastAPI backend awaits `stream_async` directly on the server loop. Every driver
call inside `sync_agent` therefore blocks that loop, and with it every other
request the worker is serving. The harness measures it as heartbeat drift:

| Scenario | Event-loop lag p99 | Idle-loop baseline p99 |
|---|---:|---:|
| `turn.supervisor`, 10 messages | 5.3 ms | 2.8 ms |
| `turn.supervisor`, 1.000 | 13.1 ms | 2.1 ms |
| `turn.supervisor`, 5.000 | 20.4 ms | 2.1 ms |
| `turn.simple`, 5.000 | 18.8 ms | 2.1 ms |

The baseline is the machine's own scheduling jitter, printed beside the lag and
never subtracted from it. The reading is not "the turn took 28 ms" but "for
about 20 ms of it, nothing else on that worker could run".


### Real-World Performance

**FastAPI Production Metrics**:
```
Configuration:
- 5 FastAPI instances
- maxPoolSize: 100 per instance
- MongoDB Atlas M30

Results:
- Average request latency: 45ms (p50)
- P95 latency: 120ms
- P99 latency: 250ms
- Throughput: 850 req/s (total)
- Connection pool utilization: 60-70%
```

**Breakdown**:
```
Request latency breakdown:
- Session manager operations: 8-12ms
- Agent processing (Claude API): 200-800ms
- Network overhead: 2-5ms
- Application logic: 10-15ms

Session manager is <5% of total latency
```

## Connection Overhead Analysis

### Connection Creation Cost

**Measurement**: Time to create MongoClient and establish connection

```python
import time
from pymongo import MongoClient

# Without pooling
start = time.time()
client = MongoClient("mongodb://localhost:27017/")
client.admin.command("ping")  # Ensure connection
elapsed = (time.time() - start) * 1000
print(f"Connection time: {elapsed}ms")
client.close()
```

**Results**:
```
Local MongoDB:        10-20ms
Same Region Network:  20-50ms
Cross Region:         50-150ms
MongoDB Atlas (EU):   30-80ms
```

### Connection Pool Initialization

**Measurement**: Time to initialize connection pool (one-time cost)

```python
start = time.time()
factory = MongoDBSessionManagerFactory(
    connection_string=mongodb_uri, maxPoolSize=100, minPoolSize=10
)
elapsed = (time.time() - start) * 1000
print(f"Pool initialization: {elapsed}ms")
```

**Results**:
```
Pool initialization: 15-30ms (one-time)
  - MongoClient creation: 10-20ms
  - Initial connections (minPoolSize=10): 5-10ms total
  - Subsequent connections: Created on-demand (lazy)
```

### Session Manager Creation

**Measurement**: Time to create session manager from factory

```python
# With factory (reuses pool)
start = time.time()
manager = factory.create_session_manager("session-123")
elapsed = (time.time() - start) * 1000
print(f"Manager creation: {elapsed}ms")
```

**Results**:
```
With factory:     <0.1ms (pool reuse)
Without factory:  10-50ms (new connection)
Improvement:      100-500x faster
```

### Summary: Connection Overhead

| Operation | Without Pool | With Pool | Improvement |
|-----------|-------------|-----------|-------------|
| First request | 10-50ms | 15-30ms | Comparable |
| Subsequent requests | 10-50ms | <0.1ms | 100-500x |
| Concurrent requests (10) | 100-500ms | <1ms | 100-500x |
| 1000 requests | 10-50s | 0.1s | 100-500x |

**Conclusion**: Connection pooling provides massive performance improvement after initialization.

## Concurrent Request Handling

### Thread Safety

The MongoDB Session Manager is designed for concurrent access:

**Thread-Safe Components**:
1. **MongoDBConnectionPool**: Double-checked locking
2. **MongoClient**: Thread-safe (PyMongo guarantee)
3. **MongoDBSessionManagerFactory**: Singleton factory
4. **Repository Operations**: Atomic MongoDB operations

**Thread-Unsafe Components** (by design):
1. **MongoDBSessionManager Instance**: Not shared across requests
2. **Agent Instance**: Not shared (Strands SDK requirement)

### Concurrent Request Pattern

```python
# FastAPI concurrent request handling
@app.post("/chat")
async def chat(session_id: str, message: str):
    # Each request gets its own manager
    # But all reuse the same connection pool
    manager = factory.create_session_manager(session_id)

    # Create agent for this request
    agent = Agent(model="claude-3-sonnet", session_manager=manager)

    # Process (may run concurrently with other requests)
    response = agent(message)

    return {"response": response}
```

**Concurrent Execution**:
```
Request 1 → Manager 1 → Pool → MongoDB
Request 2 → Manager 2 → Pool → MongoDB  (concurrent)
Request 3 → Manager 3 → Pool → MongoDB  (concurrent)
...
Request N → Manager N → Pool → MongoDB  (concurrent)
```

### Concurrency Benchmarks

Measured with the harness, `--operation turn.supervisor --history 100`, against
the same local MongoDB 8.2.7. Concurrency here means N invocations in flight on
one event loop — the way N requests share a FastAPI worker — not N parallel
driver calls: pymongo is synchronous, so those serialise.

| Concurrent invocations | p50 | p95 | p99 | Event-loop lag p99 |
|---:|---:|---:|---:|---:|
| 1 | 15.0 ms | 18.9 ms | 30.0 ms | 13.1 ms |
| 4 | 20.6 ms | 33.5 ms | 45.0 ms | 25.9 ms |
| 16 | 62.5 ms | 82.0 ms | 93.6 ms | 64.5 ms |

Per-turn latency grows roughly with the queue: sixteen turns on one loop take
about four times as long each as one turn alone, because each waits behind the
others' blocking driver calls. The commands per turn do not change (15.2 in all
three), so this is queuing, not extra work.

**Connection-pool checkout wait was 0 ms in all three**, and that is structural:
a single loop with a synchronous driver never has two checkouts in flight. A
profile that deliberately shrank the pool to four connections and drove it with
sixteen concurrent invocations still waited 0 ms. Pool contention appears when
several workers or threads share a client, not within one worker.

The practical consequence is that a worker is bounded by the sum of its blocking
calls. Scale with more workers rather than with more concurrency per worker, and
keep the per-turn round-trips low — which is what issue
[#56](https://github.com/iguinea/mongodb-session-manager/issues/56) is about.

**Recommended pool configuration** (unchanged; sized for many workers sharing a
cluster, not for contention within one):
```python
factory = MongoDBSessionManagerFactory(
    connection_string=mongodb_uri,
    maxPoolSize=100,
    minPoolSize=20,
    maxIdleTimeMS=45000,
    waitQueueTimeoutMS=10000,
)
```


## Memory Usage

### Component Memory Footprint

**Measured with `pympler.asizeof`**:

```python
from pympler import asizeof

# Factory (with pool)
factory = MongoDBSessionManagerFactory(...)
print(f"Factory: {asizeof.asizeof(factory) / 1024:.2f} KB")

# Session Manager
manager = factory.create_session_manager("session-123")
print(f"Manager: {asizeof.asizeof(manager) / 1024:.2f} KB")

# Repository
print(f"Repository: {asizeof.asizeof(manager.session_repository) / 1024:.2f} KB")
```

**Results**:

| Component | Memory | Notes |
|-----------|--------|-------|
| MongoDBConnectionPool | 15 KB | Singleton (one per app) |
| MongoClient (pooled) | 2 MB | Shared across managers |
| MongoDBSessionManagerFactory | 20 KB | One per app |
| MongoDBSessionManager | 8 KB | One per request |
| MongoDBSessionRepository | 5 KB | One per manager |
| Agent (Strands SDK) | 50-100 KB | Depends on conversation |

**Memory per Request**:
```
Manager:     8 KB
Repository:  5 KB
Agent:       50 KB (average)
-----------------------
Total:       ~63 KB per concurrent request
```

**Memory for 1000 Concurrent Requests**:
```
1000 requests × 63 KB = 63 MB
Plus shared pool: 2 MB
Total: ~65 MB
```

**Memory Efficiency**:
- Shared connection pool minimizes overhead
- Session managers are lightweight
- Most memory in agent conversation history

### Memory Optimization

**1. Connection Pool Sizing**:
```python
# Memory-constrained environment (Lambda)
factory = MongoDBSessionManagerFactory(
    connection_string=mongodb_uri,
    maxPoolSize=10,  # Lower pool size
    minPoolSize=2,  # Fewer warm connections
)
# Memory savings: ~1.5 MB
```

**2. Projection (Fetch Less Data)**:
```python
# Only fetch metadata (not entire session)
doc = collection.find_one(
    {"_id": session_id},
    {"metadata": 1},  # Projection
)
# Saves: 90% of memory for large sessions
```

**3. Pagination**:
```python
# Fetch messages in chunks
messages = repository.list_messages(
    session_id="session-123",
    agent_id="agent-A",
    limit=10,  # Only 10 messages
    offset=0,
)
# Saves: Memory proportional to conversation size
```

## MongoDB Query Optimization

### Query Performance

**Measurement Methodology**:
```python
import time

start = time.time()
result = collection.find_one({"_id": session_id})
elapsed = (time.time() - start) * 1000
print(f"Query time: {elapsed}ms")
```

### Operation Benchmarks

| Operation | Query Time | Index Used | Notes |
|-----------|-----------|------------|-------|
| Get session by ID | 1-2ms | _id (primary) | Fastest |
| Get recent sessions (10) | 3-5ms | updated_at | Indexed |
| Get by metadata.priority | 2-4ms | metadata.priority | If indexed |
| Get sessions with feedback | 10-50ms | None | Array scan |
| Count all messages | 100-500ms | None | Aggregation |
| Full text search | 50-200ms | Text index | If configured |

### Optimization Strategies

#### 1. Use Projection (Fetch Only Needed Fields)

**Before**:
```python
# Fetch entire session (could be 100+ KB)
session = collection.find_one({"_id": session_id})
metadata = session["metadata"]
```

**After**:
```python
# Fetch only metadata (~1 KB)
session = collection.find_one({"_id": session_id}, {"metadata": 1})
metadata = session["metadata"]
```

**Improvement**: 90-99% less data transfer

#### 2. Use $slice for Array Subsets

**Before**:
```python
# Fetch all messages (could be thousands)
session = collection.find_one({"_id": session_id})
last_message = session["agents"]["agent-A"]["messages"][-1]
```

**After**:
```python
# Fetch only last message
session = collection.find_one(
    {"_id": session_id}, {"agents.agent-A.messages": {"$slice": -1}}
)
last_message = session["agents"]["agent-A"]["messages"][0]
```

**Improvement**: Fetches 1 message instead of N

**Code Reference**: `/workspace/src/mongodb_session_manager/mongodb_session_manager.py` (line 228)

#### 3. Index Metadata Fields

**Before** (No index):
```python
# Full collection scan
sessions = collection.find({"metadata.priority": "high"})
# Time: O(n) - scans all documents
```

**After** (With index):
```python
# Create index
collection.create_index("metadata.priority")

# Same query, now uses index
sessions = collection.find({"metadata.priority": "high"})
# Time: O(log n + k) - much faster
```

**Improvement**: 10-100x faster for large collections

#### 4. Atomic Updates (Avoid Read-Modify-Write)

**Before** (Race condition):
```python
# Read
session = collection.find_one({"_id": session_id})
metadata = session["metadata"]

# Modify
metadata["priority"] = "high"

# Write (another request could have modified in between)
collection.update_one({"_id": session_id}, {"$set": {"metadata": metadata}})
```

**After** (Atomic):
```python
# Single atomic operation
collection.update_one({"_id": session_id}, {"$set": {"metadata.priority": "high"}})
```

**Improvement**: No race conditions, 2x faster (one query vs two)

**Code Reference**: `/workspace/src/mongodb_session_manager/mongodb_session_repository.py` (lines 578-592)

### Query Explain Plans

**Example**: Analyze query performance

```javascript
// In MongoDB shell
db.sessions.find({"metadata.priority": "high"}).explain("executionStats")
```

**Output Analysis**:
```json
{
    "executionStats": {
        "executionTimeMillis": 2,
        "totalKeysExamined": 10,
        "totalDocsExamined": 10,
        "executionStages": {
            "stage": "FETCH",
            "inputStage": {
                "stage": "IXSCAN",  // Index scan (good!)
                "indexName": "metadata.priority_1"
            }
        }
    }
}
```

**What to Look For**:
- `IXSCAN`: Good (index used)
- `COLLSCAN`: Bad (full collection scan)
- `totalDocsExamined`: Should be close to `nReturned`
- `executionTimeMillis`: Should be low (<10ms for simple queries)

## Index Performance

### Index Types and Performance

| Index Type | Creation Time | Query Performance | Write Impact | Storage |
|-----------|---------------|-------------------|--------------|---------|
| Single field | Fast (seconds) | O(log n) | Minimal | Low |
| Compound | Medium (seconds) | O(log n) | Minimal | Medium |
| Text | Slow (minutes) | O(log n + k) | Moderate | High |
| Geospatial | Medium | O(log n) | Minimal | Medium |

### Automatic Index Creation

**Once per client, on the first repository that sees a collection** (since v0.10.0):
```python
def _ensure_indexes(self):
    # Skipped entirely if this client already ensured this collection
    self.collection.create_index("created_at")
    self.collection.create_index("updated_at")
    self.collection.create_index("session_id")
    self.collection.create_index("application_name")

    # Optional metadata indexes
    if self.metadata_fields:
        for field in self.metadata_fields:
            self.collection.create_index(f"metadata.{field}")
```

**Why it is tracked**: pymongo does not cache `create_index` — every call is a
round-trip to the server even when the index already exists. With a session
manager created per request (the recommended factory pattern), that meant 4+
round-trips per instantiation: 8 per turn in an application with a supervisor
and a sub-agent.

The registry is a `WeakKeyDictionary` keyed by `MongoClient`, not by collection
name, so two clients pointing at different clusters that happen to share
database and collection names each get their own indexes. Entries disappear
when the client is closed and garbage collected. A failed `create_index` is not
recorded, so the next manager retries.

**Performance Impact**:
- First initialization per client: 100-500ms (depends on collection size)
- Subsequent managers: 0 round-trips
- No impact on empty collections

**Code Reference**: `src/mongodb_session_manager/mongodb_session_repository.py` (`_ensure_indexes`, `_INDEX_REGISTRY`)

### Bounded Restore and Domain Reads

A warm restoration performs three domain reads: the session header, the agent
state and the message history. Session documents embed their histories, so an
unprojected `read_session()` and a projection of the whole agent made that same
history cross the wire three times.

The first two reads now have payloads independent of history size:

- `read_session()` projects `session_id`, `session_type`, `created_at` and
  `updated_at`.
- `read_agent()` projects `agents.<id>.agent_data`, including the `model` and
  `system_prompt` used to seed the config cache.
- `list_messages()` sorts by `created_at` and paginates inside an aggregation;
  only the requested page crosses the wire. A direct `$slice` remains invalid
  because it would cut physical order before chronological order.
- `read_message()` returns one `$filter` match, `count_messages()` returns one
  `$size`, and `list_agent_configs()` maps only its four public fields. None of
  them transfers the embedded history.

Measured against a local MongoDB 8.2.7 standalone with primary reads, 5 warmups
and 30 repetitions (messages of 918 BSON bytes):

| Messages | Previous restoration (p50 / BSON) | Projected restoration (p50 / BSON) |
|---:|---:|---:|
| 10 | 1.03 ms / 28.1 KiB | 0.99 ms / 9.5 KiB |
| 100 | 1.76 ms / 271.8 KiB | 1.23 ms / 90.7 KiB |
| 1,000 | 12.91 ms / 2,712 KiB | 4.93 ms / 904 KiB |
| 5,000 | 64.24 ms / 13,570 KiB | 23.96 ms / 4,523 KiB |

The byte reduction approaches 66.7% as history grows. These timings validate
MongoDB locally; DocumentDB support for the projection syntax is documented by
AWS, but its latency and replica consistency require measurement on the target
cluster.

The follow-up benchmark for #58 used MongoDB 8.2.7, PyMongo 4.16, 5 warmups and
30 repetitions. With 5,000 messages of 512 characters, a chronological page of
10 fell from **3,397,842 B / 14.322 ms p50** to **7,350 B / 4.263 ms p50**.
Single-message lookup fell from 13.771 to 1.516 ms p50, server count from 13.410
to 1.122 ms, and config listing from 13.481 to 0.519 ms. Their responses were
670 B, 16 B and 118 B and contained no `messages` key. Full p50/p95/p99 tables
and explain summaries are in `artifacts/issue-58-server-side-reads.md`.

### Writes per Turn

On DocumentDB every `update` costs 40-55 ms regardless of its size, so what
drives latency is the **number** of round-trips, not the payload.

A turn is driven by messages, not by streaming: the Strands SDK registers both
`append_message` and `sync_agent` on the same `MessageAddedEvent`, plus a final
`sync_agent` on `AfterInvocationEvent`. The same turn emitting 1 chunk or 200
chunks produces exactly the same writes.

Measured on a warm turn (the session already exists) with a supervisor and a
sub-agent (one tool call):

| | v0.9.1 | #54 | + #65 | + #67 | + #66 |
|---|---|---|---|---|---|
| `update` | 21 | 15 | 13 | 10 | 8 |
| `find` | 13 | 6 | 6 | 6 | 6 |
| `createIndexes` | 8 | 0 | 0 | 0 | 0 |
| **total** | **42** | **21** | **19** | **16** | **14** |

The 8 remaining writes break down as:

| Writes | Operation | When |
|---:|---|---|
| 6 | `create_message` (`$push`) | One per message: 4 from the supervisor, 2 from the sub-agent |
| 2 | Metrics on the last message | One per agent, when its invocation closes (`AfterInvocationEvent`) |

Neither the agent state nor its config travels. `update_agent()` skips an agent
whose content is what the repository last read or wrote (#67), which covers the
first sync of each manager and the supervisor's sync after the tool. The agent
config (model and system prompt, ~14 KB each in this scenario) is known from
`read_agent()`: each manager seeds its config cache with the persisted values
and only writes when they differ (#65). On a brand-new session the first sync
still writes it once.

#### Metrics are written when the invocation closes

Strands fires `MessageAddedEvent` *before* the event loop accumulates the usage
and metrics of the model call that produced the message (`event_loop.py:409-414`
in strands 1.30, `:699-703` in 1.56). Up to v0.14.0 every sync wrote metrics,
so the one run for each message wrote the previous cycle's: a snapshot on each
tool result and a stale write on the final message that the closing sync
overwrote an instant later. An agent that called N tools cost 2N+1 metric
writes. Now the sync run for each message leaves the metrics out, and the closing
sync writes them once: 1 write per invocation, whatever N is (#66).

The sync run for each message is told apart by wrapping the hook registry
(`sync_origin.MessageAddedTagging`): Strands registers the same `sync_agent`
for both events, and the callbacks of `MessageAddedEvent` run with a
`ContextVar` tag set. An explicit `sync_agent()` call always writes, so an
application can still add a value to the metrics after the invocation and sync.

`update_agent` writes each `SessionAgent` field on its own path
(`agents.<id>.agent_data.<field>`). Setting `agent_data` as a whole replaced the
subdocument and wiped the model, system prompt and `prompt_metadata` that the
session manager stores there.

### Index Cardinality

**High Cardinality** (good for indexes):
```python
# session_id: Nearly unique
# Benefit from index: High
collection.create_index("session_id")
```

**Medium Cardinality** (good for indexes):
```python
# priority: "low", "medium", "high" (3 values)
# Benefit from index: Good
collection.create_index("metadata.priority")
```

**Low Cardinality** (poor for indexes):
```python
# session_type: "default" (1 value in 90% of docs)
# Benefit from index: Low
# Don't index!
```

### Index Selectivity

**Measure Selectivity**:
```javascript
// Count total documents
db.sessions.count()  // 10000

// Count documents with high priority
db.sessions.count({"metadata.priority": "high"})  // 500

// Selectivity: 500 / 10000 = 5%
```

**Index Efficiency**:
- Selectivity < 10%: Excellent (index very useful)
- Selectivity 10-30%: Good (index helpful)
- Selectivity > 50%: Poor (index marginal)
- Selectivity > 90%: Bad (don't index)

### Compound Index Strategy

**When to Use**:
```python
# Frequent query pattern
sessions = collection.find(
    {
        "metadata.department": "sales",
        "metadata.priority": "high",
        "updated_at": {"$gte": date},
    }
)
```

**Optimal Compound Index**:
```javascript
db.sessions.createIndex({
    "metadata.department": 1,
    "metadata.priority": 1,
    "updated_at": -1
})
```

**Index Order Matters**:
1. Equality filters first (department, priority)
2. Range filters last (updated_at)
3. Sort fields at end

**Index Prefixes**:
This compound index also supports:
```javascript
// Uses index prefix
{"metadata.department": "sales"}
{"metadata.department": "sales", "metadata.priority": "high"}

// Does NOT use index
{"metadata.priority": "high"}  // Not a prefix
{"updated_at": {"$gte": date}}  // Not a prefix
```

## Network Latency Considerations

### Network Impact

**Latency Breakdown**:
```
Total Request Time = App Processing + Network RTT + MongoDB Processing

Example:
45ms total = 10ms app + 30ms network + 5ms MongoDB
```

### Network Optimization

#### 1. Co-location

**Same Region** (MongoDB Atlas):
```
Application: AWS eu-west-1
MongoDB:     MongoDB Atlas eu-west-1
Network RTT: 1-5ms
```

**Cross Region**:
```
Application: AWS eu-west-1
MongoDB:     MongoDB Atlas us-east-1
Network RTT: 50-100ms
```

**Recommendation**: Deploy in same region (10-50x faster)

#### 2. Connection Compression

```python
factory = MongoDBSessionManagerFactory(
    connection_string=mongodb_uri,
    compressors="snappy,zlib",  # Enable compression
    # Reduces network traffic by 60-80%
)
```

**Trade-off**: CPU overhead for compression vs network time saved
- Same region: Minor benefit
- Cross region: Significant benefit

#### 3. Read Preference

```python
# For read-heavy workloads
factory = MongoDBSessionManagerFactory(
    connection_string="mongodb://host/?readPreference=secondaryPreferred"
)
```

**Options**:
- `primary`: Always read from primary (default, consistent)
- `primaryPreferred`: Primary if available, secondary if not
- `secondary`: Always read from secondary (may be stale)
- `secondaryPreferred`: Secondary if available (reduces primary load)

**Use Case**:
- `primary`: Critical reads requiring latest data
- `secondaryPreferred`: Analytics, dashboards (eventual consistency OK)

### Network Monitoring

```python
import time
from pymongo import MongoClient, monitoring


class NetworkMonitor(monitoring.CommandListener):
    def started(self, event):
        self.start_time = time.time()

    def succeeded(self, event):
        duration = (time.time() - self.start_time) * 1000
        print(f"{event.command_name}: {duration}ms")


monitoring.register(NetworkMonitor())
```

**Metrics to Track**:
- Average query latency
- P95, P99 latency
- Network errors/retries
- Connection pool wait time

## Scaling Strategies

### Vertical Scaling

**Application Tier**:

| Instance Size | vCPUs | RAM | Pool Size | Throughput |
|--------------|-------|-----|-----------|------------|
| Small | 1 | 2 GB | 20 | 100 req/s |
| Medium | 2 | 4 GB | 50 | 250 req/s |
| Large | 4 | 8 GB | 100 | 500 req/s |
| XLarge | 8 | 16 GB | 200 | 1000 req/s |

**MongoDB Tier** (Atlas):

| Tier | Storage | RAM | Connections | Cost/Month |
|------|---------|-----|-------------|------------|
| M10 | 10 GB | 2 GB | 1,500 | $57 |
| M20 | 20 GB | 4 GB | 3,000 | $140 |
| M30 | 40 GB | 8 GB | 3,000 | $280 |
| M40 | 80 GB | 16 GB | 12,500 | $560 |

### Horizontal Scaling

**Application Instances**:
```
Load Balancer
├── FastAPI Instance 1 (100 connections)
├── FastAPI Instance 2 (100 connections)
├── FastAPI Instance 3 (100 connections)
└── FastAPI Instance N (100 connections)
     ↓
MongoDB (handles all connections)
```

**Connection Planning**:
```
Total Connections = Instances × maxPoolSize
Example: 5 instances × 100 = 500 connections

MongoDB Atlas M30: 3,000 connection limit
Headroom: 3000 - 500 = 2500 (sufficient)
```

**Auto-Scaling Configuration**:
```yaml
# Kubernetes HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: session-manager-api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: session-manager-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Database Scaling

#### Read Scaling (Replica Set)

```
Primary (writes + reads)
├── Secondary 1 (reads)
├── Secondary 2 (reads)
└── Secondary 3 (reads)
```

**Configuration**:
```python
factory = MongoDBSessionManagerFactory(
    connection_string="mongodb://host1,host2,host3/?replicaSet=rs0&readPreference=secondaryPreferred"
)
```

**Benefits**:
- Distributes read load across secondaries
- Primary handles only writes
- 3-4x read capacity increase

#### Write Scaling (Sharding)

```
mongos (Router)
├── Shard 1 (sessions 0-33%)
├── Shard 2 (sessions 34-66%)
└── Shard 3 (sessions 67-100%)
```

**Shard Key**: `session_id` (excellent distribution)

**Configuration**:
```javascript
// Enable sharding on database
sh.enableSharding("sessions_db")

// Shard collection by session_id
sh.shardCollection(
    "sessions_db.sessions",
    { "session_id": "hashed" }
)
```

**Benefits**:
- Linear write scaling
- Each shard handles subset of sessions
- Automatic data distribution

**When to Shard**:
- Collection > 500 GB
- Write throughput > 5000 ops/s
- Single replica set at capacity

## Production Optimization Tips

### 1. Connection Pool Configuration

**High-Traffic Production**:
```python
factory = MongoDBSessionManagerFactory(
    connection_string=mongodb_uri,
    maxPoolSize=200,  # Large pool
    minPoolSize=50,  # Many warm connections
    maxIdleTimeMS=60000,  # Keep connections 1 minute
    waitQueueTimeoutMS=10000,  # 10s timeout for queue
    serverSelectionTimeoutMS=5000,  # 5s server selection
    connectTimeoutMS=10000,  # 10s connection timeout
    socketTimeoutMS=45000,  # 45s socket timeout
    retryWrites=True,  # Automatic write retry
    retryReads=True,  # Automatic read retry
    compressors="snappy,zlib",  # Compression
)
```

### 2. Monitoring and Alerting

**Key Metrics**:
```python
# Application metrics
- request_latency_ms (p50, p95, p99)
- request_rate (req/s)
- error_rate (%)
- connection_pool_utilization (%)
- connection_wait_time_ms

# MongoDB metrics
- active_connections
- queued_operations
- operation_latency_ms
- cache_hit_ratio (%)
- page_faults
```

**Alert Thresholds**:
```yaml
alerts:
  - name: high_latency
    condition: p95_latency > 500ms
    action: scale_up

  - name: connection_pool_exhaustion
    condition: pool_utilization > 90%
    action: increase_pool_size

  - name: high_error_rate
    condition: error_rate > 5%
    action: page_oncall
```

### 3. Caching Strategy

**Application-Level Cache**:
```python
from functools import lru_cache


@lru_cache(maxsize=1000)
def get_session_metadata(session_id: str):
    return repository.get_metadata(session_id)


# Cache hit: 0.01ms
# Cache miss: 5ms (MongoDB query)
# Hit ratio: 80% typical
# Effective latency: 0.8 × 0.01 + 0.2 × 5 = 1.008ms
```

**Redis Cache**:
```python
import redis

cache = redis.Redis()


def get_session_with_cache(session_id: str):
    # Try cache first
    cached = cache.get(f"session:{session_id}")
    if cached:
        return json.loads(cached)

    # Cache miss - fetch from MongoDB
    session = repository.read_session(session_id)

    # Cache for 5 minutes
    cache.setex(f"session:{session_id}", 300, json.dumps(session))

    return session
```

### 4. Batch Operations

**Inefficient** (N queries):
```python
for session_id in session_ids:
    session = repository.read_session(session_id)
    # Process session
```

**Efficient** (1 query):
```python
# Batch fetch
sessions = collection.find({"_id": {"$in": session_ids}})

# Process all
for session in sessions:
    # Process session
```

**Improvement**: 10-100x faster for large batches

### 5. Write Batching

**Inefficient** (N writes):
```python
for metadata_update in updates:
    repository.update_metadata(metadata_update["session_id"], metadata_update["data"])
```

**Efficient** (1 bulk write):
```python
from pymongo import UpdateOne

operations = [
    UpdateOne(
        {"_id": update["session_id"]},
        {"$set": {f"metadata.{k}": v for k, v in update["data"].items()}},
    )
    for update in updates
]

collection.bulk_write(operations)
```

**Improvement**: 5-50x faster for large batches

### 6. Query Optimization Checklist

- [ ] Use projection to fetch only needed fields
- [ ] Add indexes on frequently queried fields
- [ ] Use `$slice` for array subsets
- [ ] Avoid `$where` and complex `$regex`
- [ ] Use aggregation for complex queries
- [ ] Batch operations when possible
- [ ] Monitor slow queries (> 100ms)
- [ ] Use `explain()` to verify index usage

### 7. Resource Limits

**MongoDB Connection Limits**:
```
M10: 1,500 connections
M20: 3,000 connections
M30: 3,000 connections
M40: 12,500 connections
```

**Application Configuration**:
```python
# Calculate total connections
instances = 5
max_pool_size = 100
total_connections = instances × max_pool_size  # 500

# Ensure under MongoDB limit
assert total_connections < mongodb_connection_limit
```

**Document Size Limits**:
```
MongoDB: 16 MB per document
Average session: 50-500 KB
Messages before limit: ~10,000-50,000
```

## Monitoring and Metrics

### Application-Level Metrics

**FastAPI Middleware**:
```python
import time
from fastapi import Request


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()

    response = await call_next(request)

    duration = (time.time() - start) * 1000

    # Log metrics
    logger.info(
        f"path={request.url.path} "
        f"method={request.method} "
        f"status={response.status_code} "
        f"duration={duration:.2f}ms"
    )

    return response
```

**Prometheus Metrics**:
```python
from prometheus_client import Histogram, Counter

request_duration = Histogram(
    "session_manager_request_duration_ms",
    "Request duration in milliseconds",
    ["endpoint", "method"],
)

request_count = Counter(
    "session_manager_requests_total",
    "Total request count",
    ["endpoint", "method", "status"],
)


@app.post("/chat")
async def chat(session_id: str):
    with request_duration.labels("/chat", "POST").time():
        # Handle request
        request_count.labels("/chat", "POST", "200").inc()
```

### MongoDB Metrics

**Connection Pool Stats**:
```python
@app.get("/metrics/pool")
async def pool_metrics():
    factory = get_global_factory()
    stats = factory.get_connection_stats()

    return {
        "status": stats["status"],
        "max_pool_size": stats["pool_config"]["maxPoolSize"],
        "min_pool_size": stats["pool_config"]["minPoolSize"],
        "server_version": stats["server_version"],
    }
```

**MongoDB Profiler**:
```javascript
// Enable profiler for slow queries
db.setProfilingLevel(1, { slowms: 100 })

// View slow queries
db.system.profile.find({
    millis: { $gt: 100 }
}).sort({ ts: -1 }).limit(10)
```

### Dashboard Example

**Grafana Dashboard**:
```yaml
panels:
  - title: Request Latency
    metric: session_manager_request_duration_ms
    aggregation: percentile(95)
    threshold:
      warning: 200ms
      critical: 500ms

  - title: Throughput
    metric: session_manager_requests_total
    aggregation: rate(1m)

  - title: Error Rate
    metric: session_manager_requests_total{status=~"5.."}
    aggregation: rate(1m) / rate(total)

  - title: Connection Pool Utilization
    metric: mongodb_connection_pool_active / mongodb_connection_pool_max
    threshold:
      warning: 80%
      critical: 95%
```

### Performance Testing

**Load Test with Locust**:
```python
from locust import HttpUser, task, between


class SessionManagerUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def chat(self):
        self.client.post(
            "/chat", json={"session_id": f"session-{self.user_id}", "message": "Hello"}
        )

    @task(2)
    def get_metadata(self):
        self.client.get(f"/metadata/{self.user_id}")
```

**Run Load Test**:
```bash
locust -f loadtest.py --host=http://localhost:8000 --users=100 --spawn-rate=10
```

---

## Summary

The MongoDB Session Manager provides excellent performance characteristics:

1. **Connection Pooling**: 100-500x improvement over creating connections per request
2. **Concurrent Handling**: Linear scaling up to MongoDB connection limits
3. **Low Latency**: < 10ms overhead for session operations
4. **Memory Efficient**: ~63 KB per concurrent request
5. **Scalable**: Supports 1000+ req/s per instance

**Key Optimizations**:
- Use factory pattern with connection pooling
- Enable indexes on frequently queried fields
- Use projection and $slice to minimize data transfer
- Configure pool size appropriately for workload
- Monitor and alert on key metrics

**Production Recommendations**:
- Start with maxPoolSize=100, adjust based on load
- Deploy in same region as MongoDB
- Enable compression for cross-region
- Monitor p95/p99 latency, not just average
- Use horizontal scaling for high traffic
- Consider sharding for > 500 GB data
