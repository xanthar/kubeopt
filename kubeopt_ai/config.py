"""
Configuration module for KubeOpt AI.

Implements a Config class pattern with environment-based settings.
All configuration is read from environment variables following twelve-factor app principles.
"""

import os
from typing import Optional


class BaseConfig:
    """Base configuration with defaults for all environments."""

    # Flask settings
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")
    DEBUG: bool = False
    TESTING: bool = False

    # Database settings
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://kubeopt:kubeopt@localhost:5432/kubeopt"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # Prometheus settings
    PROMETHEUS_BASE_URL: str = os.environ.get(
        "PROMETHEUS_BASE_URL",
        "http://prometheus:9090"
    )
    PROMETHEUS_TIMEOUT: int = int(os.environ.get("PROMETHEUS_TIMEOUT", "30"))

    # Metrics collection settings
    DEFAULT_LOOKBACK_DAYS: int = int(os.environ.get("KUBEOPT_DEFAULT_LOOKBACK_DAYS", "7"))

    # LLM settings
    LLM_API_KEY: Optional[str] = os.environ.get("LLM_API_KEY")
    LLM_MODEL_NAME: str = os.environ.get("LLM_MODEL_NAME", "claude-sonnet-4-20250514")
    LLM_API_BASE_URL: str = os.environ.get(
        "LLM_API_BASE_URL",
        "https://api.anthropic.com/v1"
    )
    LLM_MAX_TOKENS: int = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
    LLM_RETRY_ATTEMPTS: int = int(os.environ.get("LLM_RETRY_ATTEMPTS", "3"))

    # Application settings
    JSON_SORT_KEYS: bool = False
    MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024  # 16MB max request size

    # Logging
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "json"  # 'json' or 'text'


class DevConfig(BaseConfig):
    """Development configuration."""

    DEBUG: bool = True
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "DEBUG")
    LOG_FORMAT: str = "text"


class TestConfig(BaseConfig):
    """Testing configuration."""

    TESTING: bool = True
    DEBUG: bool = True

    # Use SQLite for tests by default
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        "sqlite:///:memory:"
    )

    # Shorter timeouts for tests
    PROMETHEUS_TIMEOUT: int = 5
    LLM_RETRY_ATTEMPTS: int = 1


class ProdConfig(BaseConfig):
    """Production configuration."""

    DEBUG: bool = False

    # Production requires a real secret key
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "")

    @classmethod
    def validate(cls) -> None:
        """Validate production configuration."""
        if not cls.SECRET_KEY:
            raise ValueError("SECRET_KEY must be set in production")
        if not cls.LLM_API_KEY:
            raise ValueError("LLM_API_KEY must be set in production")
        if cls.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
            raise ValueError("SQLite is not supported in production")


# Configuration mapping
config_by_name: dict[str, type[BaseConfig]] = {
    "development": DevConfig,
    "dev": DevConfig,
    "testing": TestConfig,
    "test": TestConfig,
    "production": ProdConfig,
    "prod": ProdConfig,
}


def get_config() -> BaseConfig:
    """Get configuration based on FLASK_ENV environment variable."""
    env = os.environ.get("FLASK_ENV", "development").lower()
    config_class = config_by_name.get(env, DevConfig)

    if config_class == ProdConfig:
        ProdConfig.validate()

    return config_class()
