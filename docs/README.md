# MongoDB Session Manager - Documentation

Complete documentation for the MongoDB Session Manager library for Strands Agents.

## Table of Contents

### Getting Started
Start here if you're new to MongoDB Session Manager.

- [Installation](getting-started/installation.md) - How to install and set up the library
- [Quickstart Guide](getting-started/quickstart.md) - Get up and running in 5 minutes
- [Basic Concepts](getting-started/basic-concepts.md) - Core concepts and terminology

### User Guide
Comprehensive guides for using all features of the library.

- [Session Management](user-guide/session-management.md) - Managing agent conversations and state
- [Connection Pooling](user-guide/connection-pooling.md) - Efficient MongoDB connection management
- [Factory Pattern](user-guide/factory-pattern.md) - Optimized session manager creation for stateless environments
- [Metadata Management](user-guide/metadata-management.md) - Working with session metadata
- [Feedback System](user-guide/feedback-system.md) - Collecting and managing user feedback
- [AWS Integrations](user-guide/aws-integrations.md) - SNS and SQS hooks for real-time notifications
- [Async Streaming](user-guide/async-streaming.md) - Real-time streaming responses

### API Reference
Detailed API documentation for all classes, methods, and functions.

- [MongoDBSessionManager](api-reference/mongodb-session-manager.md) - Main session management class
- [MongoDBSessionRepository](api-reference/mongodb-session-repository.md) - Low-level MongoDB operations
- [MongoDBConnectionPool](api-reference/mongodb-connection-pool.md) - Singleton connection pool
- [MongoDBSessionManagerFactory](api-reference/mongodb-session-factory.md) - Factory for session managers
- [Hooks Reference](api-reference/hooks.md) - Metadata and feedback hooks, AWS integrations

### Architecture
Understanding the design and implementation.

- [Architecture Overview](architecture/overview.md) - High-level system architecture
- [Design Decisions](architecture/design-decisions.md) - Why things work the way they do
- [Data Model](architecture/data-model.md) - MongoDB document structure and schema
- [Performance](architecture/performance.md) - Performance characteristics and optimization

### Examples
Practical examples and use cases.

- [Basic Usage](examples/basic-usage.md) - Simple examples to get started
- [FastAPI Integration](examples/fastapi-integration.md) - Production FastAPI setup with connection pooling
- [Metadata Patterns](examples/metadata-patterns.md) - Advanced metadata management patterns
- [Feedback Patterns](examples/feedback-patterns.md) - Feedback collection and processing
- [AWS Integration Patterns](examples/aws-patterns.md) - Using SNS and SQS hooks

### Development
Contributing to the project.

- [Development Setup](development/setup.md) - Setting up your development environment
- [Contributing Guide](development/contributing.md) - How to contribute to the project
- [Testing](development/testing.md) - Running and writing tests
- [Release Process](development/releasing.md) - How releases are created

### Additional Resources

- [FAQ](faq.md) - Frequently asked questions
- [Changelog](../CHANGELOG.md) - Version history and changes
- [GitHub Repository](https://github.com/iguinea/mongodb-session-manager)

## Quick Links

### Popular Topics
- [Getting Started with FastAPI](examples/fastapi-integration.md)
- [Optimizing for Production](architecture/performance.md)
- [Session Persistence](user-guide/session-management.md#session-persistence)
- [Metadata Hooks](api-reference/hooks.md#metadata-hooks)
- [AWS SNS Notifications](user-guide/aws-integrations.md#sns-feedback-notifications)

### Common Tasks
- [Create a session manager](getting-started/quickstart.md#creating-a-session-manager)
- [Initialize global factory](user-guide/factory-pattern.md#global-factory-initialization)
- [Add metadata to sessions](user-guide/metadata-management.md#updating-metadata)
- [Collect user feedback](user-guide/feedback-system.md#adding-feedback)
- [Stream responses](user-guide/async-streaming.md#streaming-responses)

### Executable Examples

Run these scripts to see features in action:

| Script | Description | Documentation |
|--------|-------------|---------------|
| [example_calculator_tool.py](../examples/example_calculator_tool.py) | Basic agent with Strands calculator tool | [Guide](examples/basic-usage.md) |
| [example_agent_config.py](../examples/example_agent_config.py) | Agent configuration persistence | [Guide](examples/basic-usage.md) |
| [example_fastapi.py](../examples/example_fastapi.py) | FastAPI with connection pooling | [Guide](examples/fastapi-integration.md) |
| [example_fastapi_streaming.py](../examples/example_fastapi_streaming.py) | FastAPI with streaming responses | [Guide](examples/fastapi-integration.md) |
| [example_metadata_tool.py](../examples/example_metadata_tool.py) | Agent managing metadata autonomously | [Guide](examples/metadata-patterns.md) |
| [example_metadata_hook.py](../examples/example_metadata_hook.py) | Metadata hooks (audit, validation, caching) | [Guide](examples/metadata-patterns.md) |
| [example_feedback_hook.py](../examples/example_feedback_hook.py) | Feedback hooks (audit, validation, notifications) | [Guide](examples/feedback-patterns.md) |

**Run any example:**
```bash
uv run python examples/example_name.py
```

📁 **[View all examples →](../examples/)**

## Version

This documentation is for **MongoDB Session Manager v0.5.0**.

Last updated: 2026-02-07

## Support

- **Issues**: [GitHub Issues](https://github.com/iguinea/mongodb-session-manager/issues)
- **Email**: iguinea@gmail.com

## License

This project is licensed under the same terms as the parent Itzulbira project.
