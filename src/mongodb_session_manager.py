"""Itzulbira Session Manager implementation for Strands Agents."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from pymongo import MongoClient
from strands.session.repository_session_manager import RepositorySessionManager

from .mongodb_connection_pool import MongoDBConnectionPool
from .mongodb_session_repository import MongoDBSessionRepository

logger = logging.getLogger(__name__)


class MongoDBSessionManager(RepositorySessionManager):
    """Itzulbira Session Manager for Strands Agents with comprehensive metrics tracking."""

    def __init__(
        self,
        session_id: str,
        connection_string: Optional[str] = None,
        database_name: str = "genai-mrg-mongodb",
        collection_name: str = "virtualagent_sessions",
        client: Optional[MongoClient] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Itzulbira Session Manager.

        Args:
            session_id: Unique identifier for the session
            connection_string: MongoDB connection string (ignored if client is provided)
            database_name: Name of the database
            collection_name: Name of the collection for sessions
            client: Optional pre-configured MongoClient to use
            **kwargs: Additional arguments passed to parent class and MongoClient
        """
        # Extract MongoDB client kwargs
        mongo_kwargs = {}
        parent_kwargs = {}
        
        # Common MongoDB client options
        mongo_options = {
            "maxPoolSize", "minPoolSize", "maxIdleTimeMS", "waitQueueTimeoutMS",
            "serverSelectionTimeoutMS", "connectTimeoutMS", "socketTimeoutMS",
            "compressors", "retryWrites", "retryReads", "w", "journal",
            "fsync", "authSource", "authMechanism", "tlsAllowInvalidCertificates"
        }
        
        for key, value in kwargs.items():
            if key in mongo_options:
                mongo_kwargs[key] = value
            else:
                parent_kwargs[key] = value
        
        # Create MongoDB repository with optional client
        repository = MongoDBSessionRepository(
            connection_string=connection_string,
            database_name=database_name,
            collection_name=collection_name,
            client=client,
            **mongo_kwargs
        )
        
        # Initialize parent class with repository
        super().__init__(
            session_id=session_id,
            session_repository=repository,
            **parent_kwargs
        )
        
        # Track metrics internally
        self._start_time: Optional[float] = None
        self._last_input_tokens: Optional[int] = None
        self._last_output_tokens: Optional[int] = None
        self._agent_configs: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"Initialized Itzulbira session manager for session: {session_id}")

    def sync_agent(self, agent: Any, **kwargs: Any) -> None:
        """Sync agent data and capture model/system_prompt."""
        # FIRST: Save existing token totals before parent overwrites them
        existing_totals = {}
        doc = self.session_repository.collection.find_one(
            {"_id": self.session_id},
            {f"agents.{agent.agent_id}.metadata.metrics": 1}
        )
        if doc and "agents" in doc and agent.agent_id in doc["agents"]:
            metrics = doc["agents"][agent.agent_id].get("metadata", {}).get("metrics", {})
            if metrics:  # Check metrics is not None
                for key in ['total_input_tokens', 'total_output_tokens', 'total_tokens']:
                    if key in metrics:
                        existing_totals[key] = metrics[key]
        
        # Call parent (this will overwrite agent data)
        super().sync_agent(agent, **kwargs)
        
        # Extract and store agent configuration
        model = None
        if hasattr(agent, 'model'):
            model_obj = agent.model
            if hasattr(model_obj, 'config') and isinstance(model_obj.config, dict):
                model = model_obj.config.get('model_id')  # Get from BedrockModel config
            elif hasattr(model_obj, 'model'):
                model = model_obj.model  # Alternative attribute
            elif isinstance(model_obj, str):
                model = model_obj
        
        system_prompt = getattr(agent, 'system_prompt', None)
        name = getattr(agent, 'name', None)
        description = getattr(agent, 'description', None)
        
        # Extract agent state if available
        agent_state = {}
        if hasattr(agent, 'state'):
            try:
                # Get the entire state dictionary
                agent_state = agent.state.get() if hasattr(agent.state, 'get') else {}
            except Exception as e:
                logger.debug(f"Could not extract agent state: {e}")
        
        # Store config for this agent
        self._agent_configs[agent.agent_id] = {
            'model': model,
            'system_prompt': system_prompt,
            'name': name,
            'description': description
        }
        
        # Update agent data and metadata in MongoDB
        update_data = {}
        
        # Store model, system_prompt, name and description in metadata
        if model:
            update_data[f"agents.{agent.agent_id}.metadata.model"] = model
        if system_prompt:
            update_data[f"agents.{agent.agent_id}.metadata.system_prompt"] = system_prompt
        if name:
            update_data[f"agents.{agent.agent_id}.metadata.name"] = name
        if description:
            update_data[f"agents.{agent.agent_id}.metadata.description"] = description
        
        # Store agent state in agent_data
        if agent_state is not None:
            update_data[f"agents.{agent.agent_id}.agent_data.state"] = agent_state
        
        # Restore or initialize token totals in metadata.metrics
        if existing_totals:
            # Restore existing totals
            for key, value in existing_totals.items():
                update_data[f"agents.{agent.agent_id}.metadata.metrics.{key}"] = value
        else:
            # Initialize to 0 for new agents
            update_data[f"agents.{agent.agent_id}.metadata.metrics.total_input_tokens"] = 0
            update_data[f"agents.{agent.agent_id}.metadata.metrics.total_output_tokens"] = 0
            update_data[f"agents.{agent.agent_id}.metadata.metrics.total_tokens"] = 0
        
        if update_data:
            self.session_repository.collection.update_one(
                {"_id": self.session_id},
                {"$set": update_data}
            )
    
    def start_timing(self) -> None:
        """Start timing for latency measurement.
        
        Note: Timing now starts automatically when user messages are appended.
        This method is kept for backwards compatibility and edge cases.
        """
        self._start_time = time.time()
    
    def set_token_counts(self, input_tokens: int, output_tokens: int) -> None:
        """Set token counts for the current interaction.
        
        Note: Token counts are now automatically extracted when possible.
        This method is kept for backwards compatibility and edge cases.
        """
        self._last_input_tokens = input_tokens
        self._last_output_tokens = output_tokens
    
    def _extract_token_info(self, message: Any, agent: Any) -> Dict[str, int]:
        """Extract token information from message, agent, or model response.
        
        Tries multiple sources to automatically detect token usage:
        1. Message object (usage, token_usage, metrics attributes)
        2. Agent object (last_response, usage attributes) 
        3. Agent model object (usage attributes)
        4. Message metadata or context
        
        Returns:
            Dict with 'input_tokens' and 'output_tokens' keys, or empty dict if not found
        """
        token_info = {}
        
        # Debug logging
        logger.debug(f"=== Token Extraction Debug ===")
        logger.debug(f"Message type: {type(message)}")
        logger.debug(f"Message attrs: {dir(message) if hasattr(message, '__dir__') else 'N/A'}")
        
        # Try to extract from message object
        if hasattr(message, 'usage'):
            logger.debug(f"Found 'usage' attr on message")
            usage = message.usage
            logger.debug(f"Usage type: {type(usage)}, value: {usage}")
            if hasattr(usage, 'input_tokens'):
                token_info['input_tokens'] = usage.input_tokens
                logger.debug(f"Found input_tokens: {usage.input_tokens}")
            if hasattr(usage, 'output_tokens'):
                token_info['output_tokens'] = usage.output_tokens
                logger.debug(f"Found output_tokens: {usage.output_tokens}")
        
        # Try token_usage attribute (alternative naming)
        elif hasattr(message, 'token_usage'):
            logger.debug(f"Found 'token_usage' attr on message")
            usage = message.token_usage
            if hasattr(usage, 'prompt_tokens'):
                token_info['input_tokens'] = usage.prompt_tokens
            if hasattr(usage, 'completion_tokens'):
                token_info['output_tokens'] = usage.completion_tokens
        
        # Try metrics attribute
        elif hasattr(message, 'metrics'):
            logger.debug(f"Found 'metrics' attr on message")
            metrics = message.metrics
            if hasattr(metrics, 'input_tokens'):
                token_info['input_tokens'] = metrics.input_tokens
            if hasattr(metrics, 'output_tokens'):
                token_info['output_tokens'] = metrics.output_tokens
        
        # Try to extract from agent if message doesn't have tokens
        if not token_info and agent:
            logger.debug(f"No tokens in message, checking agent...")
            logger.debug(f"Agent type: {type(agent)}")
            logger.debug(f"Agent attrs: {[attr for attr in dir(agent) if not attr.startswith('_')][:20]}")
            
            # Check agent's last response
            if hasattr(agent, 'last_response'):
                logger.debug(f"Found 'last_response' on agent")
                response = agent.last_response
                logger.debug(f"Last response type: {type(response)}")
                if hasattr(response, 'usage'):
                    usage = response.usage
                    logger.debug(f"Found usage on last_response: {usage}")
                    if hasattr(usage, 'input_tokens'):
                        token_info['input_tokens'] = usage.input_tokens
                    if hasattr(usage, 'output_tokens'):
                        token_info['output_tokens'] = usage.output_tokens
            
            # Check agent model usage
            if not token_info and hasattr(agent, 'model'):
                logger.debug(f"Checking agent.model...")
                model = agent.model
                logger.debug(f"Model type: {type(model)}")
                logger.debug(f"Model attrs: {[attr for attr in dir(model) if not attr.startswith('_')][:20]}")
                if hasattr(model, 'usage'):
                    usage = model.usage
                    logger.debug(f"Found usage on model: {usage}")
                    if hasattr(usage, 'input_tokens'):
                        token_info['input_tokens'] = usage.input_tokens
                    if hasattr(usage, 'output_tokens'):
                        token_info['output_tokens'] = usage.output_tokens
                        
                # Check if model has last_response
                if hasattr(model, 'last_response'):
                    logger.debug(f"Found 'last_response' on model")
                    response = model.last_response
                    logger.debug(f"Model last_response type: {type(response)}")
                    if hasattr(response, 'usage'):
                        usage = response.usage
                        logger.debug(f"Found usage on model.last_response: {usage}")
                        if hasattr(usage, 'input_tokens'):
                            token_info['input_tokens'] = usage.input_tokens
                        if hasattr(usage, 'output_tokens'):
                            token_info['output_tokens'] = usage.output_tokens
            
            # Check event_loop_metrics on agent
            if not token_info and hasattr(agent, 'event_loop_metrics'):
                logger.debug(f"Found 'event_loop_metrics' on agent")
                metrics = agent.event_loop_metrics
                logger.debug(f"Event loop metrics type: {type(metrics)}")
                logger.debug(f"Event loop metrics: {metrics}")
                
                # Check if it has accumulated_usage attribute
                if hasattr(metrics, 'accumulated_usage'):
                    usage = metrics.accumulated_usage
                    logger.debug(f"Found accumulated_usage: {usage}")
                    if isinstance(usage, dict):
                        # Extract tokens from accumulated usage
                        input_tokens = usage.get('inputTokens', 0)
                        output_tokens = usage.get('outputTokens', 0)
                        
                        # Calculate tokens for this message based on difference from stored totals
                        doc = self.session_repository.collection.find_one(
                            {"_id": self.session_id},
                            {f"agents.{agent.agent_id}.metadata.metrics": 1}
                        )
                        if doc and "agents" in doc and agent.agent_id in doc["agents"]:
                            metrics = doc["agents"][agent.agent_id].get("metadata", {}).get("metrics", {})
                            stored_input = metrics.get('total_input_tokens', 0)
                            stored_output = metrics.get('total_output_tokens', 0)
                            
                            # Calculate the difference (tokens for this interaction)
                            if input_tokens > stored_input:
                                token_info['input_tokens'] = input_tokens - stored_input
                            if output_tokens > stored_output:
                                token_info['output_tokens'] = output_tokens - stored_output
                                
                        logger.debug(f"Extracted tokens from accumulated_usage: {token_info}")
        
        # Try dict-like access for dictionary messages
        if not token_info and isinstance(message, dict):
            logger.debug(f"Message is dict, keys: {list(message.keys())}")
            if 'usage' in message:
                usage = message['usage']
                logger.debug(f"Found 'usage' in dict: {usage}")
                token_info['input_tokens'] = usage.get('input_tokens', usage.get('prompt_tokens'))
                token_info['output_tokens'] = usage.get('output_tokens', usage.get('completion_tokens'))
            elif 'token_usage' in message:
                usage = message['token_usage']  
                token_info['input_tokens'] = usage.get('input_tokens', usage.get('prompt_tokens'))
                token_info['output_tokens'] = usage.get('output_tokens', usage.get('completion_tokens'))
        
        logger.debug(f"Final token_info: {token_info}")
        logger.debug(f"=== End Token Extraction Debug ===")
        
        # Filter out None values
        return {k: v for k, v in token_info.items() if v is not None}
    
    
    def append_message(self, message: Any, agent: Any) -> None:
        """Append a message with automatic timing and metrics tracking."""        
        # Determine message role
        message_role = message.get('role') if isinstance(message, dict) else getattr(message, 'role', None)
        
        # Automatic timing: start timing when user message is appended
        if message_role == 'user':
            self._start_time = time.time()
        
        # Automatic token extraction: try to extract tokens from message/agent
        if message_role == 'assistant':
            token_info = self._extract_token_info(message, agent)
            if token_info:
                # Use extracted tokens if available
                self._last_input_tokens = token_info.get('input_tokens', self._last_input_tokens)
                self._last_output_tokens = token_info.get('output_tokens', self._last_output_tokens)
                
                logger.debug(
                    f"Auto-extracted tokens - Input: {self._last_input_tokens}, "
                    f"Output: {self._last_output_tokens}"
                )
        
        # Initialize agent tracking if not exists
        if agent.agent_id not in self._latest_agent_message:
            self._latest_agent_message[agent.agent_id] = []
        
        # Call parent to append message
        super().append_message(message, agent)
        
        # Calculate latency and add metrics only for assistant responses
        latency_ms = None
        if self._start_time is not None and message_role == 'assistant':
            latency_ms = int((time.time() - self._start_time) * 1000)
            self._start_time = None
        
        if message_role == 'assistant' and any([self._last_input_tokens, self._last_output_tokens, latency_ms]):
            # Get current metrics to update totals
            doc = self.session_repository.collection.find_one(
                {"_id": self.session_id},
                {f"agents.{agent.agent_id}.metadata.metrics": 1,
                 f"agents.{agent.agent_id}.messages": {"$slice": -1}}
            )
            
            if doc and "agents" in doc and agent.agent_id in doc["agents"]:
                agent_doc = doc["agents"][agent.agent_id]
                current_metrics = agent_doc.get("metadata", {}).get("metrics", {})
                messages = agent_doc.get("messages", [])
                
                if messages:
                    last_msg_id = messages[-1]["message_id"]
                    
                    # Add metrics to message using positional operator
                    metrics_update = {}
                    if self._last_input_tokens is not None:
                        metrics_update[f"agents.{agent.agent_id}.messages.$.input_tokens"] = self._last_input_tokens
                    if self._last_output_tokens is not None:
                        metrics_update[f"agents.{agent.agent_id}.messages.$.output_tokens"] = self._last_output_tokens
                    if latency_ms is not None:
                        metrics_update[f"agents.{agent.agent_id}.messages.$.latency_ms"] = latency_ms
                    
                    if metrics_update:
                        self.session_repository.collection.update_one(
                            {
                                "_id": self.session_id,
                                f"agents.{agent.agent_id}.messages.message_id": last_msg_id
                            },
                            {"$set": metrics_update}
                        )
                    
                    # Update token totals
                    if self._last_input_tokens or self._last_output_tokens:
                        total_input = current_metrics.get('total_input_tokens', 0)
                        total_output = current_metrics.get('total_output_tokens', 0)
                        
                        if self._last_input_tokens:
                            total_input += self._last_input_tokens
                        if self._last_output_tokens:
                            total_output += self._last_output_tokens
                        
                        totals_update = {
                            f"agents.{agent.agent_id}.metadata.metrics.total_input_tokens": total_input,
                            f"agents.{agent.agent_id}.metadata.metrics.total_output_tokens": total_output,
                            f"agents.{agent.agent_id}.metadata.metrics.total_tokens": total_input + total_output
                        }
                        
                        self.session_repository.collection.update_one(
                            {"_id": self.session_id},
                            {"$set": totals_update}
                        )
        
        # Reset token counts
        self._last_input_tokens = None
        self._last_output_tokens = None
    
    def check_session_exists(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Check if session exists and optionally retrieve agent metadata.
        
        Args:
            agent_id: Optional specific agent ID to check. If None, returns all agents.
            
        Returns:
            Dictionary with:
            - exists: bool - Whether the session exists
            - agents: dict - Agent metadata keyed by agent_id
            - created_at: datetime - Session creation time (if exists)
            - updated_at: datetime - Last update time (if exists)
        """
        doc = self.session_repository.collection.find_one(
            {"_id": self.session_id}
        )
        
        result = {
            'exists': doc is not None,
            'agents': {},
            'created_at': None,
            'updated_at': None
        }
        
        if doc:
            result['created_at'] = doc.get('created_at')
            result['updated_at'] = doc.get('updated_at')
            
            if "agents" in doc:
                if agent_id:
                    # Only specific agent requested
                    if agent_id in doc["agents"]:
                        agent_data = doc["agents"][agent_id]
                        metadata = agent_data.get("metadata", {})
                        result['agents'][agent_id] = {
                            'model': metadata.get('model'),
                            'name': metadata.get('name'),
                            'description': metadata.get('description'),
                            'system_prompt': metadata.get('system_prompt'),
                            'metrics': metadata.get('metrics', {}),
                            'created_at': agent_data.get('created_at'),
                            'updated_at': agent_data.get('updated_at'),
                            'message_count': len(agent_data.get('messages', []))
                        }
                else:
                    # All agents requested
                    for aid, adata in doc["agents"].items():
                        metadata = adata.get("metadata", {})
                        result['agents'][aid] = {
                            'model': metadata.get('model'),
                            'name': metadata.get('name'),
                            'description': metadata.get('description'),
                            'system_prompt': metadata.get('system_prompt'),
                            'metrics': metadata.get('metrics', {}),
                            'created_at': adata.get('created_at'),
                            'updated_at': adata.get('updated_at'),
                            'message_count': len(adata.get('messages', []))
                        }
        
        return result
    
    def get_metrics_summary(self, agent_id: str) -> Dict[str, Any]:
        """Get a summary of metrics for an agent."""
        # Get full agent document
        doc = self.session_repository.collection.find_one(
            {"_id": self.session_id},
            {f"agents.{agent_id}": 1}
        )
        
        if not doc or "agents" not in doc or agent_id not in doc["agents"]:
            # Try to get from internal cache
            config = self._agent_configs.get(agent_id, {})
            return {
                'model': config.get('model'),
                'system_prompt': config.get('system_prompt'),
                'name': config.get('name'),
                'description': config.get('description'),
                'state': {},
                'total_input_tokens': 0,
                'total_output_tokens': 0,
                'total_tokens': 0,
                'total_messages': 0,
                'messages_with_metrics': 0,
                'average_latency_ms': 0
            }
        
        agent_data = doc["agents"][agent_id]
        agent_info = agent_data.get("agent_data", {})
        metadata = agent_data.get("metadata", {})
        metrics = metadata.get("metrics", {})
        messages = agent_data.get("messages", [])
        
        # Calculate message metrics
        total_messages = len(messages)
        messages_with_metrics = 0
        total_latency = 0
        
        for msg in messages:
            if 'latency_ms' in msg:
                messages_with_metrics += 1
                total_latency += msg['latency_ms']
        
        avg_latency = total_latency / messages_with_metrics if messages_with_metrics > 0 else 0
        
        return {
            'model': metadata.get('model') or self._agent_configs.get(agent_id, {}).get('model'),
            'system_prompt': metadata.get('system_prompt') or self._agent_configs.get(agent_id, {}).get('system_prompt'),
            'name': metadata.get('name') or self._agent_configs.get(agent_id, {}).get('name'),
            'description': metadata.get('description') or self._agent_configs.get(agent_id, {}).get('description'),
            'state': agent_info.get('state', {}),
            'total_input_tokens': metrics.get('total_input_tokens', 0),
            'total_output_tokens': metrics.get('total_output_tokens', 0),
            'total_tokens': metrics.get('total_tokens', 0),
            'total_messages': total_messages,
            'messages_with_metrics': messages_with_metrics,
            'average_latency_ms': avg_latency
        }

    def close(self) -> None:
        """Close the underlying MongoDB connection."""
        # Access the repository through the parent class attribute
        if hasattr(self, 'session_repository') and hasattr(self.session_repository, 'close'):
            self.session_repository.close()


# Convenience factory function
def create_mongodb_session_manager(
    session_id: str,
    connection_string: Optional[str] = None,
    database_name: str = "database_name",
    collection_name: str = "collection_name",
    client: Optional[MongoClient] = None,
    **kwargs: Any,
) -> MongoDBSessionManager:
    """Create an Itzulbira Session Manager with default settings.
    
    Args:
        session_id: Unique identifier for the session
        connection_string: MongoDB connection string (ignored if client is provided)
        database_name: Name of the database
        collection_name: Name of the collection for sessions
        client: Optional pre-configured MongoClient to use
        **kwargs: Additional arguments passed to MongoDBSessionManager
    
    Returns:
        Configured MongoDBSessionManager instance
    """
    return MongoDBSessionManager(
        session_id=session_id,
        connection_string=connection_string,
        database_name=database_name,
        collection_name=collection_name,
        client=client,
        **kwargs
    )