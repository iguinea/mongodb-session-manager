"""Unit tests for MongoDBSessionManagerFactory and global factory functions."""

from unittest.mock import MagicMock, patch

import pytest

from mongodb_session_manager.mongodb_session_factory import (
    MongoDBSessionManagerFactory,
    initialize_global_factory,
    get_global_factory,
    close_global_factory,
)
import mongodb_session_manager.mongodb_session_factory as factory_module


@pytest.fixture(autouse=True)
def reset_global_factory():
    """Reset global factory state after each test."""
    yield
    factory_module._global_factory = None


# ---------------------------------------------------------------------------
# Factory init
# ---------------------------------------------------------------------------


class TestFactoryInit:
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_init_with_connection_string(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost/",
        )
        assert factory._owns_client is True
        mock_pool.initialize.assert_called_once()

    def test_init_with_client(self):
        client = MagicMock()
        factory = MongoDBSessionManagerFactory(client=client)
        assert factory._owns_client is False
        assert factory._client is client

    def test_init_raises_without_connection_or_client(self):
        with pytest.raises(ValueError, match="Either connection_string or client"):
            MongoDBSessionManagerFactory()

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_stores_application_name(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost/",
            application_name="my-app",
        )
        assert factory.application_name == "my-app"

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_stores_metadata_fields(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost/",
            metadata_fields=["status"],
        )
        assert factory.metadata_fields == ["status"]


# ---------------------------------------------------------------------------
# create_session_manager
# ---------------------------------------------------------------------------


class TestCreateSessionManager:
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager")
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_uses_shared_client(self, mock_pool, mock_mgr_cls):
        mock_client = MagicMock()
        mock_pool.initialize.return_value = mock_client
        mock_mgr_cls.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(connection_string="mongodb://localhost/")
        factory.create_session_manager(session_id="s1")

        call_kwargs = mock_mgr_cls.call_args[1]
        assert call_kwargs["client"] is mock_client

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager")
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_uses_default_db_name(self, mock_pool, mock_mgr_cls):
        mock_pool.initialize.return_value = MagicMock()
        mock_mgr_cls.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost/",
            database_name="my_db",
        )
        factory.create_session_manager(session_id="s1")
        assert mock_mgr_cls.call_args[1]["database_name"] == "my_db"

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager")
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_overrides_db_name(self, mock_pool, mock_mgr_cls):
        mock_pool.initialize.return_value = MagicMock()
        mock_mgr_cls.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost/",
            database_name="default_db",
        )
        factory.create_session_manager(session_id="s1", database_name="override_db")
        assert mock_mgr_cls.call_args[1]["database_name"] == "override_db"

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager")
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_uses_factory_application_name(self, mock_pool, mock_mgr_cls):
        mock_pool.initialize.return_value = MagicMock()
        mock_mgr_cls.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost/",
            application_name="factory-default",
        )
        factory.create_session_manager(session_id="s1")
        assert mock_mgr_cls.call_args[1]["application_name"] == "factory-default"

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager")
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_overrides_application_name(self, mock_pool, mock_mgr_cls):
        mock_pool.initialize.return_value = MagicMock()
        mock_mgr_cls.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost/",
            application_name="factory-default",
        )
        factory.create_session_manager(session_id="s1", application_name="custom")
        assert mock_mgr_cls.call_args[1]["application_name"] == "custom"

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager")
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_none_override_uses_factory_default(self, mock_pool, mock_mgr_cls):
        mock_pool.initialize.return_value = MagicMock()
        mock_mgr_cls.return_value = MagicMock()

        factory = MongoDBSessionManagerFactory(
            connection_string="mongodb://localhost/",
            application_name="factory-default",
        )
        factory.create_session_manager(session_id="s1", application_name=None)
        assert mock_mgr_cls.call_args[1]["application_name"] == "factory-default"


# ---------------------------------------------------------------------------
# get_connection_stats
# ---------------------------------------------------------------------------


class TestGetConnectionStats:
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_pool_stats(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        mock_pool.get_pool_stats.return_value = {"status": "connected"}

        factory = MongoDBSessionManagerFactory(connection_string="mongodb://localhost/")
        stats = factory.get_connection_stats()
        assert stats["status"] == "connected"

    def test_external_client_stats(self):
        factory = MongoDBSessionManagerFactory(client=MagicMock())
        stats = factory.get_connection_stats()
        assert stats["status"] == "external_client"


# ---------------------------------------------------------------------------
# Factory close
# ---------------------------------------------------------------------------


class TestFactoryClose:
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_closes_pool(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        factory = MongoDBSessionManagerFactory(connection_string="mongodb://localhost/")
        factory.close()
        mock_pool.close.assert_called_once()

    def test_does_not_close_external_client(self):
        client = MagicMock()
        factory = MongoDBSessionManagerFactory(client=client)
        factory.close()
        # MongoDBConnectionPool.close should not be called


# ---------------------------------------------------------------------------
# Global factory
# ---------------------------------------------------------------------------


class TestGlobalFactory:
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_initialize(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        factory = initialize_global_factory(connection_string="mongodb://localhost/")
        assert factory is not None
        assert get_global_factory() is factory

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_closes_existing_on_reinit(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        f1 = initialize_global_factory(connection_string="mongodb://localhost/")
        f2 = initialize_global_factory(connection_string="mongodb://localhost/")
        assert f1 is not f2

    def test_get_raises_when_not_initialized(self):
        with pytest.raises(RuntimeError, match="Global factory not initialized"):
            get_global_factory()

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_close_cleanup(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        initialize_global_factory(connection_string="mongodb://localhost/")
        close_global_factory()
        assert factory_module._global_factory is None

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_initialize_with_application_name(self, mock_pool):
        mock_pool.initialize.return_value = MagicMock()
        factory = initialize_global_factory(
            connection_string="mongodb://localhost/",
            application_name="global-app",
        )
        assert factory.application_name == "global-app"

    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBSessionManager")
    @patch("mongodb_session_manager.mongodb_session_factory.MongoDBConnectionPool")
    def test_global_factory_propagates_app_name(self, mock_pool, mock_mgr_cls):
        mock_pool.initialize.return_value = MagicMock()
        mock_mgr_cls.return_value = MagicMock()

        initialize_global_factory(
            connection_string="mongodb://localhost/",
            application_name="global-app",
        )
        get_global_factory().create_session_manager(session_id="s1")
        assert mock_mgr_cls.call_args[1]["application_name"] == "global-app"
