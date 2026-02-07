"""Integration tests for MongoDBSessionManagerFactory (requires MongoDB).

Migrates factory integration tests from test_application_name.py.
"""

import pytest

from mongodb_session_manager import (
    MongoDBSessionManagerFactory,
    initialize_global_factory,
    get_global_factory,
    close_global_factory,
)
import mongodb_session_manager.mongodb_session_factory as factory_module


pytestmark = pytest.mark.integration


class TestFactoryIntegration:
    def test_factory_with_real_mongodb(
        self, mongodb_connection, unique_session_id, cleanup_session
    ):
        factory = MongoDBSessionManagerFactory(
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
            application_name="factory-integration",
        )
        try:
            mgr = factory.create_session_manager(session_id=unique_session_id)
            cleanup_session(mgr.session_repository.collection, unique_session_id)

            doc = mgr.session_repository.collection.find_one({"_id": unique_session_id})
            assert doc["application_name"] == "factory-integration"
            assert mgr.get_application_name() == "factory-integration"
        finally:
            factory.close()

    def test_factory_override_application_name(
        self, mongodb_connection, unique_session_id, cleanup_session
    ):
        factory = MongoDBSessionManagerFactory(
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
            application_name="default-app",
        )
        try:
            mgr = factory.create_session_manager(
                session_id=unique_session_id,
                application_name="custom-app",
            )
            cleanup_session(mgr.session_repository.collection, unique_session_id)

            assert mgr.get_application_name() == "custom-app"
        finally:
            factory.close()

    def test_global_factory_lifecycle(
        self, mongodb_connection, unique_session_id, cleanup_session
    ):
        try:
            initialize_global_factory(
                connection_string=mongodb_connection,
                database_name="test_db",
                collection_name="test_sessions",
                application_name="global-integration",
            )

            mgr = get_global_factory().create_session_manager(
                session_id=unique_session_id
            )
            cleanup_session(mgr.session_repository.collection, unique_session_id)

            assert mgr.get_application_name() == "global-integration"
        finally:
            close_global_factory()
            factory_module._global_factory = None

    def test_connection_stats(self, mongodb_connection):
        factory = MongoDBSessionManagerFactory(
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
        )
        try:
            stats = factory.get_connection_stats()
            assert stats["status"] == "connected"
        finally:
            factory.close()

    def test_factory_without_application_name(
        self, mongodb_connection, unique_session_id, cleanup_session
    ):
        factory = MongoDBSessionManagerFactory(
            connection_string=mongodb_connection,
            database_name="test_db",
            collection_name="test_sessions",
        )
        try:
            mgr = factory.create_session_manager(session_id=unique_session_id)
            cleanup_session(mgr.session_repository.collection, unique_session_id)

            assert mgr.get_application_name() is None
        finally:
            factory.close()
