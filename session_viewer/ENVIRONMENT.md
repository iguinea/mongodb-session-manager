# Session Viewer - Environment Variables Documentation

Complete reference for configuring the Session Viewer backend via environment variables.

## Table of Contents

- [Quick Start](#quick-start)
- [Variables Reference](#variables-reference)
- [Configuration by Category](#configuration-by-category)
- [Environment-Specific Configurations](#environment-specific-configurations)
- [Troubleshooting](#troubleshooting)
- [Security Best Practices](#security-best-practices)

## Quick Start

### Minimal Configuration (Development)

```bash
# Copy example file
cd session_viewer/backend
cp .env.example .env

# Edit .env - minimum required for local development
MONGODB_CONNECTION_STRING=mongodb://localhost:27017/
BACKEND_PASSWORD=dev123
```

### Recommended Configuration (Production)

```bash
# MongoDB
MONGODB_CONNECTION_STRING=mongodb+srv://user:password@cluster.mongodb.net/
DATABASE_NAME=production_sessions

# Security
BACKEND_PASSWORD=your_strong_password_here

# Dynamic Filters (v0.1.19+)
ENUM_FIELDS_STR=metadata.status,metadata.priority,metadata.case_type

# Performance
MAX_POOL_SIZE=200
LOG_LEVEL=WARNING
```

## Variables Reference

### Complete Table

| Variable | Type | Default | Required | Since | Description |
|----------|------|---------|----------|-------|-------------|
| **MongoDB Configuration** |
| `MONGODB_CONNECTION_STRING` | string | `mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/` | ✅ Production | v0.1.16 | MongoDB connection string. **⚠️ CRITICAL: Change for production** |
| `DATABASE_NAME` | string | `examples` | 🟡 Recommended | v0.1.16 | Database name for storing sessions |
| `COLLECTION_NAME` | string | `sessions` | ❌ Optional | v0.1.16 | Collection name for session documents |
| **Security** |
| `BACKEND_PASSWORD` | string | `123456` | ✅ Production | v0.1.18 | Password for authentication. **⚠️ CRITICAL: Change for production** |
| **Server Configuration** |
| `BACKEND_HOST` | string | `0.0.0.0` | ❌ Optional | v0.1.16 | Host to bind the FastAPI server (0.0.0.0 = all interfaces) |
| `BACKEND_PORT` | int | `8882` | ❌ Optional | v0.1.16 | Port for the FastAPI server |
| **CORS** |
| `FRONTEND_URL` | string | `http://localhost:8883` | ❌ Optional | v0.1.16 | Frontend URL (legacy, not actively used) |
| `ALLOWED_ORIGINS_STR` | string | `http://localhost:8883,http://127.0.0.1:8883,http://0.0.0.0:8883` | ❌ Optional | v0.1.16 | Comma-separated allowed origins. **Note:** Code currently uses `*` wildcard |
| **Connection Pool** |
| `MAX_POOL_SIZE` | int | `100` | ❌ Optional | v0.1.16 | Maximum MongoDB connections in pool |
| `MIN_POOL_SIZE` | int | `10` | ❌ Optional | v0.1.16 | Minimum MongoDB connections maintained in pool |
| `MAX_IDLE_TIME_MS` | int | `30000` | ❌ Optional | v0.1.16 | Maximum idle time for connections (milliseconds) |
| **Pagination** |
| `DEFAULT_PAGE_SIZE` | int | `20` | ❌ Optional | v0.1.16 | Default number of results per page |
| `MAX_PAGE_SIZE` | int | `100` | ❌ Optional | v0.1.16 | Maximum number of results per page (prevents large queries) |
| **Dynamic Filters (v0.1.19+)** |
| `ENUM_FIELDS_STR` | string | `""` (empty) | ❌ Optional | v0.1.19 | Comma-separated fields to display as enum dropdowns |
| `ENUM_MAX_VALUES` | int | `50` | ❌ Optional | v0.1.19 | Maximum distinct values for a field to be treated as enum |
| **Logging** |
| `LOG_LEVEL` | string | `INFO` | ❌ Optional | v0.1.16 | Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL |

**Legend:**
- ✅ Required for production
- 🟡 Recommended to configure
- ❌ Optional (has reasonable defaults)

## Configuration by Category

### 1. MongoDB Configuration

#### Development (Local MongoDB)
```bash
MONGODB_CONNECTION_STRING=mongodb://localhost:27017/
DATABASE_NAME=dev_sessions
COLLECTION_NAME=sessions
```

#### Development (Docker Compose)
```bash
MONGODB_CONNECTION_STRING=mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/
DATABASE_NAME=examples
COLLECTION_NAME=sessions
```

#### Production (MongoDB Atlas)
```bash
MONGODB_CONNECTION_STRING=mongodb+srv://prod_user:secure_password@cluster0.mongodb.net/?retryWrites=true&w=majority
DATABASE_NAME=production_sessions
COLLECTION_NAME=sessions
```

#### Production (Self-Hosted Replica Set)
```bash
MONGODB_CONNECTION_STRING=mongodb://user:password@mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0&authSource=admin
DATABASE_NAME=production_sessions
COLLECTION_NAME=sessions
```

**Important Notes:**
- Always use authentication in production
- Enable SSL/TLS for production connections
- Use read/write concern appropriate for your use case
- MongoDB Atlas connection strings include retry settings by default

### 2. Security Configuration

#### Development
```bash
BACKEND_PASSWORD=dev123
```

#### Staging
```bash
BACKEND_PASSWORD=staging_password_2024
```

#### Production
```bash
BACKEND_PASSWORD=Pr0d_S3cur3_P@ssw0rd_2024!
```

**Password Requirements:**
- Minimum 16 characters recommended
- Mix of uppercase, lowercase, numbers, and symbols
- Different passwords for each environment
- Rotate passwords regularly (every 90 days)
- Never commit passwords to version control

**How Authentication Works:**
1. User enters password in frontend modal
2. Frontend hashes password with SHA-256: `sha256(password)`
3. Hash sent to `POST /api/v1/check_password` for validation
4. Backend compares against `sha256(BACKEND_PASSWORD)`
5. All subsequent requests include `X-Password: <hash>` header
6. Middleware validates header on every request (except `/health` and `/check_password`)

**Security Features:**
- Password never travels as plain text
- Hash stored in memory only (not localStorage)
- Lost on browser close/refresh (re-authentication required)
- Unlimited retry attempts

### 3. CORS Configuration

#### Development (Current Implementation)
The code in `main.py` currently uses:
```python
allow_origins=["*"]  # Allows all origins
allow_credentials=False
```

Configuration in `.env`:
```bash
ALLOWED_ORIGINS_STR=http://localhost:8883,http://127.0.0.1:8883
```

#### Production (Recommended)

**Step 1:** Update `main.py` (lines 107-113):
```python
# Change from:
allow_origins=["*"],
allow_credentials=False,

# To:
allow_origins=settings.allowed_origins,
allow_credentials=True,
```

**Step 2:** Configure `.env`:
```bash
ALLOWED_ORIGINS_STR=https://yourdomain.com,https://app.yourdomain.com,https://www.yourdomain.com
```

**Important:**
- Wildcard `*` is insecure for production
- Always specify exact origins in production
- Include all subdomains that need access
- Use HTTPS origins only

### 4. Connection Pool Configuration

#### Low Traffic (< 100 concurrent users)
```bash
MAX_POOL_SIZE=50
MIN_POOL_SIZE=5
MAX_IDLE_TIME_MS=60000
```

#### Medium Traffic (100-1000 concurrent users)
```bash
MAX_POOL_SIZE=100
MIN_POOL_SIZE=10
MAX_IDLE_TIME_MS=30000
```

#### High Traffic (> 1000 concurrent users)
```bash
MAX_POOL_SIZE=200
MIN_POOL_SIZE=20
MAX_IDLE_TIME_MS=20000
```

**Tuning Guidelines:**
- `MAX_POOL_SIZE`: Based on MongoDB server capacity and expected concurrency
- `MIN_POOL_SIZE`: Set to average concurrent requests to avoid cold starts
- `MAX_IDLE_TIME_MS`: Lower values free resources faster, higher values reduce connection overhead

**Monitoring:**
Check connection pool stats via `/health` endpoint:
```bash
curl http://localhost:8882/health
```

### 5. Pagination Configuration

#### Default (Balanced)
```bash
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=100
```

#### Fast Response Times (Smaller Pages)
```bash
DEFAULT_PAGE_SIZE=10
MAX_PAGE_SIZE=50
```

#### Fewer Round Trips (Larger Pages)
```bash
DEFAULT_PAGE_SIZE=50
MAX_PAGE_SIZE=200
```

**Considerations:**
- Smaller pages: Faster response, more round trips
- Larger pages: Slower response, fewer round trips
- `MAX_PAGE_SIZE` prevents clients from requesting excessive data
- Users can override `DEFAULT_PAGE_SIZE` via API parameter

### 6. Dynamic Filters Configuration (v0.1.19+)

The dynamic filters feature allows configuring which fields display as dropdowns with predefined values instead of text inputs.

#### No Enum Fields (Default)
```bash
ENUM_FIELDS_STR=
ENUM_MAX_VALUES=50
```

All indexed fields display as text inputs.

#### Basic Enum Configuration
```bash
ENUM_FIELDS_STR=metadata.status,metadata.priority
ENUM_MAX_VALUES=50
```

Only `metadata.status` and `metadata.priority` will be checked for enum values.

#### Production Example
```bash
# Configure common metadata fields as enums
ENUM_FIELDS_STR=metadata.status,metadata.priority,metadata.case_type,metadata.category

# Allow up to 100 distinct values for enums
ENUM_MAX_VALUES=100
```

**How It Works:**

1. **Backend queries MongoDB indexes** to find all filterable fields (performance guarantee)
2. **For each field:**
   - If field is NOT in `ENUM_FIELDS_STR` → text input
   - If field IS in `ENUM_FIELDS_STR`:
     - Query distinct values from MongoDB
     - If count ≤ `ENUM_MAX_VALUES` → dropdown with values
     - If count > `ENUM_MAX_VALUES` → fallback to text input
3. **Type detection:**
   - Fields with "date" or "_at" suffix → date picker
   - Boolean fields → True/False dropdown
   - Number fields → number input
   - All others → text input (or enum dropdown if configured)

**Identifying Enum Candidates:**

Connect to MongoDB and analyze distinct values:
```javascript
// In MongoDB shell
db.sessions.distinct("metadata.status").length
// Output: 5 → Good candidate (< 50)

db.sessions.distinct("metadata.customer_id").length
// Output: 15,000 → NOT a good candidate (>> 50)

// List all distinct values for a field
db.sessions.distinct("metadata.status")
// Output: ["active", "completed", "failed", "pending", "cancelled"]
```

**Best Practices:**
- Enum fields should have < 50 distinct values (configurable)
- Only configure fields with stable, predefined value sets
- Status fields, priority levels, categories are good candidates
- User IDs, timestamps, free-text fields are NOT good candidates
- Higher `ENUM_MAX_VALUES` = more database queries = slower `/api/v1/metadata-fields` endpoint

**Performance Impact:**
- Querying distinct values is expensive for large collections
- Only indexed fields are eligible (enforced since v0.1.19)
- Limit `ENUM_FIELDS_STR` to 5-10 fields max
- Adjust `ENUM_MAX_VALUES` based on your data distribution

#### Creating MongoDB Indexes

**Required for v0.1.19+**: Only indexed fields will appear as filterable.

```javascript
// In MongoDB shell or via application startup script

// Always index these
db.sessions.createIndex({"session_id": 1});
db.sessions.createIndex({"created_at": -1});
db.sessions.createIndex({"updated_at": -1});

// Index metadata fields you want to filter
db.sessions.createIndex({"metadata.status": 1});
db.sessions.createIndex({"metadata.priority": 1});
db.sessions.createIndex({"metadata.case_type": 1});
db.sessions.createIndex({"metadata.category": 1});
db.sessions.createIndex({"metadata.assigned_to": 1});

// Compound indexes for common query patterns (optional)
db.sessions.createIndex({"metadata.status": 1, "created_at": -1});
db.sessions.createIndex({"metadata.priority": 1, "updated_at": -1});
```

**Verification:**
```javascript
// List all indexes
db.sessions.getIndexes()

// Check if index exists
db.sessions.getIndexes().filter(idx => idx.name.includes("metadata.status"))
```

### 7. Logging Configuration

#### Development (Maximum Visibility)
```bash
LOG_LEVEL=DEBUG
```

Logs everything including:
- All HTTP requests
- Database queries
- Connection pool operations
- Field type detection
- Enum value retrieval

#### Staging (Moderate Visibility)
```bash
LOG_LEVEL=INFO
```

Logs:
- HTTP requests
- Successful operations
- Important state changes
- Performance warnings

#### Production (Errors Only)
```bash
LOG_LEVEL=WARNING
```

Logs:
- Warnings
- Errors
- Critical issues

**Available Levels (in order):**
1. `DEBUG` - Most verbose
2. `INFO` - Normal operation
3. `WARNING` - Potential issues
4. `ERROR` - Errors that don't crash the app
5. `CRITICAL` - Application-breaking errors

## Environment-Specific Configurations

### Development Environment

**File: `.env.development`**
```bash
# MongoDB
MONGODB_CONNECTION_STRING=mongodb://localhost:27017/
DATABASE_NAME=dev_sessions
COLLECTION_NAME=sessions

# Security (weak password OK for dev)
BACKEND_PASSWORD=dev123

# Server
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8882

# CORS (allow localhost)
ALLOWED_ORIGINS_STR=http://localhost:8883,http://127.0.0.1:8883

# Connection Pool (smaller pool for dev)
MAX_POOL_SIZE=20
MIN_POOL_SIZE=5
MAX_IDLE_TIME_MS=60000

# Pagination
DEFAULT_PAGE_SIZE=10
MAX_PAGE_SIZE=50

# Dynamic Filters (test with few fields)
ENUM_FIELDS_STR=metadata.status
ENUM_MAX_VALUES=20

# Logging (verbose)
LOG_LEVEL=DEBUG
```

### Staging Environment

**File: `.env.staging`**
```bash
# MongoDB
MONGODB_CONNECTION_STRING=mongodb+srv://staging_user:staging_pass@staging-cluster.mongodb.net/
DATABASE_NAME=staging_sessions
COLLECTION_NAME=sessions

# Security
BACKEND_PASSWORD=staging_password_2024

# Server
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8882

# CORS
ALLOWED_ORIGINS_STR=https://staging.yourdomain.com

# Connection Pool
MAX_POOL_SIZE=50
MIN_POOL_SIZE=10
MAX_IDLE_TIME_MS=30000

# Pagination
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=100

# Dynamic Filters
ENUM_FIELDS_STR=metadata.status,metadata.priority,metadata.case_type
ENUM_MAX_VALUES=50

# Logging
LOG_LEVEL=INFO
```

### Production Environment

**File: `.env.production`**
```bash
# MongoDB
MONGODB_CONNECTION_STRING=mongodb+srv://prod_user:${MONGODB_PASSWORD}@prod-cluster.mongodb.net/
DATABASE_NAME=production_sessions
COLLECTION_NAME=sessions

# Security (use secrets management)
BACKEND_PASSWORD=${BACKEND_PASSWORD}

# Server
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8882

# CORS (specific origins only)
ALLOWED_ORIGINS_STR=https://yourdomain.com,https://app.yourdomain.com,https://www.yourdomain.com

# Connection Pool (high capacity)
MAX_POOL_SIZE=200
MIN_POOL_SIZE=20
MAX_IDLE_TIME_MS=20000

# Pagination (optimized)
DEFAULT_PAGE_SIZE=20
MAX_PAGE_SIZE=50

# Dynamic Filters (production fields)
ENUM_FIELDS_STR=metadata.status,metadata.priority,metadata.case_type,metadata.category
ENUM_MAX_VALUES=50

# Logging (errors only)
LOG_LEVEL=WARNING
```

**Production Notes:**
- Use environment variable substitution for secrets (`${VAR}`)
- Never hardcode production passwords
- Use secrets management (AWS Secrets Manager, HashiCorp Vault, etc.)
- Rotate credentials regularly
- Monitor logs for security events

## Troubleshooting

### Issue: "Can't connect to MongoDB"

**Symptoms:** `/health` endpoint returns `"mongodb": "disconnected"`

**Checks:**
1. Verify MongoDB is running:
   ```bash
   # For local MongoDB
   systemctl status mongod

   # For Docker Compose
   docker ps | grep mongodb
   ```

2. Test connection string:
   ```bash
   mongosh "${MONGODB_CONNECTION_STRING}"
   ```

3. Check network connectivity:
   ```bash
   # Test port
   telnet mongodb_host 27017

   # Test DNS resolution
   nslookup cluster.mongodb.net
   ```

4. Verify credentials:
   - Username/password correct?
   - User has read/write permissions on database?
   - IP whitelist configured (MongoDB Atlas)?

**Solution:**
- Update `MONGODB_CONNECTION_STRING` with correct values
- Add IP to Atlas whitelist
- Check firewall rules

### Issue: "Authentication failed" / "Invalid password"

**Symptoms:** Frontend shows "Invalid password" after login attempt

**Checks:**
1. Verify password in `.env`:
   ```bash
   grep BACKEND_PASSWORD .env
   ```

2. Test password hash:
   ```python
   import hashlib
   password = "123456"  # Your password
   print(hashlib.sha256(password.encode()).hexdigest())
   ```

3. Check backend logs:
   ```bash
   # Look for password validation messages
   LOG_LEVEL=DEBUG make dev
   ```

**Solution:**
- Ensure password in `.env` matches what you're typing
- Restart backend after changing `.env`
- Clear browser cache if hash is cached

### Issue: "CORS error in browser console"

**Symptoms:** Browser shows "CORS policy blocked" error

**Checks:**
1. Check CORS configuration in `main.py`:
   ```python
   # Should be:
   allow_origins=settings.allowed_origins

   # Or for development:
   allow_origins=["*"]
   ```

2. Verify frontend URL in `ALLOWED_ORIGINS_STR`:
   ```bash
   grep ALLOWED_ORIGINS_STR .env
   ```

3. Check browser console for actual error:
   - Origin mismatch?
   - Credentials mismatch?
   - Method not allowed?

**Solution:**
- Add frontend URL to `ALLOWED_ORIGINS_STR`
- Restart backend after changes
- For development, use `allow_origins=["*"]` temporarily

### Issue: "No filterable fields appear"

**Symptoms:** `/api/v1/metadata-fields` returns empty or minimal fields

**Cause:** v0.1.19+ only returns indexed fields

**Checks:**
1. List MongoDB indexes:
   ```javascript
   db.sessions.getIndexes()
   ```

2. Verify fields have indexes:
   ```javascript
   // Should see indexes on fields you want to filter
   ```

**Solution:**
Create indexes for fields you want to filter:
```javascript
db.sessions.createIndex({"metadata.status": 1});
db.sessions.createIndex({"metadata.priority": 1});
```

### Issue: "Enum dropdown not showing"

**Symptoms:** Field configured in `ENUM_FIELDS_STR` displays as text input

**Checks:**
1. Verify field is in `ENUM_FIELDS_STR`:
   ```bash
   grep ENUM_FIELDS_STR .env
   ```

2. Check distinct value count:
   ```javascript
   db.sessions.distinct("metadata.status").length
   // Should be <= ENUM_MAX_VALUES
   ```

3. Check backend logs for warnings:
   ```bash
   LOG_LEVEL=DEBUG make dev
   # Look for "exceeds limit" messages
   ```

**Solution:**
- Increase `ENUM_MAX_VALUES` if field has more values
- Or remove field from `ENUM_FIELDS_STR` if it's not suitable for enum
- Verify field has index

### Issue: "Slow performance on search"

**Symptoms:** `/api/v1/sessions/search` takes > 5 seconds

**Checks:**
1. Check MongoDB slow query log
2. Verify indexes exist for filtered fields
3. Check connection pool stats via `/health`
4. Monitor MongoDB server CPU/memory

**Solutions:**
- Create missing indexes
- Increase `MAX_POOL_SIZE`
- Reduce `MAX_PAGE_SIZE`
- Add compound indexes for common query patterns
- Optimize MongoDB server resources

## Security Best Practices

### 1. Password Management

✅ **DO:**
- Use strong passwords (16+ characters, mixed case, numbers, symbols)
- Use different passwords for each environment
- Store passwords in secrets management (production)
- Rotate passwords every 90 days
- Use environment variable substitution: `${SECRET_NAME}`

❌ **DON'T:**
- Hardcode passwords in `.env` files for production
- Commit `.env` files to version control
- Share passwords via email or chat
- Reuse passwords across environments
- Use default passwords (`123456`, `password`, etc.)

### 2. MongoDB Connection Strings

✅ **DO:**
- Use authentication for all environments
- Enable SSL/TLS for production
- Use IP whitelisting (MongoDB Atlas)
- Rotate database credentials regularly
- Use read-only users where possible

❌ **DON'T:**
- Expose connection strings in client-side code
- Use MongoDB without authentication
- Allow connections from `0.0.0.0/0`
- Share admin credentials with application

### 3. CORS Configuration

✅ **DO:**
- Specify exact origins in production
- Use HTTPS origins only
- Update `main.py` to use `settings.allowed_origins`
- Set `allow_credentials=True` if using cookies

❌ **DON'T:**
- Use `allow_origins=["*"]` in production
- Mix HTTP and HTTPS origins
- Allow untrusted origins

### 4. Logging

✅ **DO:**
- Use `LOG_LEVEL=WARNING` or `ERROR` in production
- Sanitize sensitive data before logging
- Rotate log files regularly
- Monitor logs for security events

❌ **DON'T:**
- Log passwords or tokens
- Use `LOG_LEVEL=DEBUG` in production
- Expose detailed errors to clients
- Store logs indefinitely without rotation

### 5. Infrastructure

✅ **DO:**
- Use HTTPS reverse proxy (nginx, caddy)
- Enable rate limiting
- Use environment variable substitution for secrets
- Implement monitoring and alerting
- Regular security updates

❌ **DON'T:**
- Expose backend directly to internet
- Run as root user
- Disable security features for convenience

## Additional Resources

- **Backend README:** `session_viewer/backend/README.md` - API documentation
- **Frontend README:** `session_viewer/frontend/README.md` - UI documentation
- **Main CLAUDE.md:** `/CLAUDE.md` - Project overview
- **Changelog:** `/CHANGELOG.md` - Version history
- **.env.example:** `session_viewer/backend/.env.example` - Configuration template

## Support

For issues or questions:
1. Check backend logs: `LOG_LEVEL=DEBUG make dev`
2. Test endpoints with curl
3. Review this documentation
4. Consult project maintainer

---

**Document Version:** 1.0
**Last Updated:** 2025-10-19
**Compatible With:** Session Viewer v0.1.19+
