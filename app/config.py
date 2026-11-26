"""Configuration objects for the Campus IT Helpdesk application.

All runtime settings come from environment variables so the same image can be
promoted from staging to production without a rebuild (12-factor principle).
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _bool_env(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Base configuration used by every environment."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
    SEED_FILE = os.environ.get("SEED_FILE", str(BASE_DIR / "data" / "seed_tickets.json"))
    DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "helpdesk123")

    APP_VERSION = os.environ.get("APP_VERSION", "1.0.0")
    GIT_SHA = os.environ.get("GIT_SHA", "local")
    BUILD_TIME = os.environ.get("BUILD_TIME", "unknown")
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    CSRF_ENABLED = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool_env("SESSION_COOKIE_SECURE", "0")
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024

    JSON_SORT_KEYS = False


class TestConfig(Config):
    """Configuration used by the automated test suite."""

    TESTING = True
    SECRET_KEY = "test-secret-key"
    CSRF_ENABLED = False
    LOG_LEVEL = "WARNING"


class ProductionConfig(Config):
    """Hardened configuration for deployed environments."""

    ENVIRONMENT = "production"
    SESSION_COOKIE_SECURE = True
