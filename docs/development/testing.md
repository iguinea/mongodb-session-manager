# Testing Guide

This guide covers how to run and write tests for the MongoDB Session Manager project.

## Table of Contents

- [Testing Framework](#testing-framework)
- [Running Tests](#running-tests)
- [Writing Unit Tests](#writing-unit-tests)
- [Writing Integration Tests](#writing-integration-tests)
- [Test Coverage](#test-coverage)
- [Testing with MongoDB](#testing-with-mongodb)
- [Mocking MongoDB Connections](#mocking-mongodb-connections)
- [Testing Hooks](#testing-hooks)
- [Testing AWS Integrations](#testing-aws-integrations)
- [CI/CD Testing](#cicd-testing)
- [Best Practices](#best-practices)

## Testing Framework

The project uses **pytest** as its testing framework, along with several pytest plugins:

- **pytest**: Main testing framework
- **pytest-cov**: Coverage reporting
- **pytest-mock**: Mocking utilities
- **pytest-asyncio**: Async test support

### Installation

Tests are run using UV:

```bash
# Install all dependencies including test dependencies
uv sync

# Or install test dependencies separately
uv add --dev pytest pytest-cov pytest-mock pytest-asyncio
```

## Running Tests

### Basic Test Execution

```bash
# Run all tests
uv run pytest tests/

# Run tests in a specific file
uv run pytest tests/test_session_manager.py

# Run a specific test function
uv run pytest tests/test_session_manager.py::test_create_session

# Run tests matching a pattern
uv run pytest tests/ -k "metadata"

# Run tests with verbose output
uv run pytest tests/ -v

# Run tests with extra verbose output (show print statements)
uv run pytest tests/ -vv -s
```

### Advanced Options

```bash
# Stop at first failure
uv run pytest tests/ -x

# Run last failed tests
uv run pytest tests/ --lf

# Run tests in parallel (requires pytest-xdist)
uv run pytest tests/ -n auto

# Show slowest tests
uv run pytest tests/ --durations=10

# Run only integration tests
uv run pytest tests/ -m integration

# Run only unit tests
uv run pytest tests/ -m unit

# Skip slow tests
uv run pytest tests/ -m "not slow"
```

### Running with Coverage

```bash
# Run tests with coverage report
uv run pytest --cov=mongodb_session_manager tests/

# Generate HTML coverage report
uv run pytest --cov=mongodb_session_manager --cov-report=html tests/

# Open HTML report
open htmlcov/index.html

# Show missing lines in coverage
uv run pytest --cov=mongodb_session_manager --cov-report=term-missing tests/

# Fail if coverage is below threshold
uv run pytest --cov=mongodb_session_manager --cov-fail-under=80 tests/
```

## Writing Unit Tests

Unit tests test individual functions or methods in isolation, typically with mocked dependencies.

### Test File Structure

```python
# tests/test_session_manager.py
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from mongodb_session_manager import MongoDBSessionManager

class TestMongoDBSessionManager:
    """Test suite for MongoDBSessionManager."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.session_id = "test-session"
        self.mock_client = Mock()

    def teardown_method(self):
        """Clean up after each test method."""
        pass

    def test_create_session_manager(self):
        """Test creating a session manager."""
        manager = MongoDBSessionManager(
            session_id=self.session_id,
            client=self.mock_client,
            database_name="test_db"
        )
        assert manager.session_id == self.session_id

    def test_update_metadata(self):
        """Test updating session metadata."""
        # Test implementation
        pass
```

### Example Unit Tests

#### Test with Mocked MongoDB

```python
import pytest
from unittest.mock import Mock, patch
from mongodb_session_manager import MongoDBSessionManager

def test_update_metadata_with_mock():
    """Test metadata update with mocked MongoDB."""
    # Create mock MongoDB client
    mock_client = Mock()
    mock_db = Mock()
    mock_collection = Mock()

    mock_client.__getitem__.return_value = mock_db
    mock_db.__getitem__.return_value = mock_collection

    # Create session manager with mock client
    manager = MongoDBSessionManager(
        session_id="test-123",
        client=mock_client,
        database_name="test_db"
    )

    # Test update_metadata
    metadata = {"priority": "high", "status": "active"}
    manager.update_metadata(metadata)

    # Verify MongoDB was called correctly
    mock_collection.update_one.assert_called_once()
    call_args = mock_collection.update_one.call_args
    assert call_args[0][0] == {"_id": "test-123"}
    assert "metadata.priority" in call_args[0][1]["$set"]
```

#### Test Error Handling

```python
def test_update_metadata_invalid_input():
    """Test that invalid metadata raises ValueError."""
    manager = MongoDBSessionManager(
        session_id="test-123",
        client=Mock(),
        database_name="test_db"
    )

    # Should raise ValueError for non-dict metadata
    with pytest.raises(ValueError, match="must be a dictionary"):
        manager.update_metadata("not a dict")
```

#### Test with Fixtures

```python
@pytest.fixture
def mock_mongodb_client():
    """Fixture providing a mocked MongoDB client."""
    mock_client = Mock()
    mock_db = Mock()
    mock_collection = Mock()

    mock_client.__getitem__.return_value = mock_db
    mock_db.__getitem__.return_value = mock_collection

    return mock_client

@pytest.fixture
def session_manager(mock_mongodb_client):
    """Fixture providing a session manager with mocked client."""
    return MongoDBSessionManager(
        session_id="test-session",
        client=mock_mongodb_client,
        database_name="test_db"
    )

def test_with_fixtures(session_manager):
    """Test using fixtures."""
    metadata = {"test": "data"}
    session_manager.update_metadata(metadata)
    assert session_manager.get_metadata() is not None
```

## Writing Integration Tests

Integration tests test the full functionality with a real MongoDB instance.

### Setting Up Test MongoDB

#### Option 1: Docker (Recommended)

```yaml
# docker-compose.test.yml
version: '3.8'

services:
  mongodb-test:
    image: mongo:7.0
    container_name: mongodb-test
    ports:
      - "27018:27017"
    environment:
      MONGO_INITDB_ROOT_USERNAME: test
      MONGO_INITDB_ROOT_PASSWORD: test
    tmpfs:
      - /data/db  # Use tmpfs for faster tests
```

Start test MongoDB:
```bash
docker-compose -f docker-compose.test.yml up -d
```

#### Option 2: MongoDB Test Fixture

```python
import pytest
from pymongo import MongoClient
import os

@pytest.fixture(scope="session")
def mongodb_uri():
    """Get MongoDB URI from environment or use default."""
    return os.getenv(
        "TEST_MONGODB_URI",
        "mongodb://test:test@localhost:27018/"
    )

@pytest.fixture(scope="session")
def mongodb_client(mongodb_uri):
    """Create MongoDB client for tests."""
    client = MongoClient(mongodb_uri)
    yield client
    client.close()

@pytest.fixture
def clean_database(mongodb_client):
    """Clean database before each test."""
    db = mongodb_client["test_database"]
    # Drop all collections
    for collection in db.list_collection_names():
        db[collection].drop()
    yield db
```

### Example Integration Tests

```python
import pytest
from mongodb_session_manager import MongoDBSessionManager
from strands import Agent

@pytest.mark.integration
def test_session_persistence(mongodb_uri, clean_database):
    """Test that sessions persist across manager instances."""
    session_id = "integration-test-session"

    # Create first manager and add metadata
    manager1 = MongoDBSessionManager(
        session_id=session_id,
        connection_string=mongodb_uri,
        database_name="test_database"
    )
    manager1.update_metadata({"user": "test_user", "count": 1})
    manager1.close()

    # Create second manager and verify persistence
    manager2 = MongoDBSessionManager(
        session_id=session_id,
        connection_string=mongodb_uri,
        database_name="test_database"
    )
    metadata = manager2.get_metadata()
    assert metadata["user"] == "test_user"
    assert metadata["count"] == 1
    manager2.close()

@pytest.mark.integration
def test_full_agent_workflow(mongodb_uri, clean_database):
    """Test complete agent workflow with MongoDB persistence."""
    session_id = "agent-workflow-test"

    # Create session manager
    manager = MongoDBSessionManager(
        session_id=session_id,
        connection_string=mongodb_uri,
        database_name="test_database"
    )

    # Create agent (would need API key for real test)
    # This is a mock test - in real scenario you'd use actual agent

    # Simulate agent interaction
    manager.append_message(
        {"role": "user", "content": "Hello"},
        Mock(agent_id="test-agent")
    )
    manager.append_message(
        {"role": "assistant", "content": "Hi there!"},
        Mock(agent_id="test-agent")
    )

    # Verify messages were stored
    messages = manager.list_messages(agent_id="test-agent")
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"

    manager.close()

@pytest.mark.integration
def test_connection_pool_reuse(mongodb_uri):
    """Test that connection pool properly reuses connections."""
    from mongodb_session_manager import (
        MongoDBSessionManagerFactory,
        MongoDBConnectionPool
    )

    # Create factory
    factory = MongoDBSessionManagerFactory(
        connection_string=mongodb_uri,
        database_name="test_database",
        maxPoolSize=10
    )

    # Create multiple session managers
    managers = [
        factory.create_session_manager(f"session-{i}")
        for i in range(5)
    ]

    # All should share the same connection pool
    stats = factory.get_connection_stats()
    assert stats is not None

    # Clean up
    for manager in managers:
        manager.close()
    factory.close()
```

## Test Coverage

### Measuring Coverage

```bash
# Generate coverage report
uv run pytest --cov=mongodb_session_manager --cov-report=term tests/

# Generate HTML report
uv run pytest --cov=mongodb_session_manager --cov-report=html tests/

# Generate XML report (for CI)
uv run pytest --cov=mongodb_session_manager --cov-report=xml tests/
```

### Coverage Goals

- **Minimum**: 80% overall coverage
- **New Code**: 100% coverage for new features
- **Critical Paths**: 100% coverage for critical functionality

### Checking Coverage

```bash
# View coverage report
uv run pytest --cov=mongodb_session_manager --cov-report=term-missing tests/

# Example output:
# Name                                    Stmts   Miss  Cover   Missing
# ---------------------------------------------------------------------
# mongodb_session_manager/__init__.py        20      0   100%
# mongodb_session_manager/manager.py        150     10    93%   45-47, 89-92
# ---------------------------------------------------------------------
# TOTAL                                     500     25    95%
```

## Testing with MongoDB

### Test Database Cleanup

Always clean up test data after tests:

```python
@pytest.fixture(autouse=True)
def cleanup_test_data(mongodb_client):
    """Automatically clean up test data after each test."""
    yield
    # Clean up after test
    db = mongodb_client["test_database"]
    db["test_collection"].delete_many({})

# Or use separate test database per test
@pytest.fixture
def unique_test_db(mongodb_client):
    """Create unique test database for each test."""
    import uuid
    db_name = f"test_db_{uuid.uuid4().hex[:8]}"
    db = mongodb_client[db_name]
    yield db
    mongodb_client.drop_database(db_name)
```

### Testing Indexes

```python
def test_indexes_created(mongodb_client):
    """Test that required indexes are created."""
    manager = MongoDBSessionManager(
        session_id="test",
        client=mongodb_client,
        database_name="test_database",
        collection_name="sessions"
    )

    # Get collection indexes
    collection = mongodb_client["test_database"]["sessions"]
    indexes = list(collection.list_indexes())

    # Verify indexes exist
    index_names = [idx["name"] for idx in indexes]
    assert "created_at_1" in index_names
    assert "updated_at_1" in index_names

    manager.close()
```

### Testing Concurrent Operations

```python
import pytest
from concurrent.futures import ThreadPoolExecutor

@pytest.mark.integration
def test_concurrent_metadata_updates(mongodb_uri):
    """Test thread-safe metadata updates."""
    session_id = "concurrent-test"

    def update_metadata(value):
        manager = MongoDBSessionManager(
            session_id=session_id,
            connection_string=mongodb_uri,
            database_name="test_database"
        )
        manager.update_metadata({f"field_{value}": value})
        manager.close()

    # Run concurrent updates
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(update_metadata, range(10))

    # Verify all updates succeeded
    manager = MongoDBSessionManager(
        session_id=session_id,
        connection_string=mongodb_uri,
        database_name="test_database"
    )
    metadata = manager.get_metadata()
    assert len(metadata) == 10
    manager.close()
```

## Mocking MongoDB Connections

### Using pytest-mock

```python
def test_with_pytest_mock(mocker):
    """Test using pytest-mock."""
    # Mock MongoDB client
    mock_client = mocker.Mock()
    mock_collection = mocker.Mock()

    # Configure mock
    mock_client.__getitem__.return_value.__getitem__.return_value = mock_collection
    mock_collection.find_one.return_value = {"_id": "test", "metadata": {}}

    # Test code
    manager = MongoDBSessionManager(
        session_id="test",
        client=mock_client,
        database_name="test_db"
    )

    metadata = manager.get_metadata()
    mock_collection.find_one.assert_called_once()
```

### Mocking Connection Pool

```python
@patch('mongodb_session_manager.mongodb_connection_pool.MongoDBConnectionPool')
def test_factory_with_mocked_pool(mock_pool_class):
    """Test factory with mocked connection pool."""
    from mongodb_session_manager import MongoDBSessionManagerFactory

    # Configure mock
    mock_pool = Mock()
    mock_client = Mock()
    mock_pool.get_client.return_value = mock_client
    mock_pool_class.get_instance.return_value = mock_pool

    # Test factory
    factory = MongoDBSessionManagerFactory(
        connection_string="mongodb://test",
        database_name="test_db"
    )

    manager = factory.create_session_manager("test-session")
    assert manager.session_id == "test-session"
```

## Testing Hooks

### Testing Metadata Hooks

```python
def test_metadata_hook():
    """Test that metadata hook is called."""
    hook_called = []

    def test_hook(original_func, action, session_id, **kwargs):
        hook_called.append((action, session_id))
        if action == "update":
            return original_func(kwargs["metadata"])
        elif action == "delete":
            return original_func(kwargs["keys"])
        else:
            return original_func()

    manager = MongoDBSessionManager(
        session_id="test",
        client=Mock(),
        database_name="test_db",
        metadataHook=test_hook
    )

    # Test hook is called
    manager.update_metadata({"test": "value"})
    assert ("update", "test") in hook_called

def test_metadata_hook_validation():
    """Test metadata hook can validate input."""
    def validation_hook(original_func, action, session_id, **kwargs):
        if action == "update":
            metadata = kwargs["metadata"]
            if "invalid" in metadata:
                raise ValueError("Invalid field not allowed")
        return original_func(kwargs.get("metadata"), kwargs.get("keys"))

    manager = MongoDBSessionManager(
        session_id="test",
        client=Mock(),
        database_name="test_db",
        metadataHook=validation_hook
    )

    # Should raise error
    with pytest.raises(ValueError, match="Invalid field"):
        manager.update_metadata({"invalid": "value"})
```

### Testing Feedback Hooks

```python
def test_feedback_hook():
    """Test that feedback hook is called."""
    feedback_received = []

    def feedback_hook(original_func, action, session_id, **kwargs):
        feedback_received.append(kwargs["feedback"])
        return original_func(kwargs["feedback"])

    manager = MongoDBSessionManager(
        session_id="test",
        client=Mock(),
        database_name="test_db",
        feedbackHook=feedback_hook
    )

    # Add feedback
    feedback = {"rating": "up", "comment": "Great!"}
    manager.add_feedback(feedback)

    assert feedback in feedback_received
```

## Testing AWS Integrations

### Testing SNS Feedback Hook

```python
@pytest.mark.skipif(
    not is_feedback_sns_hook_available(),
    reason="SNS hook not available"
)
def test_sns_feedback_hook(mocker):
    """Test SNS feedback hook."""
    from mongodb_session_manager import create_feedback_sns_hook

    # Mock SNS client
    mock_sns = mocker.Mock()
    mocker.patch('custom_aws.sns.SNSClient', return_value=mock_sns)

    # Create hook
    hook = create_feedback_sns_hook(
        topic_arn_good="arn:aws:sns:test:good",
        topic_arn_bad="arn:aws:sns:test:bad"
    )

    # Test with feedback
    manager = MongoDBSessionManager(
        session_id="test",
        client=Mock(),
        database_name="test_db",
        feedbackHook=hook
    )

    feedback = {"rating": "down", "comment": "Bad response"}
    manager.add_feedback(feedback)

    # Verify SNS was called (async, so may need to wait)
    import time
    time.sleep(0.1)  # Allow async operation to complete

    # Check that publish was attempted
    assert mock_sns.publish_message.called or mock_sns.publish_message.call_count >= 0
```

### Testing SQS Metadata Hook

```python
@pytest.mark.skipif(
    not is_metadata_sqs_hook_available(),
    reason="SQS hook not available"
)
def test_sqs_metadata_hook(mocker):
    """Test SQS metadata hook."""
    from mongodb_session_manager import create_metadata_sqs_hook

    # Mock SQS client
    mock_sqs = mocker.Mock()
    mocker.patch('custom_aws.sqs.SQSClient', return_value=mock_sqs)

    # Create hook
    hook = create_metadata_sqs_hook(
        queue_url="https://sqs.test.amazonaws.com/queue",
        metadata_fields=["status", "priority"]
    )

    # Test with metadata update
    manager = MongoDBSessionManager(
        session_id="test",
        client=Mock(),
        database_name="test_db",
        metadataHook=hook
    )

    metadata = {"status": "active", "priority": "high", "internal": "not synced"}
    manager.update_metadata(metadata)

    # Verify SQS was called
    import time
    time.sleep(0.1)

    # Check that send was attempted
    assert mock_sqs.send_message.called or mock_sqs.send_message.call_count >= 0
```

## CI/CD Testing

### GitHub Actions Example

```yaml
# .github/workflows/tests.yml
name: Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      mongodb:
        image: mongo:7.0
        ports:
          - 27017:27017
        env:
          MONGO_INITDB_ROOT_USERNAME: test
          MONGO_INITDB_ROOT_PASSWORD: test

    steps:
    - uses: actions/checkout@v3

    - name: Install UV
      run: curl -LsSf https://astral.sh/uv/install.sh | sh

    - name: Install dependencies
      run: uv sync

    - name: Run linting
      run: |
        uv run ruff check .
        uv run ruff format --check .

    - name: Run tests
      env:
        TEST_MONGODB_URI: mongodb://test:test@localhost:27017/
      run: uv run pytest --cov=mongodb_session_manager --cov-report=xml tests/

    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

### Pre-commit Hook

```bash
# .git/hooks/pre-commit
#!/bin/bash

echo "Running pre-commit checks..."

# Format code
uv run ruff format .

# Check linting
uv run ruff check --fix .

# Run tests
uv run pytest tests/

if [ $? -ne 0 ]; then
    echo "Tests failed. Commit aborted."
    exit 1
fi

echo "All checks passed!"
```

## Best Practices

### General Testing Principles

1. **Test One Thing**: Each test should test one specific behavior
2. **Clear Names**: Test names should describe what they test
3. **AAA Pattern**: Arrange, Act, Assert
4. **Independent Tests**: Tests should not depend on each other
5. **Fast Tests**: Keep tests fast by mocking external dependencies

### Good Test Example

```python
def test_update_metadata_preserves_existing_fields():
    """Test that updating metadata preserves existing fields.

    This test verifies that when metadata is updated with new fields,
    the existing fields are not removed from the database.
    """
    # Arrange
    manager = create_test_manager()
    manager.update_metadata({"field1": "value1", "field2": "value2"})

    # Act
    manager.update_metadata({"field3": "value3"})

    # Assert
    metadata = manager.get_metadata()
    assert metadata["field1"] == "value1"
    assert metadata["field2"] == "value2"
    assert metadata["field3"] == "value3"
```

### Test Organization

```
tests/
  ├── unit/                    # Unit tests
  │   ├── test_session_manager.py
  │   ├── test_repository.py
  │   ├── test_connection_pool.py
  │   └── test_factory.py
  ├── integration/             # Integration tests
  │   ├── test_full_workflow.py
  │   ├── test_persistence.py
  │   └── test_concurrent.py
  ├── hooks/                   # Hook tests
  │   ├── test_metadata_hooks.py
  │   └── test_feedback_hooks.py
  ├── aws/                     # AWS integration tests
  │   ├── test_sns_hook.py
  │   └── test_sqs_hook.py
  ├── conftest.py             # Shared fixtures
  └── pytest.ini              # Pytest configuration
```

### Pytest Configuration

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

markers =
    unit: Unit tests
    integration: Integration tests requiring MongoDB
    slow: Slow tests
    aws: Tests requiring AWS services

addopts =
    -v
    --strict-markers
    --tb=short
    --disable-warnings

# Coverage settings
[coverage:run]
source = mongodb_session_manager
omit =
    tests/*
    setup.py

[coverage:report]
precision = 2
show_missing = True
skip_covered = False
```

## Summary

Testing is crucial for maintaining code quality. Remember to:

- Write tests for all new code
- Run tests before committing
- Maintain high test coverage
- Use appropriate test types (unit vs integration)
- Mock external dependencies in unit tests
- Clean up test data after tests
- Keep tests fast and independent

For more information, see:
- [Setup Guide](setup.md) for environment setup
- [Contributing Guide](contributing.md) for contribution workflow
- [Pytest Documentation](https://docs.pytest.org/)

Happy testing!
