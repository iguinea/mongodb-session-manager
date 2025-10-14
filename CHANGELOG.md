# Changelog

All notable changes to the MongoDB Session Manager project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.9]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/yourusername/mongodb-session-manager/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/yourusername/mongodb-session-manager/releases/tag/v0.1.0