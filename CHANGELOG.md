# Changelog

All notable changes to the MongoDB Session Manager project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.19] - 2025-10-16

### Added
- **Dynamic Index-Based Filters**: Session Viewer filters now automatically based on MongoDB indexes
  - Backend queries collection indexes (`list_indexes()`) to determine available filters
  - Automatic type detection (string, date, number, boolean, enum) by sampling documents
  - Configurable enum fields via `ENUM_FIELDS_STR` environment variable
  - Type-appropriate UI controls:
    - Enum fields → Dropdown with predefined values
    - Date fields → Date picker
    - Number fields → Number input
    - Boolean fields → True/False dropdown
    - String fields → Text input (default)
  - Performance guarantee: only indexed fields can be filtered (no full collection scans)

### Changed
- **API Response Structure**: `/api/v1/metadata-fields` now returns `FieldInfo` objects with type information
  - **Old format** (v0.1.16-0.1.18):
    ```json
    {
      "fields": ["status", "priority"],
      "sample_values": {"status": ["active", "completed"]}
    }
    ```
  - **New format** (v0.1.19+):
    ```json
    {
      "fields": [
        {"field": "metadata.status", "type": "enum", "values": ["active", "completed"]},
        {"field": "created_at", "type": "date"},
        {"field": "session_id", "type": "string"}
      ]
    }
    ```
- **Frontend Filter Rendering**: Dynamic filter inputs now adapt to field type automatically
- **Backend Version**: FastAPI app version updated to 0.1.19

### Configuration
New environment variables for dynamic filter configuration:
- `ENUM_FIELDS_STR`: Comma-separated list of fields to treat as enum dropdowns
  - Example: `metadata.status,metadata.priority,metadata.case_type`
  - Fields not in this list will use text input (even if they have few unique values)
- `ENUM_MAX_VALUES`: Maximum distinct values for enum detection (default: 50)
  - If a configured enum field has more values than this limit, it falls back to text input

### Implementation Details
- **Backend**: 3 new helper functions in `main.py`:
  - `get_indexed_fields()`: Extracts field names from MongoDB indexes
  - `detect_field_type()`: Samples 100 documents to determine field type
  - `get_enum_values()`: Retrieves distinct values for enum fields
  - `get_metadata_fields()`: Refactored to use index-based approach
- **Frontend**: Major refactor of `renderDynamicFilter()` in `components.js`:
  - Field selector now stores type information in dataset attributes
  - Event listener on field change renders appropriate input control
  - Enum values stored as JSON and parsed dynamically

### Benefits
- ✅ **Automatic**: Filters adapt to existing indexes without code changes
- ✅ **Performant**: Only indexed fields = guaranteed fast queries
- ✅ **Flexible**: Enum configuration via environment variables
- ✅ **Extensible**: Add new filter by creating MongoDB index + optional enum config
- ✅ **Type-safe**: Appropriate UI controls reduce user errors
- ✅ **Maintainable**: No hardcoded filter lists

### Migration Guide
**Backward Compatible**: Frontend continues to work if backend returns old format.

**To Enable Dynamic Filters**:
1. Ensure fields you want to filter have MongoDB indexes:
   ```javascript
   db.sessions.createIndex({"metadata.status": 1});
   db.sessions.createIndex({"metadata.priority": 1});
   db.sessions.createIndex({"created_at": -1});
   ```
2. Configure enum fields in `.env`:
   ```bash
   ENUM_FIELDS_STR=metadata.status,metadata.priority
   ```
3. Restart backend: `cd session_viewer/backend && make dev`
4. Frontend will automatically load new field structure

### Documentation
- Updated `features/3_dynamic_index_filters/plan.md` with complete specification
- Updated `features/3_dynamic_index_filters/progress.md` for tracking
- Updated `session_viewer/backend/.env.example` with new configuration
- See full documentation in feature plan for implementation details

## [0.1.18] - 2025-10-15

### Added
- **Authentication System**: Password protection for Session Viewer application
  - Backend endpoint `POST /api/v1/check_password` for password validation
  - Password stored as `BACKEND_PASSWORD` in `.env` (default: `123456`)
  - SHA-256 password hashing using js-sha256 library for security
  - Frontend modal with elegant dark gradient background and centered logo
  - Header-based authentication (`X-Password`) for all API requests
  - Middleware validates password on every request (except `/health` and `/check_password`)
  - Password stored in memory only (not localStorage) - lost on browser close/refresh
  - Unlimited retry attempts with clear error messages
  - Auto-focus on password input for better UX

- **Resizable Panels**: Drag-to-resize functionality for left panel (Filters + Results)
  - Drag handle between panels with visual hover/dragging states
  - Width constraints: 20% minimum, 70% maximum
  - localStorage persistence for user preference
  - Responsive design: disabled on mobile (stacks vertically)
  - Smooth dragging with cursor change and text selection prevention

- **Interactive JSON Visualization**: Enhanced JSON display using renderjson library
  - Tool calls and results now display as collapsible JSON trees
  - Metadata display with interactive expand/collapse controls
  - "Expand All" / "Collapse All" buttons for metadata section
  - Syntax highlighting with color-coded types (strings, numbers, booleans, keys)
  - Configurable display levels (show 2 levels by default)
  - String truncation for long values (100 chars max)

- **Direct Session Loading**: URL parameter support for quick access
  - Use `?session_id=<ID>` to load session directly on page load
  - Automatic session detail display on initialization
  - Useful for sharing links to specific sessions

- **Favicon**: Added custom SVG favicon for better branding
  - Blue document/list icon matching the application theme
  - Visible in browser tabs and bookmarks

### Changed
- **CORS Configuration**: Set to allow all origins (`*`) for easier development
  - Changed from specific origins to wildcard for development
  - `allow_credentials` set to `False` (required with `allow_origins=["*"]`)
  - Commented for easy production switch back to specific origins

- **Frontend Initialization**: Application only starts after successful authentication
  - SessionViewer and PanelResizer initialized after password validation
  - Clean modal removal from DOM on successful login

- **Layout System**: Changed from CSS Grid to Flexbox for resizable panels
  - Left panel with fixed/adjustable width
  - Right panel flex-grows to fill remaining space
  - Resize handle positioned between panels

### Security
- **Password Hashing**: SHA-256 hash of password travels over network, not plain text
- **No Persistence**: Password not stored in browser (localStorage/sessionStorage)
- **Session-based**: Password required on every page load/refresh
- **Header-based Auth**: All API requests include `X-Password` header with hash
- **Environment Variable**: Password stored in backend `.env` as `BACKEND_PASSWORD`

### Technical Details
- **Modified Files**:
  - Backend: `main.py` (authentication middleware + endpoint), `config.py` (BACKEND_PASSWORD), `.env` (BACKEND_PASSWORD=123456)
  - Frontend: `index.html` (auth modal + resizable layout + renderjson), `viewer.js` (PanelResizer class + URL params + metadata controls)
  - Libraries: Added `js-sha256` (0.9.0) and `renderjson` (1.4.0) via CDN

- **Authentication Flow**:
  1. User opens page → Modal displayed with dark gradient background
  2. User enters password → Frontend hashes with SHA-256
  3. Frontend sends hash to `POST /api/v1/check_password`
  4. Backend validates hash against environment variable
  5. On success: Modal removed, axios configured with header, app initialized
  6. On failure: Error message displayed, retry allowed

- **Panel Resizing**:
  - Mouse events: `mousedown`, `mousemove`, `mouseup`
  - Width calculated as percentage of parent container
  - Body class `resizing` added during drag to prevent text selection
  - localStorage key: `session-viewer-left-panel-width`

### Benefits
- **Security**: Unauthorized users cannot access session data
- **Flexibility**: Resizable panels adapt to user preferences
- **Usability**: Better JSON visualization improves data comprehension
- **Convenience**: Direct session URLs enable easy sharing and bookmarking
- **Branding**: Favicon improves professional appearance

### Configuration
```bash
# Backend .env
BACKEND_PASSWORD=123456  # Change for production
ALLOWED_ORIGINS_STR=*    # For development, specify origins for production
```

### Usage Examples
```bash
# Access with authentication
http://localhost:8883
# Enter password: 123456

# Direct session access
http://localhost:8883?session_id=abc123

# Resize panels
# Drag the vertical handle between left and right panels
```

## [0.1.17] - 2025-10-15

### Added
- **Session Viewer UI Enhancements**: Major improvements to visualization and user experience
  - **Tool Call Visualization**: Display tool calls and results in timeline with color-coded badges
    - 🔧 Blue badges for tool calls with collapsible JSON input parameters
    - ✅ Green badges for successful tool results with collapsible output
    - ❌ Red badges for failed tool results with error details
    - New functions: `parseMessageContent()`, `renderToolUse()`, `renderToolResult()`
    - Professional styling with hover effects and transitions
  - **System Prompt Display**: Full markdown-rendered system prompts in agent summary
    - Click "📝 System Prompt" to expand/collapse full prompt
    - Uses zero-md for professional markdown rendering (code blocks, lists, emphasis)
    - Scrollable area (max 300px) with custom scrollbar
    - No more truncated prompts - see the complete agent configuration
  - **Layout Reorganization**: Improved workflow with new 2-column layout
    - Left column (5/12): Filters + Results stacked vertically
    - Right column (7/12): Session details (wider for better content display)
    - More intuitive flow: filter → see results → explore details
    - Better space utilization on all screen sizes

### Changed
- Session Viewer frontend now uses 2-column layout instead of 3-column
- Agent Summary displays full system prompts with markdown rendering instead of truncated text (was 60 chars)
- Timeline messages now parse and display `toolUse` and `toolResult` content types alongside text
- Results panel height adjusted to `calc(100vh - 600px)` to accommodate filters above

### Fixed
- Tool calls and results were previously rendered as plain text, now properly visualized

### Technical Details
- **Modified Files**:
  - `session_viewer/frontend/components.js`:
    - Lines 121-160: New `parseMessageContent()` function to detect text/toolUse/toolResult
    - Lines 166-222: New tool rendering functions (`renderToolUse`, `renderToolResult`)
    - Lines 228-334: Enhanced `renderTimelineMessage()` with multi-content parsing
    - Lines 427-518: Rewritten `renderAgentSummary()` with zero-md integration
  - `session_viewer/frontend/index.html`:
    - Lines 92-226: CSS styles for tool blocks, badges, and collapsible details
    - Lines 227-273: CSS styles for agent prompt display with custom scrollbar
    - Lines 248-385: Reorganized grid layout structure (3 cols → 2 cols)

### Benefits
- **Better Debugging**: Visual distinction between tool calls, results, and text messages
- **Full Context**: Complete system prompts help understand agent behavior
- **Improved UX**: More intuitive layout reduces eye movement and improves workflow
- **Professional Look**: Color-coded badges and collapsible sections for clean timeline

## [0.1.16] - 2025-10-15

### Added
- **Session Viewer**: Full-featured web application for viewing and analyzing MongoDB sessions
  - **Backend FastAPI API** (`session_viewer/backend/`):
    - 4 REST API endpoints with dynamic filtering and pagination
    - `GET /api/v1/sessions/search` - Search sessions with multiple filters (AND logic)
    - `GET /api/v1/sessions/{id}` - Get complete session with unified timeline
    - `GET /api/v1/metadata-fields` - List available metadata fields dynamically
    - `GET /health` - Health check with connection pool statistics
    - Dynamic MongoDB query builder for metadata filters
    - Unified timeline algorithm (merges multi-agent messages + feedbacks chronologically)
    - Connection pooling integration for high performance
    - CORS configuration for frontend integration
    - Comprehensive error handling and logging
  - **Frontend Web Application** (`session_viewer/frontend/`):
    - Modern UI with Tailwind CSS and vanilla JavaScript (ES6 classes)
    - 3-panel layout: Filters, Results, Session Detail
    - Dynamic filter panel with add/remove metadata filters
    - Session search with session ID, date range, and metadata fields
    - Pagination for search results (configurable page size)
    - Session detail view with expandable metadata
    - Unified chronological timeline for all agents
    - Message rendering with markdown support (marked.js)
    - Feedback indicators inline in timeline (👍/👎)
    - Metrics display (tokens, latency) for assistant messages
    - Agent summary with model and system_prompt configuration
    - Real-time health check indicator
    - Responsive design for desktop, tablet, and mobile
  - **Libraries Used**:
    - Backend: FastAPI, pydantic-settings, uvicorn
    - Frontend: Tailwind CSS (CDN), marked.js, dayjs, axios
  - **Documentation**:
    - Backend README with API documentation and examples
    - Frontend README with architecture and usage guide
    - Feature plan in `features/2_session_viewer/plan.md`
    - Progress tracking in `features/2_session_viewer/progress.md`
    - Makefile commands for both backend and frontend

### Features
- **Dynamic Metadata Filtering**: Users can add any metadata field as a filter at runtime
- **Multi-criteria Search**: Combine session ID, date range, and multiple metadata filters
- **Pagination**: Server-side pagination with configurable page sizes (default 20, max 100)
- **Timeline Unification**: Messages from all agents and feedbacks merged chronologically
- **Markdown Rendering**: Full markdown support in assistant messages
- **Feedback Integration**: User feedbacks displayed at correct chronological position
- **Agent Configuration Display**: Shows model and system_prompt for each agent
- **Health Monitoring**: Real-time backend connectivity status
- **Configurable**: Backend settings via `.env` file

### Architecture
- **Backend**: RESTful API with FastAPI, MongoDB aggregation pipelines, connection pooling
- **Frontend**: OOP JavaScript with classes (APIClient, FilterPanel, ResultsList, SessionDetail, SessionViewer)
- **Communication**: Axios for HTTP requests, JSON data exchange
- **Styling**: Utility-first Tailwind CSS, responsive grid layout
- **Deployment**: Backend on port 8882, Frontend on port 8883

### Files Created
- Backend: `config.py`, `models.py`, `main.py`, `.env.example`, `Makefile`, `README.md`
- Frontend: `index.html`, `viewer.js`, `components.js`, `Makefile`, `README.md`
- Total: 11 new files with 1500+ lines of code

### Usage
```bash
# Backend
cd session_viewer/backend
cp .env.example .env
make run  # or: uv run python main.py

# Frontend
cd session_viewer/frontend
make run  # or: python3 -m http.server 8883

# Access: http://localhost:8883
```

### Benefits
- **Debugging**: Visualize complete conversation flows across multiple agents
- **Analytics**: Analyze session patterns by metadata fields
- **Auditing**: Review historical interactions and feedbacks
- **Troubleshooting**: Identify issues in agent responses and timing
- **User Research**: Understand user behavior and feedback patterns

### Technical Details
- REST API follows OpenAPI 3.0 specification
- MongoDB queries use regex for partial matching (case-insensitive)
- Timeline sorting by `created_at` timestamp (ISO 8601)
- Frontend uses ES6 classes for maintainable OOP architecture
- Components are pure functions for reusability
- Loading and empty states for better UX
- Error handling with user-friendly messages
- CORS enabled for localhost development

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

[0.1.17]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.16...v0.1.17
[0.1.16]: https://github.com/iguinea/mongodb-session-manager/compare/v0.1.15...v0.1.16
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