"""Unit tests for MongoDBConnectionPool."""

from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import PyMongoError

from mongodb_session_manager.mongodb_connection_pool import MongoDBConnectionPool


@pytest.fixture(autouse=True)
def reset_connection_pool():
    """Reset the singleton state between tests."""
    yield
    # Reset singleton
    MongoDBConnectionPool._instance = None
    MongoDBConnectionPool._client = None
    MongoDBConnectionPool._connection_string = None
    MongoDBConnectionPool._client_kwargs = {}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_same_instance(self):
        a = MongoDBConnectionPool()
        b = MongoDBConnectionPool()
        assert a is b

    def test_thread_safety(self):
        import threading

        instances = []

        def create():
            instances.append(MongoDBConnectionPool())

        threads = [threading.Thread(target=create) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(inst is instances[0] for inst in instances)


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_creates_client_with_defaults(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client_cls.return_value = mock_client

        result = MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
        assert result is mock_client
        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs["maxPoolSize"] == 100
        assert call_kwargs["retryWrites"] is True

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_reuses_for_same_params(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client_cls.return_value = mock_client

        client1 = MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
        client2 = MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
        assert client1 is client2
        assert mock_client_cls.call_count == 1

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_recreates_when_params_change(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://host1/")
        MongoDBConnectionPool.initialize("mongodb://host2/")
        assert mock_client_cls.call_count == 2

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_pings_admin(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost:27017/")
        mock_client.admin.command.assert_called_once_with("ping")

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_raises_on_connection_error(self, mock_client_cls):
        mock_client_cls.side_effect = PyMongoError("connection failed")
        with pytest.raises(PyMongoError):
            MongoDBConnectionPool.initialize("mongodb://bad/")

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_kwargs_override_defaults(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/", maxPoolSize=50)
        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs["maxPoolSize"] == 50


# ---------------------------------------------------------------------------
# get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_returns_client(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        assert MongoDBConnectionPool.get_client() is mock_client

    def test_returns_none_when_not_initialized(self):
        assert MongoDBConnectionPool.get_client() is None


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_closes_and_cleans_state(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        MongoDBConnectionPool.close()
        mock_client.close.assert_called_once()
        assert MongoDBConnectionPool.get_client() is None

    def test_handles_close_without_initialize(self):
        # Should not raise
        MongoDBConnectionPool.close()


# ---------------------------------------------------------------------------
# get_pool_stats
# ---------------------------------------------------------------------------


class TestGetPoolStats:
    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_stats_when_connected(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client.server_info.return_value = {"version": "7.0.0"}
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        stats = MongoDBConnectionPool.get_pool_stats()
        assert stats["status"] == "connected"
        assert stats["server_version"] == "7.0.0"

    def test_stats_not_initialized(self):
        stats = MongoDBConnectionPool.get_pool_stats()
        assert stats["status"] == "not_initialized"

    @patch("mongodb_session_manager.mongodb_connection_pool.MongoClient")
    def test_stats_on_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}
        mock_client.server_info.side_effect = Exception("stats error")
        mock_client_cls.return_value = mock_client

        MongoDBConnectionPool.initialize("mongodb://localhost/")
        stats = MongoDBConnectionPool.get_pool_stats()
        assert stats["status"] == "error"
