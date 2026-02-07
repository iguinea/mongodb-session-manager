"""Configuration management for Session Viewer Backend.

This module handles all configuration via environment variables,
providing defaults for development and requiring explicit configuration
for production deployments.

In production (AWS App Runner), the DOCUMENTDB_SECRET environment variable
contains the full JSON secret from AWS Secrets Manager with fields:
- username, password, host, port, ssl, engine, dbClusterIdentifier

The connection string is built from these fields following the same pattern
as the MCP and Virtual Agent services.
"""

import os
import json
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import model_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # MongoDB Configuration
    mongodb_connection_string: Optional[str] = (
        None  # Optional - will be built from DOCUMENTDB_SECRET if not provided
    )
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
    allowed_origins_str: str = (
        "http://localhost:8883,http://127.0.0.1:8883,http://0.0.0.0:8883"
    )

    @property
    def allowed_origins(self) -> List[str]:
        """Parse allowed_origins from comma-separated string."""
        return [origin.strip() for origin in self.allowed_origins_str.split(",")]

    # Pagination Settings
    default_page_size: int = 20
    max_page_size: int = 100

    # Logging Configuration
    log_level: str = "INFO"
    # Structured Logging (JSON format for CloudWatch)
    # Set to "json" for production (CloudWatch Insights compatible)
    # Set to "text" for development (human-readable)
    log_format: str = "text"
    # Service identification for structured logs
    log_service_name: str = "session-viewer-backend"
    log_environment: str = "development"

    # Authentication
    # SECURITY: No default password - must be set via SESSION_VIEWER_BACKEND_PASSWORD env var
    # If not set, a random secure password will be generated and logged (development only)
    backend_password: Optional[str] = None

    # Dynamic Filter Configuration
    enum_fields_str: str = ""
    enum_max_values: int = 50

    # Rate Limiting Configuration (CWE-307 Prevention)
    # Format: "{count}/{period}" where period is: second, minute, hour, day
    rate_limit_auth: str = "5/minute"       # Authentication endpoints - strict
    rate_limit_search: str = "30/minute"    # Search endpoints - moderate
    rate_limit_read: str = "60/minute"      # Read endpoints - permissive
    rate_limit_metadata: str = "10/minute"  # Metadata endpoints - cached in frontend

    # Security Headers Configuration (CWE-693 Prevention)
    # Set to "false" to disable security headers (not recommended)
    security_headers_enabled: bool = True

    # X-Frame-Options: DENY | SAMEORIGIN | ALLOW-FROM uri
    x_frame_options: str = "DENY"

    # Content-Security-Policy (CSP)
    # Allows scripts/styles from CDNs used by frontend (Tailwind, day.js, etc.)
    content_security_policy: str = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "img-src 'self' data:; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'"
    )

    # Referrer-Policy: no-referrer | same-origin | strict-origin-when-cross-origin | etc.
    referrer_policy: str = "strict-origin-when-cross-origin"

    # Permissions-Policy (formerly Feature-Policy)
    permissions_policy: str = "geolocation=(), microphone=(), camera=(), payment=()"

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

    @model_validator(mode="after")
    def build_connection_string_from_secret(self):
        """Build MongoDB connection string from DOCUMENTDB_SECRET JSON if not already provided.

        In production (AWS App Runner), DOCUMENTDB_SECRET contains the full JSON secret
        with username, password, host, port, ssl, engine, dbClusterIdentifier.

        In development, mongodb_connection_string is provided directly via .env file.
        """
        # If connection string is already provided, use it as-is
        if self.mongodb_connection_string:
            return self

        # Try to build connection string from DOCUMENTDB_SECRET (production)
        documentdb_secret = os.getenv("DOCUMENTDB_SECRET")
        if documentdb_secret:
            try:
                secret_data = json.loads(documentdb_secret)
                ssl = os.getenv("SET_MONGODB_SSL", "true").lower()
                self.mongodb_connection_string = (
                    "mongodb://"
                    + secret_data["username"]
                    + ":"
                    + secret_data["password"]
                    + "@"
                    + secret_data["host"]
                    + ":"
                    + str(secret_data["port"])
                    + f"/?ssl={ssl}&retryWrites=false"
                )
                print(
                    "MongoDB/DocumentDB connection string built from DOCUMENTDB_SECRET"
                )
                return self

            except (json.JSONDecodeError, KeyError) as e:
                print(f"Failed to parse DOCUMENTDB_SECRET: {e}")
                print("Falling back to default connection string")

        # Use default development connection string if nothing else worked
        if not self.mongodb_connection_string:
            self.mongodb_connection_string = (  # noqa: S105
                "mongodb://mongodb:mongodb@localhost:8550/"
            )
            print("Using default development MongoDB connection string")

        return self

    @model_validator(mode="after")
    def validate_backend_password(self):
        """Generate secure random password if not provided.

        SECURITY: In production, SESSION_VIEWER_BACKEND_PASSWORD MUST be set.
        In development, a random secure password is generated and logged.
        """
        import secrets
        import string

        if not self.backend_password:
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
            random_password = "".join(secrets.choice(alphabet) for _ in range(20))
            self.backend_password = random_password

            print("WARNING: No SESSION_VIEWER_BACKEND_PASSWORD configured!")
            print(
                f"Using auto-generated password: {random_password}"
            )
            print("For production, set SESSION_VIEWER_BACKEND_PASSWORD environment variable")
            print("This password will change on every restart!")

        if len(self.backend_password) < 8:
            print("WARNING: Password is too short (minimum 8 characters recommended)")

        return self

    class Config:
        """Pydantic configuration."""

        env_prefix = "SESSION_VIEWER_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
