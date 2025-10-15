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

List available metadata fields across all sessions.

**Example Request:**
```bash
curl "http://localhost:8882/api/v1/metadata-fields"
```

**Response:**
```json
{
  "fields": [
    "case_type",
    "customer_phone",
    "customer_cups",
    "customer_itaxnum"
  ],
  "sample_values": {
    "case_type": ["Analizando caso", "IP_REAPERTURA", "NEW_CASE"],
    "customer_phone": ["604518797", "612345678"]
  }
}
```

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

All configuration is managed via environment variables in `.env`:

```bash
# MongoDB Configuration
MONGODB_CONNECTION_STRING=mongodb://mongodb:mongodb@localhost:27017/
DATABASE_NAME=examples
COLLECTION_NAME=sessions

# Backend Server
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8882

# Authentication
BACKEND_PASSWORD=123456  # Change for production!

# CORS (Development mode - allows all origins)
# For production, specify allowed origins in ALLOWED_ORIGINS_STR
ALLOWED_ORIGINS_STR=*

# Pagination
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=100

# Logging
LOG_LEVEL=INFO
```

### Production Configuration

For production deployments:

1. **Change Password**: Set strong password in `BACKEND_PASSWORD`
2. **Configure CORS**: Change from `*` to specific origins:
   ```bash
   ALLOWED_ORIGINS_STR=https://yourdomain.com,https://app.yourdomain.com
   ```
3. **Update main.py**: Modify CORS middleware to use `settings.allowed_origins` instead of `["*"]` (see comments in code)
4. **Enable HTTPS**: Use reverse proxy (nginx/caddy) for HTTPS
5. **Set LOG_LEVEL**: Change to `WARNING` or `ERROR` for production

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
