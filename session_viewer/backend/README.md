# Session Viewer Backend

FastAPI backend for the MongoDB Session Viewer application.

## Features

- **Authentication System**: Password-protected access with SHA-256 hashing
- **Dynamic Filtering**: Search sessions using configurable metadata fields
- **Pagination**: Server-side pagination with configurable page sizes
- **Unified Timeline**: Chronologically merged messages from multiple agents and feedbacks
- **Connection Pooling**: Efficient MongoDB connection management
- **CORS Support**: Configured for frontend integration (development mode: wildcard origins)
- **Health Checks**: Monitor service and database status

## Architecture

```
backend/
├── main.py              # FastAPI application with endpoints
├── config.py            # Configuration management
├── models.py            # Pydantic models for request/response
├── .env.example         # Configuration template
├── Makefile             # Development commands
└── README.md            # This file
```

## Setup

### 1. Prerequisites

- Python 3.13+
- UV package manager
- MongoDB instance running (configured in .env)

### 2. Configuration

Copy the example environment file and configure:

```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Install Dependencies

Dependencies are managed by the parent project's UV configuration.

## Usage

### Start the Server

```bash
# Using Makefile
make run

# Or directly with UV
uv run python main.py

# Development mode with auto-reload
make dev
```

The server will start on `http://localhost:8882` by default.

## API Endpoints

### `POST /api/v1/check_password`

Validate password hash for authentication.

**Request Body:**
```json
{
  "password_hash": "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92"
}
```

**Response:**
```json
{
  "valid": true
}
```

**Authentication:**
- This endpoint does NOT require authentication (used for login)
- Password is hashed with SHA-256 on frontend before sending
- Backend validates against `BACKEND_PASSWORD` environment variable

### `GET /api/v1/sessions/search`

Search sessions with dynamic filters and pagination.

**Query Parameters:**
- `filters` (string, optional): JSON string with metadata filters
- `session_id` (string, optional): Session ID for partial matching
- `created_at_start` (datetime, optional): Start date for filtering
- `created_at_end` (datetime, optional): End date for filtering
- `limit` (int, default=20): Results per page
- `offset` (int, default=0): Pagination offset

**Example Request:**
```bash
curl "http://localhost:8882/api/v1/sessions/search?filters=%7B%22metadata.case_type%22%3A%22IP_REAPERTURA%22%7D&limit=10"
```

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "68ee8a6e8ff935ffff0f7b85",
      "created_at": "2025-10-14T17:37:50.668Z",
      "updated_at": "2025-10-14T17:38:28.325Z",
      "metadata": {...},
      "agents_count": 1,
      "messages_count": 4,
      "feedbacks_count": 1
    }
  ],
  "total": 100,
  "limit": 10,
  "offset": 0,
  "has_more": true
}
```

### `GET /api/v1/sessions/{session_id}`

Get complete session detail with unified timeline.

**Example Request:**
```bash
curl "http://localhost:8882/api/v1/sessions/68ee8a6e8ff935ffff0f7b85"
```

**Response:**
```json
{
  "session_id": "68ee8a6e8ff935ffff0f7b85",
  "created_at": "2025-10-14T17:37:50.668Z",
  "updated_at": "2025-10-14T17:38:28.325Z",
  "metadata": {...},
  "timeline": [
    {
      "type": "message",
      "timestamp": "2025-10-14T17:37:54.164Z",
      "agent_id": "case_dispatcher",
      "role": "user",
      "content": [...],
      "message_id": 0
    },
    {
      "type": "feedback",
      "timestamp": "2025-10-14T17:38:02.006Z",
      "rating": "up",
      "comment": "Excelente análisis"
    }
  ],
  "agents_summary": {
    "case_dispatcher": {
      "messages_count": 4,
      "model": "eu.anthropic.claude-sonnet-4-20250514-v1:0",
      "system_prompt": "..."
    }
  }
}
```

### `GET /api/v1/metadata-fields`

Get indexed fields with type information and enum values (v0.1.19+).

**Behavior:**
1. Queries MongoDB collection indexes to find filterable fields
2. Detects data type for each field (string, date, number, boolean, enum)
3. For fields configured in `ENUM_FIELDS_STR`, retrieves distinct values
4. Returns structured `FieldInfo` objects with type and optional enum values

**Configuration:**
- `ENUM_FIELDS_STR`: Comma-separated fields to treat as enums
- `ENUM_MAX_VALUES`: Max distinct values for enum (default: 50)

**Example Request:**
```bash
curl "http://localhost:8882/api/v1/metadata-fields"
```

**Response (v0.1.19+):**
```json
{
  "fields": [
    {
      "field": "created_at",
      "type": "date"
    },
    {
      "field": "session_id",
      "type": "string"
    },
    {
      "field": "metadata.case_type",
      "type": "enum",
      "values": ["Analizando caso", "IP_REAPERTURA", "NEW_CASE"]
    },
    {
      "field": "metadata.priority",
      "type": "enum",
      "values": ["low", "medium", "high", "urgent", "critical"]
    },
    {
      "field": "metadata.customer_phone",
      "type": "string"
    }
  ]
}
```

**Field Types:**
- `string`: Text input field (default)
- `date`: Date picker
- `number`: Number input
- `boolean`: True/False dropdown
- `enum`: Dropdown with predefined values (requires `ENUM_FIELDS_STR` configuration)

**Response Format Changes:**

| Version | Format |
|---------|--------|
| v0.1.16-0.1.18 | `{"fields": [...], "sample_values": {...}}` |
| v0.1.19+ | `{"fields": [{"field": "...", "type": "...", "values": [...]}]}` |

**Migration Notes:**
- Frontend is backward compatible
- Old format still works if backend returns it
- New format provides better UX with type-appropriate input controls

### `GET /health`

Health check endpoint.

**Authentication:**
- This endpoint does NOT require authentication

**Example Request:**
```bash
curl "http://localhost:8882/health"
```

**Response:**
```json
{
  "status": "healthy",
  "mongodb": "connected",
  "connection_pool": {
    "active_connections": 5,
    "available_connections": 95,
    "total_connections": 100
  }
}
```

## Authentication

All API endpoints (except `/health` and `/api/v1/check_password`) require password authentication.

### Authentication Flow

1. User enters password in frontend modal
2. Frontend hashes password with SHA-256: `sha256(password)`
3. Frontend sends hash to `POST /api/v1/check_password`
4. Backend validates hash against environment variable `BACKEND_PASSWORD`
5. On success: Frontend stores hash in memory and includes it in all subsequent requests
6. All API requests include header: `X-Password: <sha256_hash>`

### Security Features

- **No Plain Text**: Password never travels as plain text
- **SHA-256 Hashing**: Password hashed on frontend using js-sha256 library
- **Header-based Auth**: Hash included in `X-Password` header
- **No Persistence**: Hash stored in memory only (lost on browser close/refresh)
- **Middleware Validation**: Every request validates password (except health/check_password)
- **Environment Variable**: Backend password configured in `.env` file

### Making Authenticated Requests

```bash
# First, hash your password (using Node.js as example)
PASSWORD_HASH=$(echo -n "123456" | sha256sum | cut -d' ' -f1)

# Then include in header
curl -H "X-Password: $PASSWORD_HASH" "http://localhost:8882/api/v1/sessions/search"
```

**With Python:**
```python
import hashlib
import requests

# Hash password
password = "123456"
password_hash = hashlib.sha256(password.encode()).hexdigest()

# Make authenticated request
headers = {"X-Password": password_hash}
response = requests.get(
    "http://localhost:8882/api/v1/sessions/search",
    headers=headers
)
```

## Configuration

All configuration is managed via environment variables in `.env`. Copy `.env.example` to `.env` and configure according to your environment.

### Environment Variables Reference

| Variable | Type | Default | Required | Description |
|----------|------|---------|----------|-------------|
| **MongoDB** |
| `MONGODB_CONNECTION_STRING` | string | `mongodb://...` | ✅ Production | MongoDB connection string. **⚠️ Change for production** |
| `DATABASE_NAME` | string | `examples` | Recommended | Database name for sessions |
| `COLLECTION_NAME` | string | `sessions` | Optional | Collection name for session documents |
| **Security** |
| `BACKEND_PASSWORD` | string | `123456` | ✅ Production | Password for authentication. **⚠️ CRITICAL: Change for production** |
| **Server** |
| `BACKEND_HOST` | string | `0.0.0.0` | Optional | Host to bind the server |
| `BACKEND_PORT` | int | `8882` | Optional | Port for the FastAPI server |
| **CORS** |
| `ALLOWED_ORIGINS_STR` | string | `http://localhost:8883,...` | Optional | Comma-separated allowed origins. **Note:** Code currently uses `*` (see Production) |
| **Connection Pool** |
| `MAX_POOL_SIZE` | int | `100` | Optional | Maximum MongoDB connections in pool |
| `MIN_POOL_SIZE` | int | `10` | Optional | Minimum MongoDB connections in pool |
| `MAX_IDLE_TIME_MS` | int | `30000` | Optional | Max idle time for connections (ms) |
| **Pagination** |
| `DEFAULT_PAGE_SIZE` | int | `20` | Optional | Default results per page |
| `MAX_PAGE_SIZE` | int | `100` | Optional | Maximum results per page allowed |
| **Dynamic Filters (v0.1.19+)** |
| `ENUM_FIELDS_STR` | string | `""` (empty) | Optional | Comma-separated fields to display as dropdowns |
| `ENUM_MAX_VALUES` | int | `50` | Optional | Max distinct values for enum detection |
| **Logging** |
| `LOG_LEVEL` | string | `INFO` | Optional | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |

### Detailed Configuration

#### MongoDB Configuration
```bash
# Development (local MongoDB)
MONGODB_CONNECTION_STRING=mongodb://localhost:27017/

# Production (MongoDB Atlas)
MONGODB_CONNECTION_STRING=mongodb+srv://user:password@cluster.mongodb.net/

# With Docker Compose (default)
MONGODB_CONNECTION_STRING=mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/

DATABASE_NAME=examples              # Change for production
COLLECTION_NAME=sessions
```

#### Security Configuration
```bash
# CRITICAL: Change password for production
BACKEND_PASSWORD=my_super_secure_password_2024

# Password is hashed with SHA-256 on frontend before transmission
# All endpoints (except /health and /check_password) require authentication
```

#### Dynamic Filter Configuration (v0.1.19+)

Configure which fields should display as dropdowns with predefined values:

```bash
# Fields to treat as enums (dropdowns)
# Comma-separated list of full field paths
ENUM_FIELDS_STR=metadata.status,metadata.priority,metadata.case_type

# Maximum distinct values for enum detection
# If a configured enum field exceeds this limit, it falls back to text input
ENUM_MAX_VALUES=50
```

**How it works:**
1. Backend queries MongoDB indexes to find filterable fields
2. For fields in `ENUM_FIELDS_STR`, retrieves distinct values
3. If distinct values ≤ `ENUM_MAX_VALUES`, displays as dropdown
4. Otherwise, displays as text input
5. Guarantees performance by only allowing indexed fields

**Example:**
```bash
# Configure dropdowns for status and priority
ENUM_FIELDS_STR=metadata.status,metadata.priority

# status has 3 values → dropdown with ["active", "completed", "failed"]
# priority has 5 values → dropdown with ["low", "medium", "high", "urgent", "critical"]
# Other fields → text input
```

#### CORS Configuration
```bash
# Development (allows all origins) - currently hardcoded in main.py
ALLOWED_ORIGINS_STR=*

# Production (specific origins)
ALLOWED_ORIGINS_STR=https://yourdomain.com,https://app.yourdomain.com
```

**⚠️ Important:** The code in `main.py:107-113` currently uses `allow_origins=["*"]` for development. For production, change to `allow_origins=settings.allowed_origins`.

#### Connection Pool Configuration
```bash
MAX_POOL_SIZE=100        # Max connections (adjust for high traffic)
MIN_POOL_SIZE=10         # Min connections (always available)
MAX_IDLE_TIME_MS=30000   # Close idle connections after 30 seconds
```

#### Pagination Configuration
```bash
DEFAULT_PAGE_SIZE=20     # Results per page (user can override)
MAX_PAGE_SIZE=100        # Maximum allowed (prevents large queries)
```

#### Logging Configuration
```bash
# Development
LOG_LEVEL=DEBUG

# Production
LOG_LEVEL=WARNING
```

### Production Configuration

For production deployments, follow this checklist:

#### 1. Security Configuration

```bash
# Set strong password (required)
BACKEND_PASSWORD=<your_strong_password_here>

# Use production MongoDB (required)
MONGODB_CONNECTION_STRING=mongodb+srv://user:password@cluster.mongodb.net/
DATABASE_NAME=production_sessions
```

**Security Best Practices:**
- Use passwords with at least 16 characters
- Include uppercase, lowercase, numbers, and symbols
- Never commit `.env` file to version control
- Rotate passwords regularly
- Use environment-specific passwords (dev, staging, prod)

#### 2. CORS Configuration

**⚠️ Critical:** Update `main.py` to use specific origins instead of wildcard:

```python
# In main.py, change from:
allow_origins=["*"]

# To:
allow_origins=settings.allowed_origins
```

Then configure allowed origins:
```bash
ALLOWED_ORIGINS_STR=https://yourdomain.com,https://app.yourdomain.com
```

#### 3. Dynamic Filters Configuration

Configure enum fields for optimal UX:

```bash
# Analyze your metadata fields and configure the most common ones as enums
ENUM_FIELDS_STR=metadata.status,metadata.priority,metadata.case_type

# Adjust threshold based on your data
ENUM_MAX_VALUES=50
```

**How to identify enum candidates:**
```javascript
// In MongoDB shell
db.sessions.distinct("metadata.status").length  // If < 50, good candidate
```

#### 4. Performance Tuning

```bash
# Adjust pool size based on expected load
MAX_POOL_SIZE=200        # Higher for high-traffic applications
MIN_POOL_SIZE=20         # Higher for consistent load

# Adjust pagination for your use case
DEFAULT_PAGE_SIZE=20     # Lower for faster response times
MAX_PAGE_SIZE=50         # Lower to prevent large queries
```

#### 5. Logging Configuration

```bash
# Production: reduce noise
LOG_LEVEL=WARNING

# Staging: more visibility
LOG_LEVEL=INFO

# Development: full visibility
LOG_LEVEL=DEBUG
```

#### 6. Infrastructure Setup

**HTTPS (Required for Production):**
Use reverse proxy (nginx/caddy) to handle HTTPS:

```nginx
# nginx example
server {
    listen 443 ssl;
    server_name api.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8882;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**MongoDB Indexes (Required for Performance):**
Create indexes for fields you want to filter:

```javascript
// In MongoDB shell
db.sessions.createIndex({"session_id": 1});
db.sessions.createIndex({"created_at": -1});
db.sessions.createIndex({"metadata.status": 1});
db.sessions.createIndex({"metadata.priority": 1});
db.sessions.createIndex({"metadata.case_type": 1});
```

**Note:** Only indexed fields will be available for filtering in v0.1.19+

#### 7. Monitoring

```bash
# Enable detailed health checks
curl https://api.yourdomain.com/health

# Monitor connection pool statistics
# Check "connection_pool" section in health response
```

#### Production Environment Example

Complete `.env` for production:

```bash
# MongoDB
MONGODB_CONNECTION_STRING=mongodb+srv://prod_user:secure_pass@cluster.mongodb.net/
DATABASE_NAME=production_sessions
COLLECTION_NAME=sessions

# Security
BACKEND_PASSWORD=<your_production_password>

# Server
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8882

# CORS (remember to update main.py!)
ALLOWED_ORIGINS_STR=https://yourdomain.com,https://app.yourdomain.com

# Connection Pool
MAX_POOL_SIZE=200
MIN_POOL_SIZE=20
MAX_IDLE_TIME_MS=30000

# Pagination
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=50

# Dynamic Filters
ENUM_FIELDS_STR=metadata.status,metadata.priority,metadata.case_type
ENUM_MAX_VALUES=50

# Logging
LOG_LEVEL=WARNING
```

## Development

### Available Commands

```bash
# Start server
make run

# Start in development mode (with auto-reload)
make dev

# Format code (future)
make format

# Run tests (future)
make test
```

### Project Structure

- **main.py**: FastAPI application with all endpoints
- **config.py**: Configuration management using pydantic-settings
- **models.py**: Pydantic models for request/response validation
- **.env**: Environment configuration (not in git)
- **.env.example**: Configuration template

## Key Features

### Dynamic Metadata Filtering

The search endpoint supports dynamic metadata field filtering. Users can filter by any metadata field without code changes:

```bash
# Filter by case type
?filters={"metadata.case_type":"IP_REAPERTURA"}

# Multiple filters
?filters={"metadata.case_type":"IP_REAPERTURA","metadata.customer_phone":"604"}
```

### Unified Timeline

The timeline merges messages from all agents and feedbacks into a single chronologically ordered view:

1. Extracts messages from all agents
2. Extracts all feedbacks
3. Sorts everything by timestamp
4. Returns unified timeline

This allows viewing the complete conversation flow across multiple agents.

### Connection Pooling

Uses the existing `MongoDBConnectionPool` from the parent project for efficient connection management:

- Shared connection pool across all requests
- Configurable pool size
- Connection lifecycle management
- Statistics monitoring

## Testing

### Manual Testing with curl

```bash
# Health check
curl http://localhost:8882/health

# List metadata fields
curl http://localhost:8882/api/v1/metadata-fields

# Search all sessions
curl "http://localhost:8882/api/v1/sessions/search"

# Search with filter
curl "http://localhost:8882/api/v1/sessions/search?session_id=68ee"

# Get session detail
curl "http://localhost:8882/api/v1/sessions/68ee8a6e8ff935ffff0f7b85"
```

### Testing with Python

```python
import requests

# Health check
response = requests.get("http://localhost:8882/health")
print(response.json())

# Search sessions
response = requests.get(
    "http://localhost:8882/api/v1/sessions/search",
    params={
        "filters": '{"metadata.case_type": "IP_REAPERTURA"}',
        "limit": 10
    }
)
print(response.json())
```

## Troubleshooting

### MongoDB Connection Issues

1. Verify MongoDB is running:
```bash
docker ps | grep mongodb
```

2. Check connection string in `.env`
3. Verify network connectivity
4. Check logs: `LOG_LEVEL=DEBUG make run`

### CORS Issues

If frontend cannot connect:

1. Verify `ALLOWED_ORIGINS` in `.env` includes frontend URL
2. Check browser console for CORS errors
3. Ensure backend is running on expected port

### Performance Issues

1. Check connection pool statistics via `/health` endpoint
2. Monitor MongoDB slow queries
3. Add indexes on frequently queried metadata fields
4. Adjust `MAX_POOL_SIZE` in configuration

## API Documentation

Interactive API documentation is available when the server is running:

- Swagger UI: http://localhost:8882/docs
- ReDoc: http://localhost:8882/redoc

## Next Steps

After backend is running:
1. Test all endpoints with curl or Postman
2. Verify MongoDB connection and queries
3. Start frontend development
4. Integrate frontend with backend API

## Support

For issues or questions:
- Check logs with `LOG_LEVEL=DEBUG`
- Review API documentation at `/docs`
- Consult parent project documentation in `/README.md`
