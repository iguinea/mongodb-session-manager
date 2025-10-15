# Runnable Examples

Complete, executable scripts demonstrating MongoDB Session Manager features. These examples are designed to run immediately with minimal setup.

## 🚀 Quick Start

### Prerequisites

1. **UV installed** - [Install UV](https://github.com/astral-sh/uv)
2. **MongoDB running** - Local, Docker, or Atlas
3. **Dependencies installed**:
   ```bash
   uv sync
   ```

### Running Examples

```bash
# From the project root
uv run python examples/example_name.py
```

## 📋 Available Examples

### Basic Usage

| Script | Description | Documentation |
|--------|-------------|---------------|
| [example_calculator_tool.py](example_calculator_tool.py) | Basic agent with Strands calculator tool and session persistence | [📚 Guide](../docs/examples/basic-usage.md) |
| [example_agent_config.py](example_agent_config.py) | Agent configuration persistence (model and system_prompt) **NEW v0.1.14** | [📚 Guide](../docs/examples/basic-usage.md) |

**Features demonstrated:**
- Creating session managers
- Agent initialization with tools
- Automatic metrics capture
- Session persistence
- Agent configuration retrieval and updates

### FastAPI Integration

| Script | Description | Documentation |
|--------|-------------|---------------|
| [example_fastapi.py](example_fastapi.py) | FastAPI with connection pooling and factory pattern | [📚 Guide](../docs/examples/fastapi-integration.md) |
| [example_fastapi_streaming.py](example_fastapi_streaming.py) | FastAPI with streaming responses and real-time metrics | [📚 Guide](../docs/examples/fastapi-integration.md) |

**Features demonstrated:**
- Global factory initialization
- Connection pool management
- Per-request session managers
- Streaming endpoints
- Health checks and metrics
- CORS configuration

### Metadata Management

| Script | Description | Documentation |
|--------|-------------|---------------|
| [example_metadata_tool.py](example_metadata_tool.py) | Agent autonomously managing session metadata | [📚 Guide](../docs/examples/metadata-patterns.md) |
| [example_metadata_tool_direct.py](example_metadata_tool_direct.py) | Direct usage of the metadata tool | [📚 Guide](../docs/examples/metadata-patterns.md) |
| [example_metadata_hook.py](example_metadata_hook.py) | Metadata hooks (audit, validation, caching, combined) | [📚 Guide](../docs/examples/metadata-patterns.md) |
| [example_metadata_update.py](example_metadata_update.py) | Metadata update with field preservation | [📚 Guide](../docs/examples/metadata-patterns.md) |
| [example_metadata_production.py](example_metadata_production.py) | Production customer support scenario | [📚 Guide](../docs/examples/metadata-patterns.md) |

**Features demonstrated:**
- Partial metadata updates
- Metadata field deletion
- Metadata tool for agents
- Metadata hooks (audit, validation, caching)
- Production metadata patterns

### Feedback System

| Script | Description | Documentation |
|--------|-------------|---------------|
| [example_feedback_hook.py](example_feedback_hook.py) | Feedback hooks (audit, validation, notifications, analytics) | [📚 Guide](../docs/examples/feedback-patterns.md) |

**Features demonstrated:**
- Adding feedback with ratings and comments
- Feedback hooks for audit and validation
- Notification hooks for real-time alerts
- Analytics hooks for metrics collection
- Combined hooks for multiple behaviors

### Performance & Async

| Script | Description | Documentation |
|--------|-------------|---------------|
| [example_performance.py](example_performance.py) | Performance benchmarks comparing pooling vs no pooling | [📚 Guide](../docs/architecture/performance.md) |
| [example_stream_async.py](example_stream_async.py) | Async streaming responses with real-time metrics | [📚 Guide](../docs/user-guide/async-streaming.md) |

**Features demonstrated:**
- Connection pooling performance benefits
- Factory pattern optimization
- Async streaming with session persistence
- Real-time token streaming
- Metrics capture during streaming

## 🎯 Example Categories

### By Feature

- **Session Management**: `example_calculator_tool.py`, `example_agent_config.py`
- **Connection Pooling**: `example_fastapi.py`, `example_performance.py`
- **Factory Pattern**: `example_fastapi.py`, `example_fastapi_streaming.py`
- **Metadata**: `example_metadata_*.py` (5 examples)
- **Feedback**: `example_feedback_hook.py`
- **Streaming**: `example_stream_async.py`, `example_fastapi_streaming.py`
- **Agent Config**: `example_agent_config.py` ⭐ NEW

### By Use Case

- **Learning**: Start with `example_calculator_tool.py`
- **Production FastAPI**: Use `example_fastapi_streaming.py`
- **Metadata Management**: See `example_metadata_production.py`
- **Performance Optimization**: Check `example_performance.py`
- **Feedback Collection**: Explore `example_feedback_hook.py`
- **Agent Configuration**: Try `example_agent_config.py` ⭐ NEW

## 📚 Documentation Links

Each example includes references to relevant documentation:

- **[Getting Started](../docs/getting-started/)** - Installation and quickstart
- **[User Guides](../docs/user-guide/)** - Comprehensive feature guides
- **[API Reference](../docs/api-reference/)** - Complete API documentation
- **[Examples Guide](../docs/examples/)** - Detailed examples and patterns
- **[Architecture](../docs/architecture/)** - Design and performance

## 🔧 Setup & Configuration

### MongoDB Connection

All examples use MongoDB connection strings. Update them as needed:

```python
# Default (Docker)
connection_string="mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/"

# Local MongoDB
connection_string="mongodb://localhost:27017/"

# MongoDB Atlas
connection_string="mongodb+srv://user:pass@cluster.mongodb.net/mydb"
```

### Environment Variables

For production use, consider using environment variables:

```bash
# .env file
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DATABASE=my_database
MONGODB_COLLECTION=my_sessions
```

Load in your code:

```python
import os
from dotenv import load_dotenv

load_dotenv()

session_manager = create_mongodb_session_manager(
    session_id="my-session",
    connection_string=os.getenv("MONGODB_URI"),
    database_name=os.getenv("MONGODB_DATABASE"),
    collection_name=os.getenv("MONGODB_COLLECTION")
)
```

## 🧪 Running Multiple Examples

You can run multiple examples in sequence to see different features:

```bash
# Learn basic features
uv run python examples/example_calculator_tool.py

# Explore agent configuration
uv run python examples/example_agent_config.py

# See metadata management
uv run python examples/example_metadata_tool.py

# Test feedback system
uv run python examples/example_feedback_hook.py

# Benchmark performance
uv run python examples/example_performance.py
```

## 🐛 Troubleshooting

### MongoDB Connection Issues

If you get connection errors:

1. **Check MongoDB is running**:
   ```bash
   # Docker
   docker ps | grep mongodb

   # Local
   systemctl status mongod  # Linux
   brew services list        # macOS
   ```

2. **Verify connection string**:
   - Correct username/password
   - Correct host and port
   - Database permissions

3. **Check firewall/network**:
   - MongoDB port (27017) is accessible
   - No firewall blocking connections

### Import Errors

If you get `ModuleNotFoundError`:

```bash
# Install dependencies
uv sync

# Or with pip
pip install -e .
```

### UV Not Found

If `uv` command is not found:

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with pip
pip install uv
```

## 💡 Tips

1. **Start Simple**: Begin with `example_calculator_tool.py` to understand basics
2. **Read Inline Comments**: Each example has detailed comments explaining the code
3. **Check Documentation**: Use the documentation links in each script
4. **Modify and Experiment**: Copy examples and modify them for your use case
5. **Production Patterns**: See `example_fastapi_streaming.py` for production setup

## 🤝 Contributing

Found an issue or want to add an example?

1. [Open an issue](https://github.com/iguinea/mongodb-session-manager/issues)
2. [Submit a PR](https://github.com/iguinea/mongodb-session-manager/pulls)
3. [Read the contributing guide](../docs/development/contributing.md)

## 📄 License

These examples are part of the MongoDB Session Manager project and are licensed under the same terms as the parent Itzulbira project.

---

**Happy Coding!** 🚀

For more information, visit the [complete documentation](../docs/).
