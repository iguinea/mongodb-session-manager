# Development Environment Setup

This guide will help you set up your development environment for contributing to the MongoDB Session Manager project.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Getting the Code](#getting-the-code)
- [Installing UV](#installing-uv)
- [Installing Dependencies](#installing-dependencies)
- [MongoDB Setup](#mongodb-setup)
- [Running Example Scripts](#running-example-scripts)
- [IDE Configuration](#ide-configuration)
- [Environment Variables](#environment-variables)
- [Verifying Installation](#verifying-installation)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before you begin, ensure you have the following installed on your system:

### Required Software

1. **Python 3.13+**
   ```bash
   # Check your Python version
   python --version
   # or
   python3 --version
   ```

   If you need to install Python:
   - **macOS**: `brew install python@3.13`
   - **Ubuntu/Debian**: `sudo apt-get install python3.13`
   - **Windows**: Download from [python.org](https://www.python.org/downloads/)

2. **MongoDB**
   - MongoDB 4.4 or higher
   - You can use MongoDB Atlas (cloud), local installation, or Docker

3. **Git**
   ```bash
   # Check if Git is installed
   git --version
   ```

### Optional Software

- **Docker & Docker Compose**: For running MongoDB locally
- **MongoDB Compass**: GUI for MongoDB (helpful for debugging)

## Getting the Code

1. **Fork the Repository** (if contributing)

   Go to https://github.com/iguinea/mongodb-session-manager and click "Fork"

2. **Clone the Repository**
   ```bash
   # If you forked it
   git clone https://github.com/YOUR_USERNAME/mongodb-session-manager.git

   # Or clone the original
   git clone https://github.com/iguinea/mongodb-session-manager.git

   cd mongodb-session-manager
   ```

3. **Create a Development Branch**
   ```bash
   git checkout -b feature/my-new-feature
   ```

## Installing UV

UV is a fast Python package and project manager. This project uses UV for all dependency management.

### Installation

**macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Using pip:**
```bash
pip install uv
```

### Verify Installation

```bash
uv --version
```

You should see something like `uv 0.x.x`.

### UV Quick Reference

UV replaces many common Python commands:

```bash
# Install dependencies
uv sync                    # Instead of: pip install -r requirements.txt

# Add a new dependency
uv add requests            # Instead of: pip install requests

# Add a dev dependency
uv add --dev pytest        # Instead of: pip install pytest

# Run Python scripts
uv run python script.py    # Instead of: python script.py

# Run tests
uv run pytest tests/       # Instead of: pytest tests/
```

## Installing Dependencies

Once UV is installed, install the project dependencies:

```bash
# Install all dependencies (including dev dependencies)
uv sync

# This creates a virtual environment and installs:
# - Core dependencies (pymongo, strands-agents, etc.)
# - Development dependencies (pytest, ruff, etc.)
# - The project itself in editable mode
```

The `uv sync` command will:
1. Create a virtual environment in `.venv/`
2. Install all dependencies from `pyproject.toml`
3. Lock the exact versions in `uv.lock`
4. Install the project in development mode

### Understanding Dependencies

**Core Dependencies** (required for the library):
- `pymongo>=4.13.2`: MongoDB Python driver
- `strands-agents>=1.0.1`: Strands Agents SDK
- `strands-agents-tools>=0.2.1`: Strands tools
- `fastapi>=0.116.1`: For FastAPI integration
- `uvloop>=0.21.0`: High-performance event loop
- `python-helpers`: Custom AWS integrations (from git repo)

**Development Dependencies** (for testing and development):
- `pytest>=7.4.0`: Testing framework
- `pytest-cov>=4.1.0`: Coverage reporting
- `pytest-mock>=3.11.0`: Mocking utilities
- `pytest-asyncio>=0.21.0`: Async test support

## MongoDB Setup

You need a MongoDB instance for development and testing. Choose one of the following options:

### Option 1: Docker (Recommended for Development)

Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  mongodb:
    image: mongo:7.0
    container_name: mongodb-dev
    ports:
      - "27017:27017"
    environment:
      MONGO_INITDB_ROOT_USERNAME: admin
      MONGO_INITDB_ROOT_PASSWORD: password
      MONGO_INITDB_DATABASE: virtualagents
    volumes:
      - mongodb_data:/data/db

volumes:
  mongodb_data:
```

Start MongoDB:
```bash
docker-compose up -d
```

Connection string: `mongodb://admin:password@localhost:27017/`

### Option 2: Local MongoDB Installation

**macOS:**
```bash
brew tap mongodb/brew
brew install mongodb-community@7.0
brew services start mongodb-community@7.0
```

**Ubuntu/Debian:**
```bash
# Install MongoDB 7.0
wget -qO - https://www.mongodb.org/static/pgp/server-7.0.asc | sudo apt-key add -
echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt-get update
sudo apt-get install -y mongodb-org
sudo systemctl start mongod
```

Connection string: `mongodb://localhost:27017/`

### Option 3: MongoDB Atlas (Cloud)

1. Sign up at [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a free cluster
3. Get your connection string from the Atlas UI
4. Whitelist your IP address

Connection string: `mongodb+srv://username:password@cluster.mongodb.net/`

### Verify MongoDB Connection

Test your MongoDB connection:

```bash
# Using mongosh (MongoDB shell)
mongosh "mongodb://admin:password@localhost:27017/"

# Or use Python
uv run python -c "from pymongo import MongoClient; client = MongoClient('mongodb://admin:password@localhost:27017/'); print(client.server_info())"
```

## Running Example Scripts

The project includes several example scripts to test functionality:

### Basic Examples

```bash
# Calculator tool example
uv run python examples/example_calculator_tool.py

# FastAPI integration
uv run python examples/example_fastapi.py

# Performance benchmarks
uv run python examples/example_performance.py

# Async streaming
uv run python examples/example_stream_async.py
```

### Metadata Examples

```bash
# Metadata management
uv run python examples/example_metadata_update.py

# Metadata tool for agents
uv run python examples/example_metadata_tool.py

# Direct tool usage
uv run python examples/example_metadata_tool_direct.py

# Metadata hooks
uv run python examples/example_metadata_hook.py
```

### Feedback Examples

```bash
# Feedback hooks
uv run python examples/example_feedback_hook.py
```

### Agent Configuration Examples

```bash
# Agent configuration persistence
uv run python examples/example_agent_config.py
```

### Interactive Playground

The project includes a web-based chat interface:

```bash
# Terminal 1: Start backend (port 8880)
cd playground/chat
make backend-fastapi-streaming

# Terminal 2: Start frontend (port 8881)
cd playground/chat
make frontend

# Open browser to: http://localhost:8881/chat.html
```

## IDE Configuration

### Visual Studio Code

1. **Install Python Extension**
   - Install "Python" extension by Microsoft

2. **Configure Settings** (`.vscode/settings.json`):
   ```json
   {
     "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
     "python.analysis.typeCheckingMode": "basic",
     "python.linting.enabled": true,
     "python.linting.ruffEnabled": true,
     "python.formatting.provider": "none",
     "[python]": {
       "editor.defaultFormatter": "charliermarsh.ruff",
       "editor.formatOnSave": true,
       "editor.codeActionsOnSave": {
         "source.fixAll": true,
         "source.organizeImports": true
       }
     },
     "files.exclude": {
       "**/__pycache__": true,
       "**/*.pyc": true,
       ".pytest_cache": true
     }
   }
   ```

3. **Recommended Extensions**:
   - Python (ms-python.python)
   - Ruff (charliermarsh.ruff)
   - MongoDB for VS Code (mongodb.mongodb-vscode)
   - GitLens (eamodio.gitlens)

4. **Launch Configuration** (`.vscode/launch.json`):
   ```json
   {
     "version": "0.2.0",
     "configurations": [
       {
         "name": "Python: Current File",
         "type": "python",
         "request": "launch",
         "program": "${file}",
         "console": "integratedTerminal",
         "justMyCode": true,
         "env": {
           "MONGODB_URI": "mongodb://admin:password@localhost:27017/"
         }
       },
       {
         "name": "Python: FastAPI Example",
         "type": "python",
         "request": "launch",
         "module": "uvicorn",
         "args": [
           "examples.example_fastapi:app",
           "--reload",
           "--port",
           "8000"
         ],
         "console": "integratedTerminal"
       }
     ]
   }
   ```

### PyCharm

1. **Configure Python Interpreter**:
   - File > Settings > Project > Python Interpreter
   - Click "Add Interpreter" > "Existing"
   - Select `.venv/bin/python`

2. **Configure Ruff**:
   - File > Settings > Tools > External Tools
   - Add new tool:
     - Name: Ruff Format
     - Program: `$ProjectFileDir$/.venv/bin/ruff`
     - Arguments: `format $FilePath$`
     - Working directory: `$ProjectFileDir$`

3. **Enable pytest**:
   - File > Settings > Tools > Python Integrated Tools
   - Set "Default test runner" to "pytest"

## Environment Variables

The project uses environment variables for configuration. Create a `.env` file in the project root:

```bash
# MongoDB Configuration
MONGODB_URI=mongodb://admin:password@localhost:27017/
MONGODB_DATABASE=virtualagents
MONGODB_COLLECTION=agent_sessions

# AWS Configuration (optional - only needed for SNS/SQS hooks)
AWS_REGION=eu-west-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key

# SNS Topics (optional)
SNS_TOPIC_ARN_GOOD=arn:aws:sns:eu-west-1:123456789:feedback-good
SNS_TOPIC_ARN_BAD=arn:aws:sns:eu-west-1:123456789:feedback-bad
SNS_TOPIC_ARN_NEUTRAL=arn:aws:sns:eu-west-1:123456789:feedback-neutral

# SQS Queue (optional)
SQS_QUEUE_URL=https://sqs.eu-west-1.amazonaws.com/123456789/metadata-updates

# Anthropic API Key (for examples)
ANTHROPIC_API_KEY=your_api_key

# Development Settings
LOG_LEVEL=DEBUG
PYTHONUNBUFFERED=1
```

**Security Note**: Never commit `.env` file to version control. It's already in `.gitignore`.

### Loading Environment Variables

The examples use Python's `os.getenv()` to read environment variables:

```python
import os

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "virtualagents")
```

For automatic loading, you can use `python-dotenv`:

```bash
uv add --dev python-dotenv
```

Then in your code:

```python
from dotenv import load_dotenv
load_dotenv()  # Loads .env file
```

## Verifying Installation

Run these commands to verify everything is set up correctly:

### 1. Check Python and UV

```bash
python --version
uv --version
```

### 2. Check Dependencies

```bash
# List installed packages
uv pip list

# Should include:
# - pymongo
# - strands-agents
# - fastapi
# - pytest
```

### 3. Run Import Test

```bash
uv run python -c "
from mongodb_session_manager import (
    MongoDBSessionManager,
    MongoDBSessionRepository,
    MongoDBConnectionPool,
    MongoDBSessionManagerFactory,
    create_mongodb_session_manager,
    is_feedback_sns_hook_available,
    is_metadata_sqs_hook_available
)
print('✓ All imports successful')
print(f'✓ SNS Hook Available: {is_feedback_sns_hook_available()}')
print(f'✓ SQS Hook Available: {is_metadata_sqs_hook_available()}')
"
```

### 4. Test MongoDB Connection

```bash
uv run python -c "
from pymongo import MongoClient
client = MongoClient('mongodb://admin:password@localhost:27017/')
print('✓ MongoDB connection successful')
print(f'✓ Server version: {client.server_info()[\"version\"]}')
client.close()
"
```

### 5. Run a Simple Test

Create a test file `test_setup.py`:

```python
from mongodb_session_manager import create_mongodb_session_manager

# Create session manager
manager = create_mongodb_session_manager(
    session_id="test-setup",
    connection_string="mongodb://admin:password@localhost:27017/",
    database_name="test_db"
)

# Test basic operations
manager.update_metadata({"test": "setup_complete"})
metadata = manager.get_metadata()
print(f"✓ Metadata test passed: {metadata}")

manager.close()
print("✓ Setup verification complete!")
```

Run it:
```bash
uv run python test_setup.py
```

## Troubleshooting

### UV Issues

**Problem**: `uv: command not found`

**Solution**:
```bash
# Ensure UV's bin directory is in PATH
export PATH="$HOME/.cargo/bin:$PATH"

# Or reinstall UV
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Problem**: `uv sync` fails with dependency conflicts

**Solution**:
```bash
# Clear UV cache
uv cache clean

# Remove lock file and try again
rm uv.lock
uv sync
```

### MongoDB Issues

**Problem**: Cannot connect to MongoDB

**Solution 1** - Check if MongoDB is running:
```bash
# Docker
docker ps | grep mongodb

# Local installation (macOS)
brew services list

# Local installation (Linux)
sudo systemctl status mongod
```

**Solution 2** - Check connection string format:
```python
# Correct formats:
"mongodb://localhost:27017/"  # No auth
"mongodb://user:pass@localhost:27017/"  # With auth
"mongodb+srv://user:pass@cluster.mongodb.net/"  # Atlas
```

**Problem**: Authentication failed

**Solution**:
```bash
# Connect to MongoDB and create user
mongosh
use admin
db.createUser({
  user: "admin",
  pwd: "password",
  roles: ["root"]
})
```

### Python Version Issues

**Problem**: Project requires Python 3.13+

**Solution**: Use pyenv to manage Python versions:
```bash
# Install pyenv
curl https://pyenv.run | bash

# Install Python 3.13
pyenv install 3.13.0

# Set as local version
pyenv local 3.13.0
```

### Import Issues

**Problem**: `ModuleNotFoundError: No module named 'mongodb_session_manager'`

**Solution**:
```bash
# Ensure you're using UV to run Python
uv run python your_script.py

# Or activate the virtual environment
source .venv/bin/activate  # Unix
.venv\Scripts\activate     # Windows

python your_script.py
```

### AWS Hook Issues

**Problem**: AWS hooks not available

**Solution**: The AWS hooks require the `python-helpers` package which is installed from Git:
```bash
# Check if python-helpers is installed
uv pip list | grep python-helpers

# If not, ensure pyproject.toml has:
# [tool.uv.sources]
# python-helpers = { git = "https://github.com/iguinea/python-helpers", rev = "latest" }

# Then reinstall
uv sync --reinstall-package python-helpers
```

### Example Script Issues

**Problem**: Examples fail with "No Anthropic API key"

**Solution**: Set your Anthropic API key:
```bash
export ANTHROPIC_API_KEY=your_api_key

# Or create .env file with:
# ANTHROPIC_API_KEY=your_api_key
```

**Problem**: FastAPI examples fail with port already in use

**Solution**:
```bash
# Find and kill process using the port
lsof -ti:8000 | xargs kill -9

# Or use a different port
uv run uvicorn examples.example_fastapi:app --port 8001
```

## Next Steps

Now that your development environment is set up:

1. **Read the Contributing Guide**: See [contributing.md](contributing.md) for development workflow
2. **Run the Tests**: See [testing.md](testing.md) for testing guidelines
3. **Explore Examples**: Run the example scripts to understand the library
4. **Start Coding**: Create your feature branch and start developing!

## Additional Resources

- **UV Documentation**: https://github.com/astral-sh/uv
- **MongoDB Documentation**: https://docs.mongodb.com/
- **Strands Agents**: https://github.com/strands-ai/strands-agents
- **Python 3.13 Documentation**: https://docs.python.org/3.13/

## Getting Help

If you encounter issues:

1. Check the [FAQ](../faq.md)
2. Search existing [GitHub Issues](https://github.com/iguinea/mongodb-session-manager/issues)
3. Ask in GitHub Discussions
4. Contact the maintainers

Happy coding!
