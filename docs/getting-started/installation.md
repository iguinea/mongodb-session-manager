# Installation

This guide will help you install MongoDB Session Manager and all its dependencies.

## Requirements

### System Requirements
- **Python**: 3.12.8 or higher
- **MongoDB**: 4.2 or higher (local or remote instance)
- **Package Manager**: UV (recommended) or pip

### Python Dependencies
The library has the following core dependencies:

- `pymongo>=4.16.0` - MongoDB Python driver
- `strands-agents>=1.23.0` - Core Strands Agents SDK
- `strands-agents-tools>=0.2.19` - Strands tools
- `fastapi>=0.128.0` - For FastAPI integration
- `uvloop>=0.22.0` - High-performance event loop
- `boto3>=1.42.0` - AWS SDK (for hooks)

### Optional Dependencies
For AWS integrations (SNS/SQS hooks):
- `python-helpers` - Contains custom_aws.sns and custom_aws.sqs modules

For development:
- `pytest>=7.4.0`
- `pytest-cov>=4.1.0`
- `pytest-mock>=3.11.0`
- `pytest-asyncio>=0.21.0`

## Installation Methods

### Method 1: Using UV (Recommended)

UV is the recommended package manager for this project as it provides faster dependency resolution and better environment management.

#### Install UV
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

#### Install Dependencies
```bash
# Clone the repository
git clone https://github.com/iguinea/mongodb-session-manager.git
cd mongodb-session-manager

# Install all dependencies
uv sync

# Install with AWS integrations
uv add python-helpers
```

#### Verify Installation
```bash
# Run a simple example
uv run python examples/example_calculator_tool.py
```

### Method 2: Using pip

If you prefer to use pip, you can install the library and its dependencies directly.

```bash
# Clone the repository
git clone https://github.com/iguinea/mongodb-session-manager.git
cd mongodb-session-manager

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -e .

# Optional: Install AWS integration dependencies
pip install python-helpers
```

### Method 3: Development Installation

For contributing to the project or running tests:

```bash
# Using UV
uv sync
uv add --dev pytest pytest-cov pytest-mock pytest-asyncio

# Using pip
pip install -e ".[dev]"
```

## MongoDB Setup

### Local MongoDB Installation

#### macOS
```bash
# Using Homebrew
brew tap mongodb/brew
brew install mongodb-community

# Start MongoDB
brew services start mongodb-community
```

#### Ubuntu/Debian
```bash
# Import MongoDB public GPG key
wget -qO - https://www.mongodb.org/static/pgp/server-7.0.asc | sudo apt-key add -

# Add MongoDB repository
echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

# Install MongoDB
sudo apt-get update
sudo apt-get install -y mongodb-org

# Start MongoDB
sudo systemctl start mongod
sudo systemctl enable mongod
```

#### Windows
Download and install from [MongoDB Download Center](https://www.mongodb.com/try/download/community).

### Docker MongoDB

For development and testing, Docker is often the easiest option:

```bash
# Run MongoDB in Docker
docker run -d \
  --name mongodb-session-manager \
  -p 27017:27017 \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=password \
  mongo:7.0

# Connection string for Docker MongoDB
export MONGODB_URI="mongodb://admin:password@localhost:27017/"
```

### MongoDB Atlas (Cloud)

For production use, MongoDB Atlas is recommended:

1. Create a free account at [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a cluster
3. Set up database access (username/password)
4. Whitelist your IP address
5. Get your connection string

```python
# Example Atlas connection string
connection_string = "mongodb+srv://username:password@cluster0.mongodb.net/mydb?retryWrites=true&w=majority"
```

## Verifying Installation

### Test MongoDB Connection

Create a simple test script to verify your setup:

```python
# test_installation.py
from pymongo import MongoClient

def test_mongodb_connection():
    """Test MongoDB connection."""
    try:
        # Replace with your MongoDB URI
        client = MongoClient("mongodb://localhost:27017/")

        # Test connection
        client.admin.command('ping')
        print("✓ MongoDB connection successful!")

        # List databases
        dbs = client.list_database_names()
        print(f"✓ Available databases: {dbs}")

        client.close()
        return True

    except Exception as e:
        print(f"✗ MongoDB connection failed: {e}")
        return False

if __name__ == "__main__":
    test_mongodb_connection()
```

Run the test:

```bash
# Using UV
uv run python test_installation.py

# Using regular Python
python test_installation.py
```

### Test Session Manager

```python
# test_session_manager.py
from mongodb_session_manager import create_mongodb_session_manager
from strands import Agent

def test_session_manager():
    """Test MongoDB Session Manager setup."""
    try:
        # Create session manager
        session_manager = create_mongodb_session_manager(
            session_id="test-session",
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions"
        )

        print("✓ Session manager created successfully!")

        # Create a simple agent
        agent = Agent(
            model="claude-3-sonnet",
            agent_id="test-agent",
            session_manager=session_manager,
            system_prompt="You are a test assistant."
        )

        print("✓ Agent created with session manager!")

        # Test a simple interaction
        response = agent("Hello, this is a test.")
        print(f"✓ Agent response: {response[:50]}...")

        # Clean up
        session_manager.close()
        print("✓ All tests passed!")

        return True

    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

if __name__ == "__main__":
    test_session_manager()
```

### Run Example Scripts

The repository includes several example scripts to test different features:

```bash
# Basic calculator tool example
uv run python examples/example_calculator_tool.py

# FastAPI integration example
uv run python examples/example_fastapi.py

# Performance benchmarks
uv run python examples/example_performance.py

# Async streaming example
uv run python examples/example_stream_async.py
```

## AWS Integration Setup (Optional)

If you plan to use AWS SNS/SQS hooks:

### Install AWS Dependencies

```bash
# Using UV
uv add python-helpers

# Using pip
pip install python-helpers
```

### Configure AWS Credentials

```bash
# Install AWS CLI
pip install awscli

# Configure credentials
aws configure
```

You'll need to provide:
- AWS Access Key ID
- AWS Secret Access Key
- Default region (e.g., eu-west-1)
- Default output format (json)

### Verify AWS Integration

```python
from mongodb_session_manager import (
    is_feedback_sns_hook_available,
    is_metadata_sqs_hook_available
)

print(f"SNS Hook Available: {is_feedback_sns_hook_available()}")
print(f"SQS Hook Available: {is_metadata_sqs_hook_available()}")
```

## Troubleshooting

### Common Issues

#### Issue: "No module named 'mongodb_session_manager'"

**Solution**: Make sure you've installed the package:
```bash
uv sync  # or pip install -e .
```

#### Issue: "Connection refused" when connecting to MongoDB

**Solutions**:
1. Check if MongoDB is running: `systemctl status mongod` (Linux) or `brew services list` (macOS)
2. Verify the connection string is correct
3. Check firewall settings
4. For Atlas, ensure your IP is whitelisted

#### Issue: "pymongo.errors.ServerSelectionTimeoutError"

**Solutions**:
1. Increase timeout in connection string:
   ```python
   connection_string = "mongodb://localhost:27017/?serverSelectionTimeoutMS=10000"
   ```
2. Check MongoDB is accessible at the specified host/port
3. Verify network connectivity

#### Issue: "custom_aws module not found"

**Solution**: Install python-helpers package:
```bash
uv add python-helpers
```

#### Issue: UV command not found

**Solution**: Add UV to your PATH or reinstall:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # or ~/.zshrc
```

## Next Steps

Now that you have MongoDB Session Manager installed:

1. [Follow the Quickstart Guide](quickstart.md) to create your first session
2. [Learn Basic Concepts](basic-concepts.md) to understand how it works
3. [Explore Examples](../examples/basic-usage.md) for common use cases

## Environment Variables

For production deployments, consider using environment variables:

```bash
# .env file
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DATABASE=production_db
MONGODB_COLLECTION=agent_sessions

# AWS Configuration (if using hooks)
AWS_REGION=eu-west-1
SNS_TOPIC_ARN_GOOD=arn:aws:sns:eu-west-1:123456789:feedback-good
SNS_TOPIC_ARN_BAD=arn:aws:sns:eu-west-1:123456789:feedback-bad
SQS_QUEUE_URL=https://sqs.eu-west-1.amazonaws.com/123456789/metadata-sync
```

Load them in your application:

```python
import os
from dotenv import load_dotenv

load_dotenv()

connection_string = os.getenv("MONGODB_URI")
database_name = os.getenv("MONGODB_DATABASE")
collection_name = os.getenv("MONGODB_COLLECTION")
```

## Support

If you encounter any issues during installation:

- Check the [FAQ](../faq.md) for common questions
- Open an issue on [GitHub](https://github.com/iguinea/mongodb-session-manager/issues)
- Contact: iguinea@gmail.com
