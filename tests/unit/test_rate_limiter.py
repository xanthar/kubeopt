"""
Unit tests for rate limiting functionality.
"""

import pytest
from unittest.mock import patch, MagicMock

from kubeopt_ai.app import create_app
from kubeopt_ai.config import BaseConfig, TestConfig
from kubeopt_ai.extensions import db
from kubeopt_ai.core.rate_limiter import (
    RateLimits,
    rate_limit,
    rate_limit_by_user,
    exempt_from_rate_limit,
    conditional_rate_limit,
    get_rate_limit_key,
    check_rate_limit_bypass,
)


class RateLimitEnabledConfig(TestConfig):
    """Test config with rate limiting enabled."""

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "5/minute"
    RATE_LIMIT_BYPASS_KEY: str = "test-bypass-key"


@pytest.fixture
def app():
    """Create Flask test application with rate limiting disabled."""
    app = create_app(TestConfig())
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def app_with_rate_limit():
    """Create Flask test application with rate limiting enabled."""
    app = create_app(RateLimitEnabledConfig())
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client without rate limiting."""
    return app.test_client()


@pytest.fixture
def client_with_rate_limit(app_with_rate_limit):
    """Create test client with rate limiting enabled."""
    return app_with_rate_limit.test_client()


class TestRateLimits:
    """Tests for RateLimits configuration class."""

    def test_default_limit(self):
        """Test default rate limit value."""
        assert RateLimits.DEFAULT == "100/hour"

    def test_optimize_limit(self):
        """Test optimize rate limit value."""
        assert RateLimits.OPTIMIZE == "10/minute"

    def test_read_limit(self):
        """Test read rate limit value."""
        assert RateLimits.READ == "300/hour"

    def test_export_limit(self):
        """Test export rate limit value."""
        assert RateLimits.EXPORT == "20/hour"

    def test_health_limit(self):
        """Test health check rate limit value."""
        assert RateLimits.HEALTH == "600/hour"


class TestRateLimitDecorators:
    """Tests for rate limiting decorators."""

    def test_rate_limit_decorator_exists(self):
        """Test that rate_limit decorator can be called."""
        decorator = rate_limit("10/minute")
        assert callable(decorator)

    def test_rate_limit_by_user_decorator_exists(self):
        """Test that rate_limit_by_user decorator can be called."""
        decorator = rate_limit_by_user("10/minute")
        assert callable(decorator)

    def test_exempt_decorator_exists(self):
        """Test that exempt_from_rate_limit decorator can be called."""
        decorator = exempt_from_rate_limit()
        assert callable(decorator)

    def test_conditional_rate_limit_decorator_exists(self):
        """Test that conditional_rate_limit decorator can be called."""
        decorator = conditional_rate_limit("10/minute")
        assert callable(decorator)


class TestGetRateLimitKey:
    """Tests for get_rate_limit_key function."""

    def test_get_key_without_user(self, app):
        """Test key generation without authenticated user."""
        with app.test_request_context("/test", headers={}):
            key = get_rate_limit_key()
            # Should return IP address or 'unknown'
            assert key is not None

    def test_get_key_with_user(self, app):
        """Test key generation with authenticated user."""
        with app.test_request_context("/test"):
            from flask import g
            g.user_id = "user-123"
            key = get_rate_limit_key()
            assert key == "user:user-123"

    def test_get_key_with_forwarded_header(self, app):
        """Test key generation with X-Forwarded-For header."""
        with app.test_request_context(
            "/test",
            headers={"X-Forwarded-For": "203.0.113.1, 198.51.100.1"}
        ):
            key = get_rate_limit_key()
            assert key == "203.0.113.1"


class TestCheckRateLimitBypass:
    """Tests for check_rate_limit_bypass function."""

    def test_bypass_disabled_rate_limiting(self, app):
        """Test bypass when rate limiting is disabled."""
        with app.test_request_context("/test"):
            # TestConfig has RATE_LIMIT_ENABLED = False
            assert check_rate_limit_bypass() is True

    def test_bypass_with_valid_key(self, app_with_rate_limit):
        """Test bypass with valid bypass key."""
        with app_with_rate_limit.test_request_context(
            "/test",
            headers={"X-RateLimit-Bypass": "test-bypass-key"}
        ):
            assert check_rate_limit_bypass() is True

    def test_no_bypass_with_invalid_key(self, app_with_rate_limit):
        """Test no bypass with invalid key."""
        with app_with_rate_limit.test_request_context(
            "/test",
            headers={"X-RateLimit-Bypass": "wrong-key"}
        ):
            assert check_rate_limit_bypass() is False

    def test_no_bypass_without_key(self, app_with_rate_limit):
        """Test no bypass without bypass key header."""
        with app_with_rate_limit.test_request_context("/test"):
            assert check_rate_limit_bypass() is False


class TestRateLimitAPI:
    """Tests for rate limiting on API endpoints."""

    def test_health_endpoint_without_rate_limit(self, client):
        """Test health endpoint works without rate limiting."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_audit_endpoint_without_rate_limit(self, client):
        """Test audit endpoint works without rate limiting."""
        response = client.get("/api/v1/audit/logs")
        assert response.status_code == 200

    def test_429_error_handler_registered(self, app):
        """Test that 429 error handler is registered."""
        # Verify the error handler is registered
        error_handlers = app.error_handler_spec.get(None, {})
        assert 429 in error_handlers, "429 error handler should be registered"


class TestRateLimitConfiguration:
    """Tests for rate limit configuration."""

    def test_config_rate_limit_enabled_default(self):
        """Test default rate limit enabled setting."""
        config = BaseConfig()
        # Default is True from env, but we set RATE_LIMIT_ENABLED env might be unset
        assert hasattr(config, "RATE_LIMIT_ENABLED")

    def test_config_rate_limit_default(self):
        """Test default rate limit value."""
        config = BaseConfig()
        assert config.RATE_LIMIT_DEFAULT == "100/hour"

    def test_config_rate_limit_storage_url(self):
        """Test default rate limit storage URL."""
        config = BaseConfig()
        assert config.RATE_LIMIT_STORAGE_URL == "memory://"

    def test_test_config_rate_limit_disabled(self):
        """Test that rate limiting is disabled in test config."""
        config = TestConfig()
        assert config.RATE_LIMIT_ENABLED is False


class TestRateLimitIntegration:
    """Integration tests for rate limiting with the application."""

    def test_app_initializes_with_rate_limit_disabled(self, app):
        """Test that app initializes correctly with rate limiting disabled."""
        assert app.config["RATE_LIMIT_ENABLED"] is False

    def test_app_initializes_with_rate_limit_enabled(self, app_with_rate_limit):
        """Test that app initializes correctly with rate limiting enabled."""
        assert app_with_rate_limit.config["RATE_LIMIT_ENABLED"] is True

    def test_bypass_key_in_config(self, app_with_rate_limit):
        """Test that bypass key is set in config."""
        assert app_with_rate_limit.config["RATE_LIMIT_BYPASS_KEY"] == "test-bypass-key"

    def test_multiple_requests_without_rate_limit(self, client):
        """Test that multiple requests work without rate limiting."""
        # Make 20 requests - should all succeed
        for _ in range(20):
            response = client.get("/api/v1/health")
            assert response.status_code == 200
