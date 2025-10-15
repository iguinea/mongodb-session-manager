# Changelog

All notable changes to the MongoDB Session Manager project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.15] - 2025-10-15

### Changed
- **Dependency Upgrades**: Updated Strands packages to latest versions for improved stability and features
  - `strands-agents`: 1.0.1 → **1.12.0** (11 minor versions)
  - `strands-agents-tools`: 0.2.1 → **0.2.11** (10 patch versions)

### Fixed
- **SessionMessage Compatibility**: Fixed compatibility with strands-agents 1.12.0+ `SessionMessage` constructor
  - Added filtering for metrics fields (`latency_ms`, `input_tokens`, `output_tokens`) that are no longer accepted as constructor parameters
  - These fields are still stored in MongoDB for analytics but filtered when converting to SessionMessage objects
  - Fixes "SessionMessage.__init__() got an unexpected keyword argument" errors when loading existing sessions
  - Updated both `read_message()` and `list_messages()` methods in `MongoDBSessionRepository`

### Added
- **Documentation Overhaul**: Comprehensive documentation structure with 30+ new files
  - Getting Started guides (installation, quickstart, basic concepts)
  - User guides (session management, connection pooling, factory pattern, metadata, feedback, AWS integrations, async streaming)
  - API reference documentation for all classes and hooks
  - Architecture documentation (overview, design decisions, data model, performance)
  - Development guides (setup, contributing, testing, releasing)
  - Examples and patterns (basic usage, FastAPI integration, metadata patterns, feedback patterns, AWS patterns)
  - FAQ and documentation index at `docs/README.md`
- New `examples/README.md` with quick reference to all example scripts

### Benefits from Strands Upgrades
- **Performance**: Better error handling and improved tool loading mechanisms
- **Features**: New model providers (Gemini), enhanced tool specifications with optional output schemas
- **Observability**: Modern OpenTelemetry v1.37 semantic conventions for better monitoring
- **Stability**: 12 versions worth of bug fixes and improvements across strands-agents
- **Tools**: Access to 10+ new tools (Elasticsearch, Twelve Labs Video, Exa/Tavily search, Bright Data)
- **Compatibility**: Better LiteLLM and model provider support (OpenAI, Bedrock, Anthropic)

### Testing
- ✅ Verified compatibility with `example_calculator_tool.py` (basic agent + tools)
- ✅ Verified compatibility with `example_agent_config.py` (agent configuration persistence)
- ✅ Verified compatibility with `example_metadata_hook.py` (metadata hooks functionality)

## [0.1.14] - 2025-10-15

### Added
- **Agent Configuration Persistence**: Automatic capture and storage of `model` and `system_prompt` fields from agents
  - `sync_agent()` now automatically captures and persists agent configuration (model, system_prompt) to MongoDB
  - New `get_agent_config(agent_id)` method to retrieve agent configuration by ID
  - New `update_agent_config(agent_id, model, system_prompt)` method to modify agent configuration
  - New `list_agents()` method to list all agents in a session with their configurations
  - Agent configuration stored in `agents.{agent_id}.agent_data.model` and `.system_prompt` fields
  - Backward compatible: existing documents without these fields continue to work
- New example file: `examples/example_agent_config.py` demonstrating configuration persistence
- Feature plan documentation in `features/1_agent_config_persistence/`

### Changed
- MongoDB schema extended with `model` and `system_prompt` fields in agent_data
- `sync_agent()` now performs additional update to persist agent configuration

### Benefits
- **Auditing**: Track which model and system prompt were used for each conversation
- **Reproducibility**: Recreate agent behavior by using the same configuration
- **Analytics**: Analyze model usage patterns, costs, and performance
- **Compliance**: Maintain records of system prompts for regulatory purposes

### Technical Details
- Model and system_prompt are captured from the `Agent` object during `sync_agent()`
- Fields are stored using MongoDB `$set` operation with dot notation
- Configuration updates are logged at DEBUG level for observability
- Methods handle missing agents gracefully (return None or empty list)

## [0.1.13] - 2025-01-19

### Changed - BREAKING CHANGE ⚠️
- **FeedbackSNSHook**: Redesigned to support separate SNS topics for different feedback types
  - `create_feedback_sns_hook()` now requires three topic ARNs instead of one:
    - `topic_arn_good`: For positive feedback (rating="up")
    - `topic_arn_bad`: For negative feedback (rating="down")
    - `topic_arn_neutral`: For neutral feedback (rating=None)
  - Messages are automatically routed to the appropriate topic based on rating
  - Message format changed to include session context: `"Session: {session_id}\n\n{comment}"`
  - Removed unused imports (json, datetime) from feedback_sns_hook.py

### Added
- **Optional Topic ARNs**: Topics can be set to `"none"` to disable notifications for specific feedback types
  - Example: `topic_arn_neutral="none"` will skip SNS notifications for neutral feedback
  - Logs informational message when skipping due to "none" value
  - Useful for selectively enabling only good/bad feedback notifications

### Migration Guide
**Before (v0.1.12 and earlier):**
```python
feedback_hook = create_feedback_sns_hook(
    topic_arn="arn:aws:sns:eu-west-1:123456789:feedback-alerts"
)
```

**After (v0.1.13+):**
```python
feedback_hook = create_feedback_sns_hook(
    topic_arn_good="arn:aws:sns:eu-west-1:123456789:feedback-good",
    topic_arn_bad="arn:aws:sns:eu-west-1:123456789:feedback-bad",
    topic_arn_neutral="arn:aws:sns:eu-west-1:123456789:feedback-neutral"
)
```

### Updated
- Documentation updated across all files to reflect new three-topic pattern
- README.md: Updated SNS feedback section with new usage examples
- CLAUDE.md: Updated AWS integration patterns with three-topic routing
- feedback_sns_hook.py: Comprehensive docstring updates with new message format

## [0.1.12] - 2025-01-19

### Changed
- **MetadataSQSHook**: Standardized SQS message format for better event handling
  - Added `event_type: "metadata_update"` field to message body for consistent event categorization
  - Updated message attributes to use `event_type` instead of `operation` for better downstream filtering
  - This change improves event processing consistency and aligns with event-driven architecture best practices

## [0.1.11] - 2025-01-19

### Changed
- **MongoDB Connection Pool**: Disabled automatic retry for write operations by setting `retryWrites` to `False`
  - This change improves error handling predictability and prevents potential data inconsistencies
  - Read operations still maintain automatic retries with `retryReads: True`

## [0.1.10] - 2025-01-19

### Fixed
- Fixed import issues in `__init__.py` and `metadata_sqs_hook.py`
- Removed unused import to clean up the codebase
- Enhanced CHANGELOG to reflect import fixes and AWS integration hook additions

## [0.1.9] - 2024-01-27

### Added
- **AWS Integration Hooks**: Optional AWS service integrations for real-time notifications and event propagation
  - `FeedbackSNSHook`: Send feedback notifications to AWS SNS for real-time alerts
  - `MetadataSQSHook`: Propagate metadata changes to AWS SQS for SSE back-propagation
  - Both hooks require `custom_aws` package (python-helpers) as optional dependency
- **Hook Creation Functions**:
  - `create_feedback_sns_hook()`: Create SNS hook with topic ARN
  - `create_metadata_sqs_hook()`: Create SQS hook with queue URL and field filtering
- **Availability Check Functions**:
  - `is_feedback_sns_hook_available()`: Check if SNS hook can be used
  - `is_metadata_sqs_hook_available()`: Check if SQS hook can be used
- **Hooks Package**: New `hooks/` directory containing AWS integration modules
  - Comprehensive docstrings for both hook modules
  - Non-blocking async operation with graceful error handling
  - Support for both async and sync execution contexts

### Updated
- `__init__.py`: Added conditional exports for AWS hooks based on availability
- Documentation updated to include AWS integration patterns
- README.md: Added AWS Integration Hooks section with examples
- CLAUDE.md: Added AWS hooks architecture and usage patterns

### Fixed
- Removed unused `TYPE_CHECKING` import from `__init__.py`
- Fixed missing `List` import in `metadata_sqs_hook.py`

### Technical Details
- SNS hook features:
  - Real-time notifications for feedback events
  - Message attributes for SNS filtering
  - Automatic rating categorization (positive/negative/neutral)
- SQS hook features:
  - Selective field propagation to minimize message size
  - Support for metadata update and delete operations
  - Designed for SSE (Server-Sent Events) back-propagation

## [0.1.8] - 2024-01-26

### Added
- **Feedback System**: New feedback management functionality for storing user ratings and comments
  - `add_feedback()` method in `MongoDBSessionManager` to store feedback with automatic timestamps
  - `get_feedbacks()` method to retrieve all feedback for a session
  - `feedbacks` array field added to MongoDB schema
  - Feedback structure: `{rating: "up"|"down"|null, comment: string, created_at: datetime}`
- **Feedback Hooks**: New `feedbackHook` parameter in `MongoDBSessionManager` constructor
  - `_apply_feedback_hook()` method that wraps the add_feedback method
  - Hook supports "add" action only for intercepting feedback operations
- Comprehensive feedback hook examples:
  - Audit hooks for logging all feedback
  - Validation hooks for ensuring feedback quality
  - Notification hooks for alerting on negative feedback
  - Analytics hooks for collecting feedback metrics
  - Combined hooks for chaining multiple behaviors
- New example file: `examples/example_feedback_hook.py`
- FastAPI integration pattern for receiving feedback from frontend

### Updated
- `MongoDBSessionRepository`: Added `add_feedback()` and `get_feedbacks()` methods
- `MongoDBSessionManagerFactory`: Now passes through feedbackHook parameter
- Documentation updated to include feedback functionality
- README.md: Added comprehensive feedback management section
- CLAUDE.md: Updated with feedback system details

## [0.1.7] - 2024-01-25

### Added
- **Metadata Hooks**: New `metadataHook` parameter in `MongoDBSessionManager` constructor to intercept and enhance metadata operations
- `_apply_metadata_hook()` method that wraps metadata methods (update_metadata, get_metadata, delete_metadata)
- Comprehensive metadata hook examples demonstrating audit, validation, caching, and combined hooks
- New example file: `examples/example_metadata_hook.py`

### Updated
- Documentation updated to include metadata hooks functionality
- README.md and CLAUDE.md now document the hooks feature

## [0.1.6] - 2024-01-24

### Added
- **Metadata Tool**: `get_metadata_tool()` method returns a Strands tool for agents to manage metadata autonomously
- Tool supports three actions: "get", "set/update", and "delete"
- New example files:
  - `examples/example_metadata_tool.py`: Agent using metadata tool autonomously
  - `examples/example_metadata_tool_direct.py`: Direct tool usage patterns

### Updated
- Comprehensive class docstrings for `MongoDBSessionManager` and `MongoDBSessionRepository`

## [0.1.5] - 2024-01-24

### Fixed
- Fixed syntax error in `delete_metadata()` method - corrected dictionary comprehension inside `$unset` operation

### Changed
- **Metadata Updates**: `update_metadata()` now uses MongoDB dot notation for partial updates, preserving existing fields
- Previously metadata updates would replace the entire metadata object

### Added
- New example files:
  - `examples/example_metadata_update.py`: Basic metadata operations
  - `examples/example_metadata_production.py`: Production customer support scenario

## [0.1.4] - 2024-01-23

### Added
- Interactive chat playground with web-based UI
- Real-time streaming support with FastAPI backend
- Playground files:
  - `playground/chat/chat.html`: Web-based chat interface
  - `playground/chat/chat-widget.js`: JavaScript for chat functionality
  - `playground/chat/Makefile`: Easy startup commands

### Updated
- Enhanced streaming examples with better error handling

## [0.1.3] - 2024-01-22

### Added
- Async streaming support with automatic metrics tracking
- `examples/example_stream_async.py`: Demonstrates async streaming with real-time metrics
- `examples/example_fastapi_streaming.py`: FastAPI integration with streaming responses

### Changed
- Improved connection pooling for streaming scenarios
- Better handling of event loop metrics during streaming

## [0.1.2] - 2024-01-21

### Added
- **Factory Pattern**: `MongoDBSessionManagerFactory` for efficient session manager creation
- **Connection Pool Singleton**: `MongoDBConnectionPool` for connection reuse
- Global factory functions:
  - `initialize_global_factory()`
  - `get_global_factory()`
  - `close_global_factory()`
- Performance optimization examples:
  - `examples/example_performance.py`: Benchmarks and comparisons
  - `examples/example_fastapi.py`: FastAPI integration with connection pooling

### Changed
- Session managers can now accept an optional MongoDB client for connection reuse
- Smart connection lifecycle management (owns vs borrowed clients)

### Performance
- Connection overhead reduced from 10-50ms to ~0ms with pooling
- Significant throughput improvement for concurrent requests

## [0.1.1] - 2024-01-20

### Added
- Automatic event loop metrics capture from agents
- Metrics stored in `event_loop_metrics` field of assistant messages
- Token counting (inputTokens, outputTokens, totalTokens)
- Latency measurement in milliseconds

### Changed
- `sync_agent()` now captures metrics from `agent.event_loop_metrics`
- Metrics are attached to the last message in the conversation

## [0.1.0] - 2024-01-15

### Initial Release
- Core MongoDB session persistence for Strands Agents
- Document-based storage with embedded agents and messages
- Full CRUD operations for sessions, agents, and messages
- Session resumption across restarts
- Multiple agents per session support
- Timestamp preservation during updates
- Thread-safe operations
- Comprehensive error handling and logging
- Basic metadata management (create, read operations)
- Example calculator tool demonstration

### Project Structure
- `MongoDBSessionRepository`: Low-level MongoDB operations
- `MongoDBSessionManager`: High-level session management
- `create_mongodb_session_manager()`: Convenience factory function
- UV package manager integration
- Docker Compose setup for local MongoDB

[0.1.15]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.14...v0.1.15
[0.1.14]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.13...v0.1.14
[0.1.13]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.12...v0.1.13
[0.1.12]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.11...v0.1.12
[0.1.11]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.10...v0.1.11
[0.1.10]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/yourusername/mongodb-session-manager/releases/tag/v0.1.0