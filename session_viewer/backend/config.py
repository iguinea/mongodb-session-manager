"""Configuration management for Session Viewer Backend.

This module handles all configuration via environment variables,
providing defaults for development and requiring explicit configuration
for production deployments.
"""

import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # MongoDB Configuration
    mongodb_connection_string: str = "mongodb://mongodb:mongodb@mongodb_session_manager-mongodb:27017/"
    database_name: str = "examples"
    collection_name: str = "sessions"

    # Connection Pool Settings
    max_pool_size: int = 100
    min_pool_size: int = 10
    max_idle_time_ms: int = 30000

    # Backend Server Configuration
    backend_host: str = "0.0.0.0"
    backend_port: int = 8882

    # CORS Configuration
    frontend_url: str = "http://localhost:8883"
    allowed_origins_str: str = "http://localhost:8883,http://127.0.0.1:8883,http://0.0.0.0:8883"

    @property
    def allowed_origins(self) -> List[str]:
        """Parse allowed_origins from comma-separated string."""
        return [origin.strip() for origin in self.allowed_origins_str.split(",")]

    # Pagination Settings
    default_page_size: int = 20
    max_page_size: int = 100

    # Logging Configuration
    log_level: str = "INFO"

    # Authentication
    backend_password: str = "123456"

    # Dynamic Filter Configuration
    enum_fields_str: str = ""
    enum_max_values: int = 50

    @property
    def enum_fields(self) -> List[str]:
        """Parse enum fields from comma-separated string.

        Returns:
            List of field names configured as enums.

        Example:
            ENUM_FIELDS_STR="metadata.status,metadata.priority"
            Returns: ["metadata.status", "metadata.priority"]
        """
        if not self.enum_fields_str:
            return []
        return [field.strip() for field in self.enum_fields_str.split(",")]

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
