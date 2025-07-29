"""MongoDB Session Repository implementation for Strands Agents."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage

logger = logging.getLogger(__name__)


class MongoDBSessionRepository(SessionRepository):
    """MongoDB implementation of SessionRepository interface."""

    def __init__(
        self,
        connection_string: Optional[str] = None,
        database_name: str = "database_name",
        collection_name: str = "collection_name",
        client: Optional[MongoClient] = None,
        metadata_fields: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize MongoDB Session Repository.

        Args:
            connection_string: MongoDB connection string (ignored if client is provided)
            database_name: Name of the database
            collection_name: Name of the collection for sessions
            client: Optional pre-configured MongoClient to use
            **kwargs: Additional arguments for MongoClient (ignored if client is provided)
        """
        if client is not None:
            # Use provided client
            self.client: MongoClient = client
            self._owns_client = False  # Don't close a client we didn't create
            logger.info("Using provided MongoDB client")
        else:
            # Create new client (legacy behavior)
            if connection_string is None:
                raise ValueError("Connection string is required")
            self.client = MongoClient(connection_string, **kwargs)
            self._owns_client = True  # We created it, we should close it
            logger.info("Created new MongoDB client")

        self.database: Database = self.client[database_name]
        self.collection: Collection = self.database[collection_name]
        self.metadata_fields = metadata_fields
        # Create indexes for timestamp ordering (only once per collection)
        self._ensure_indexes()

        logger.info(
            f"Initialized MongoDB session repository - "
            f"Database: {database_name}, Collection: {collection_name}"
        )

    def _ensure_indexes(self) -> None:
        """Ensure necessary indexes exist on the collection."""
        try:
            # Index on session timestamps
            self.collection.create_index("created_at")
            self.collection.create_index("updated_at")
            # Note: MongoDB doesn't support positional operators ($) in index definitions
            # Messages are nested arrays, so we rely on the _id index for document lookup
            if self.metadata_fields:
                for field in self.metadata_fields:
                    self.collection.create_index(field)

            logger.info("MongoDB indexes created successfully")
        except PyMongoError as e:
            logger.warning(f"Failed to create indexes: {e}")

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        """Create a new Session in MongoDB."""
        session_doc = {
            "_id": session.session_id,
            "session_id": session.session_id,
            "session_type": session.session_type,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "agents": {},
            "metadata": {},
        }
        if self.metadata_fields:
            for field in self.metadata_fields:
                session_doc["metadata"][field.split(".")[1]] = ""

        try:
            self.collection.insert_one(session_doc)
            logger.info(f"Created session: {session.session_id}")
        except PyMongoError as e:
            logger.error(f"Failed to create session {session.session_id}: {e}")
            raise

        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Optional[Session]:
        """Read a Session from MongoDB."""
        try:
            doc = self.collection.find_one({"_id": session_id})
            if not doc:
                logger.debug(f"Session not found: {session_id}")
                return None

            # Convert MongoDB document to Session object
            session = Session(
                session_id=doc["session_id"],
                session_type=doc.get("session_type", "default"),
                created_at=doc.get("created_at"),
                updated_at=doc.get("updated_at"),
            )

            logger.debug(f"Read session: {session_id}")
            return session

        except PyMongoError as e:
            logger.error(f"Failed to read session {session_id}: {e}")
            raise

    def create_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Create a new Agent in a Session."""

        agent_data = session_agent.__dict__

        agent_data["created_at"] = datetime.fromisoformat(
            session_agent.created_at.replace("Z", "+00:00")
        )

        agent_data["updated_at"] = datetime.fromisoformat(
            session_agent.updated_at.replace("Z", "+00:00")
        )

        agent_doc = {
            "agent_data": agent_data,
            "messages": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }

        try:
            result = self.collection.update_one(
                {"_id": session_id},
                {
                    "$set": {
                        f"agents.{session_agent.agent_id}": agent_doc,
                        "updated_at": datetime.now(UTC),
                    }
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            logger.info(
                f"Created agent {session_agent.agent_id} in session {session_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to create agent {session_agent.agent_id}: {e}")
            raise

    def read_agent(
        self, session_id: str, agent_id: str, **kwargs: Any
    ) -> Optional[SessionAgent]:
        """Read an Agent from a Session."""
        try:
            doc = self.collection.find_one(
                {"_id": session_id}, {f"agents.{agent_id}": 1}
            )

            if not doc or "agents" not in doc or agent_id not in doc["agents"]:
                logger.debug(f"Agent {agent_id} not found in session {session_id}")
                return None

            agent_data = doc["agents"][agent_id]["agent_data"]

            session_agent = SessionAgent(**agent_data)
            logger.debug(f"Read agent {agent_id} from session {session_id}")
            return session_agent

        except PyMongoError as e:
            logger.error(f"Failed to read agent {agent_id}: {e}")
            raise

    def update_agent(
        self, session_id: str, session_agent: SessionAgent, **kwargs: Any
    ) -> None:
        """Update an Agent in a Session."""
        agent_data = session_agent.__dict__

        agent_data["created_at"] = datetime.fromisoformat(
            session_agent.created_at.replace("Z", "+00:00")
        )

        agent_data["updated_at"] = datetime.fromisoformat(
            session_agent.updated_at.replace("Z", "+00:00")
        )

        try:
            # Preserve original created_at timestamp
            existing = self.collection.find_one(
                {"_id": session_id}, {f"agents.{session_agent.agent_id}.created_at": 1}
            )

            created_at = datetime.now(UTC)
            if (
                existing
                and "agents" in existing
                and session_agent.agent_id in existing["agents"]
            ):
                created_at = existing["agents"][session_agent.agent_id].get(
                    "created_at", created_at
                )

            result = self.collection.update_one(
                {"_id": session_id},
                {
                    "$set": {
                        f"agents.{session_agent.agent_id}.agent_data": agent_data,
                        f"agents.{session_agent.agent_id}.updated_at": datetime.now(
                            UTC
                        ),
                        f"agents.{session_agent.agent_id}.created_at": created_at,
                        "updated_at": datetime.now(UTC),
                    }
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            logger.info(
                f"Updated agent {session_agent.agent_id} in session {session_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to update agent {session_agent.agent_id}: {e}")
            raise

    def create_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Create a new Message for the Agent."""

        message_data = session_message.__dict__
        # message_data = self._serialize_datetime(
        #     message_data, exclude_fields=["created_at", "updated_at"]
        # )
        message_data["created_at"] = datetime.now(UTC)
        message_data["updated_at"] = datetime.now(UTC)

        try:
            result = self.collection.update_one(
                {"_id": session_id},
                {
                    "$push": {f"agents.{agent_id}.messages": message_data},
                    "$set": {
                        f"agents.{agent_id}.updated_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                    },
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            logger.info(
                f"Created message {session_message.message_id} for agent {agent_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to create message: {e}")
            raise

    def read_message(
        self, session_id: str, agent_id: str, message_id: int, **kwargs: Any
    ) -> Optional[SessionMessage]:
        """Read a Message from an Agent."""
        try:
            doc = self.collection.find_one(
                {"_id": session_id}, {f"agents.{agent_id}.messages": 1}
            )

            if not doc or "agents" not in doc or agent_id not in doc["agents"]:
                return None

            messages = doc["agents"][agent_id].get("messages", [])

            # Find message by ID
            for msg_data in messages:
                if msg_data.get("message_id") == message_id:
                    # logger.warning(f"msg_data1: {msg_data}")
                    # msg_data = self._deserialize_datetime(msg_data)
                    # logger.warning(f"msg_data2: {msg_data}")

                    # Filter out metrics fields that SessionMessage doesn't accept
                    metrics_fields = ["event_loop_metrics"]
                    filtered_msg_data = {
                        k: v for k, v in msg_data.items() if k not in metrics_fields
                    }
                    return SessionMessage(**filtered_msg_data)

            logger.debug(f"Message {message_id} not found")
            return None

        except PyMongoError as e:
            logger.error(f"Failed to read message {message_id}: {e}")
            raise

    def update_message(
        self,
        session_id: str,
        agent_id: str,
        session_message: SessionMessage,
        **kwargs: Any,
    ) -> None:
        """Update a Message (usually for redaction)."""

        message_data = session_message.__dict__
        # message_data = self._serialize_datetime(
        #     message_data, exclude_fields=["created_at", "updated_at"]
        # )

        try:
            # First, get the current messages to find the index
            doc = self.collection.find_one(
                {"_id": session_id}, {f"agents.{agent_id}.messages": 1}
            )

            if not doc or "agents" not in doc or agent_id not in doc["agents"]:
                raise ValueError(f"Agent {agent_id} not found in session {session_id}")

            messages = doc["agents"][agent_id].get("messages", [])

            # Find the message index
            message_index = -1
            for i, msg in enumerate(messages):
                if msg.get("message_id") == session_message.message_id:
                    message_index = i
                    # Preserve created_at timestamp
                    message_data["created_at"] = msg.get(
                        "created_at", datetime.now(UTC)
                    )
                    message_data["updated_at"] = datetime.now(UTC)
                    break

            if message_index == -1:
                raise ValueError(f"Message {session_message.message_id} not found")

            # Update the specific message
            result = self.collection.update_one(
                {"_id": session_id},
                {
                    "$set": {
                        f"agents.{agent_id}.messages.{message_index}": message_data,
                        f"agents.{agent_id}.updated_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                    }
                },
            )

            if result.matched_count == 0:
                raise ValueError(f"Session {session_id} not found")

            logger.info(
                f"Updated message {session_message.message_id} for agent {agent_id}"
            )

        except PyMongoError as e:
            logger.error(f"Failed to update message: {e}")
            raise

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[SessionMessage]:
        """List Messages from an Agent with pagination support."""
        try:
            doc = self.collection.find_one(
                {"_id": session_id}, {f"agents.{agent_id}.messages": 1}
            )

            if not doc:
                logger.warning(f"No document found for session {session_id}")
                return []

            if "agents" not in doc or agent_id not in doc["agents"]:
                logger.warning(f"Agent {agent_id} not found in session {session_id}")
                return []

            messages = doc["agents"][agent_id].get("messages", [])
            logger.info(
                f"Found {len(messages)} raw messages for agent {agent_id} in session {session_id}"
            )

            # Sort messages by created_at (oldest first - chronological order)
            messages.sort(key=lambda x: x.get("created_at", ""), reverse=False)

            # Apply pagination
            if limit is not None:
                messages = messages[offset : offset + limit]
            else:
                messages = messages[offset:]

            # Convert to SessionMessage objects
            result = []
            for i, msg_data in enumerate(messages):
                try:
                    # msg_data = self._deserialize_datetime(msg_data)
                    # Log the structure before conversion
                    logger.debug(f"Message {i} structure: {list(msg_data.keys())}")

                    # Filter out metrics fields that SessionMessage doesn't accept
                    metrics_fields = ["event_loop_metrics"]
                    filtered_msg_data = {
                        k: v for k, v in msg_data.items() if k not in metrics_fields
                    }

                    result.append(SessionMessage(**filtered_msg_data))
                except Exception as e:
                    logger.error(f"Failed to convert message {i}: {e}")
                    logger.error(f"Message data: {msg_data}")

            logger.info(
                f"Successfully converted {len(result)} messages for agent {agent_id}"
            )
            return result

        except PyMongoError as e:
            logger.error(f"Failed to list messages: {e}")
            raise

    def close(self) -> None:
        """Close the MongoDB connection."""
        if self._owns_client:
            self.client.close()
            logger.info("MongoDB connection closed")
        else:
            logger.info("Skipping close - using shared MongoDB client")

    # CUSTOM METHODS
    def update_metadata(self, session_id: str, metadata: Dict[str, Any]) -> None:
        """Update the metadata for the session."""
        try:
            # Build $set operation with dot notation to preserve existing values
            set_operations = {
                f"metadata.{key}": value for key, value in metadata.items()
            }

            self.collection.update_one(
                {"_id": session_id},
                {"$set": set_operations},
            )
        except PyMongoError as e:
            logger.error(f"Failed to update metadata for session {session_id}: {e}")
            raise

    def get_metadata(self, session_id: str) -> Dict[str, Any]:
        """Get the metadata for the session."""
        return self.collection.find_one({"_id": session_id}, {"metadata": 1})

    def delete_metadata(self, session_id: str, metadata_keys: List[str]) -> None:
        """Delete metadata keys for the session."""
        try:
            # Build $unset operation with dot notation
            unset_operations = {
                f"metadata.{metadata_key}": "" for metadata_key in metadata_keys
            }

            self.collection.update_one(
                {"_id": session_id},
                {"$unset": unset_operations},
            )
        except PyMongoError as e:
            logger.error(
                f"Failed to delete metadata keys {metadata_keys} for session {session_id}: {e}"
            )
            raise
