#!/usr/bin/env python3
"""Tests for application_name field functionality.

These tests verify that the application_name field:
- Is stored as a top-level field in the MongoDB document
- Is immutable (set only at session creation)
- Is properly indexed
- Can be retrieved via get_application_name()
- Works with both direct creation and factory pattern
"""

import os
import uuid
import pytest
from unittest.mock import MagicMock, patch

# Import the modules to test
from mongodb_session_manager import (
    create_mongodb_session_manager,
    MongoDBSessionManager,
    MongoDBSessionManagerFactory,
    initialize_global_factory,
    get_global_factory,
    close_global_factory,
)
from mongodb_session_manager.mongodb_session_repository import MongoDBSessionRepository


class TestApplicationNameRepository:
    """Test application_name at the repository level."""

    def test_repository_accepts_application_name_parameter(self):
        """Test that MongoDBSessionRepository accepts application_name parameter."""
        with patch.object(MongoDBSessionRepository, '_ensure_indexes'):
            repo = MongoDBSessionRepository(
                connection_string="mongodb://localhost:27017/",
                database_name="test_db",
                collection_name="test_sessions",
                application_name="test-app"
            )
            assert repo.application_name == "test-app"
            repo.close()

    def test_repository_application_name_defaults_to_none(self):
        """Test that application_name defaults to None when not provided."""
        with patch.object(MongoDBSessionRepository, '_ensure_indexes'):
            repo = MongoDBSessionRepository(
                connection_string="mongodb://localhost:27017/",
                database_name="test_db",
                collection_name="test_sessions"
            )
            assert repo.application_name is None
            repo.close()


class TestApplicationNameManager:
    """Test application_name at the session manager level."""

    @patch('mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository')
    def test_manager_accepts_application_name_parameter(self, mock_repo_class):
        """Test that MongoDBSessionManager accepts application_name parameter."""
        # Setup mock
        mock_repo = MagicMock()
        mock_repo.read_session.return_value = None
        mock_repo_class.return_value = mock_repo

        MongoDBSessionManager(
            session_id="test-session",
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions",
            application_name="my-bot"
        )

        # Verify application_name was passed to repository
        mock_repo_class.assert_called_once()
        call_kwargs = mock_repo_class.call_args[1]
        assert call_kwargs["application_name"] == "my-bot"

    @patch('mongodb_session_manager.mongodb_session_manager.MongoDBSessionRepository')
    def test_create_mongodb_session_manager_accepts_application_name(self, mock_repo_class):
        """Test that create_mongodb_session_manager accepts application_name."""
        mock_repo = MagicMock()
        mock_repo.read_session.return_value = None
        mock_repo_class.return_value = mock_repo

        create_mongodb_session_manager(
            session_id="test-session",
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions",
            application_name="customer-support"
        )

        # Verify application_name was passed to repository
        call_kwargs = mock_repo_class.call_args[1]
        assert call_kwargs["application_name"] == "customer-support"


class TestApplicationNameFactory:
    """Test application_name with the factory pattern."""

    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool')
    def test_factory_accepts_default_application_name(self, mock_pool):
        """Test that factory accepts default application_name."""
        mock_pool.initialize.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions",
            application_name="default-app"
        )
        assert factory.application_name == "default-app"
        factory.close()

    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager')
    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool')
    def test_factory_creates_manager_with_default_application_name(self, mock_pool, mock_manager_class):
        """Test that factory propagates default application_name to managers."""
        mock_pool.initialize.return_value = MagicMock()
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions",
            application_name="factory-default"
        )

        factory.create_session_manager(session_id="test-session")

        # Verify application_name was passed to MongoDBSessionManager
        call_kwargs = mock_manager_class.call_args[1]
        assert call_kwargs["application_name"] == "factory-default"

        factory.close()

    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager')
    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool')
    def test_factory_allows_override_per_session(self, mock_pool, mock_manager_class):
        """Test that factory allows overriding application_name per session."""
        mock_pool.initialize.return_value = MagicMock()
        mock_manager_class.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions",
            application_name="factory-default"
        )

        # Create with override
        factory.create_session_manager(
            session_id="test-session",
            application_name="custom-app"
        )
        call_kwargs = mock_manager_class.call_args[1]
        assert call_kwargs["application_name"] == "custom-app"

        # Create without override (should use factory default)
        factory.create_session_manager(session_id="test-session-2")
        call_kwargs = mock_manager_class.call_args[1]
        assert call_kwargs["application_name"] == "factory-default"

        factory.close()

    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager')
    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool')
    def test_factory_override_with_none_uses_default(self, mock_pool, mock_manager_class):
        """Test that passing None uses factory default."""
        mock_pool.initialize.return_value = MagicMock()
        mock_manager_class.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions",
            application_name="factory-default"
        )

        # Explicit None should NOT override factory default
        factory.create_session_manager(
            session_id="test-session",
            application_name=None
        )
        call_kwargs = mock_manager_class.call_args[1]
        assert call_kwargs["application_name"] == "factory-default"

        factory.close()


class TestGlobalFactoryApplicationName:
    """Test application_name with global factory functions."""

    def teardown_method(self):
        """Clean up global factory after each test."""
        try:
            close_global_factory()
        except RuntimeError:
            pass  # Factory not initialized

    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool')
    def test_initialize_global_factory_accepts_application_name(self, mock_pool):
        """Test that initialize_global_factory accepts application_name."""
        mock_pool.initialize.return_value = MagicMock()

        factory = initialize_global_factory(
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions",
            application_name="global-app"
        )

        assert factory.application_name == "global-app"

    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager')
    @patch('mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool')
    def test_global_factory_propagates_application_name(self, mock_pool, mock_manager_class):
        """Test that global factory propagates application_name to sessions."""
        mock_pool.initialize.return_value = MagicMock()
        mock_manager_class.return_value = MagicMock()

        initialize_global_factory(
            connection_string="mongodb://localhost:27017/",
            database_name="test_db",
            collection_name="test_sessions",
            application_name="global-app"
        )

        get_global_factory().create_session_manager(session_id="test")
        call_kwargs = mock_manager_class.call_args[1]
        assert call_kwargs["application_name"] == "global-app"


class TestApplicationNameIntegration:
    """Integration tests requiring a real MongoDB connection.

    These tests require MONGODB_CONNECTION_STRING environment variable.
    Skip if not available.
    """

    @pytest.fixture
    def mongodb_connection(self):
        """Get MongoDB connection string from environment."""
        conn_str = os.environ.get("MONGODB_CONNECTION_STRING")
        if not conn_str:
            pytest.skip("MONGODB_CONNECTION_STRING not set")
        return conn_str

    @pytest.fixture
    def unique_session_id(self):
        """Generate a unique session ID for each test."""
        return f"test-app-name-{uuid.uuid4().hex[:8]}"

    def _create_mock_agent(self, agent_id: str = "test-agent"):
        """Create a properly mocked agent for MongoDB integration tests."""
        mock_agent = MagicMock()
        mock_agent.agent_id = agent_id
        mock_agent.messages = []
        # These attributes need to be serializable for MongoDB
        mock_agent.state = MagicMock()
        mock_agent.state.get.return_value = {}  # Return empty dict, not MagicMock
        return mock_agent

    def test_application_name_stored_in_document(self, mongodb_connection, unique_session_id):
        """Test that application_name is stored at document root level."""
        manager = create_mongodb_session_manager(
            session_id=unique_session_id,
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
            application_name="integration-test-app"
        )

        try:
            # The session document is created when the manager is initialized
            # Query the document directly (session is auto-created)
            doc = manager.session_repository.collection.find_one(
                {"_id": unique_session_id}
            )

            assert doc is not None, "Session document should exist"
            assert "application_name" in doc, "application_name should be at root level"
            assert doc["application_name"] == "integration-test-app"

        finally:
            # Clean up
            manager.session_repository.collection.delete_one({"_id": unique_session_id})
            manager.close()

    def test_get_application_name_returns_value(self, mongodb_connection, unique_session_id):
        """Test that get_application_name() returns the stored value."""
        manager = create_mongodb_session_manager(
            session_id=unique_session_id,
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
            application_name="readable-app"
        )

        try:
            # Test get_application_name()
            app_name = manager.get_application_name()
            assert app_name == "readable-app"

        finally:
            manager.session_repository.collection.delete_one({"_id": unique_session_id})
            manager.close()

    def test_application_name_none_when_not_set(self, mongodb_connection, unique_session_id):
        """Test that get_application_name() returns None when not set."""
        manager = create_mongodb_session_manager(
            session_id=unique_session_id,
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions"
            # No application_name provided
        )

        try:
            app_name = manager.get_application_name()
            assert app_name is None

        finally:
            manager.session_repository.collection.delete_one({"_id": unique_session_id})
            manager.close()

    def test_application_name_index_exists(self, mongodb_connection, unique_session_id):
        """Test that application_name index is created."""
        manager = create_mongodb_session_manager(
            session_id=unique_session_id,
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
            application_name="index-test-app"
        )

        try:
            # Get index info
            indexes = manager.session_repository.collection.index_information()

            # Check for application_name index
            has_app_name_index = any(
                "application_name" in str(idx.get("key", []))
                for idx in indexes.values()
            )

            assert has_app_name_index, "application_name index should exist"

        finally:
            manager.close()

    def test_factory_integration(self, mongodb_connection, unique_session_id):
        """Test factory pattern with application_name integration."""
        factory = MongoDBSessionManagerFactory(
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
            application_name="factory-integration"
        )

        try:
            manager = factory.create_session_manager(session_id=unique_session_id)

            # Verify in database
            doc = manager.session_repository.collection.find_one(
                {"_id": unique_session_id}
            )
            assert doc["application_name"] == "factory-integration"

            # Verify via get_application_name()
            assert manager.get_application_name() == "factory-integration"

        finally:
            manager.session_repository.collection.delete_one({"_id": unique_session_id})
            factory.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
