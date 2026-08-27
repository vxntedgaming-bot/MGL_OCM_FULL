"""Environment helpers for MGL settings. Keep this module free of Django imports."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

TRUE_VALUES = {"1", "true", "yes", "on"}
POSTGRES_SCHEMES = {"postgres", "postgresql"}


def load_project_env(base_dir: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(base_dir / ".env", override=False)


def env_str(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return default if value == "" else value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in TRUE_VALUES


def env_csv(name: str, default: list[str] | None = None) -> list[str]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return list(default or [])
    return [part.strip() for part in value.split(",") if part.strip()]


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return int(value.strip())


def parse_database_url(url: str) -> dict:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").split("+", 1)[0]
    if scheme not in POSTGRES_SCHEMES:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")
    name = unquote(parsed.path.lstrip("/"))
    if not name:
        raise ValueError("DATABASE_URL must include a database name")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or "5432"),
        "CONN_MAX_AGE": env_int("DATABASE_CONN_MAX_AGE", 60),
    }


def sqlite_config(base_dir: Path) -> dict:
    name = env_str("SQLITE_PATH")
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(name) if name else base_dir / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }


def postgres_config_from_parts() -> dict:
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("POSTGRES_DB", "mgl"),
        "USER": env_str("POSTGRES_USER", "mgl"),
        "PASSWORD": env_str("POSTGRES_PASSWORD", ""),
        "HOST": env_str("POSTGRES_HOST", "localhost"),
        "PORT": env_str("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_int("DATABASE_CONN_MAX_AGE", 60),
    }


def database_config(base_dir: Path) -> dict:
    database_url = env_str("DATABASE_URL")
    if database_url:
        return parse_database_url(database_url)
    if env_str("POSTGRES_DB") or env_str("POSTGRES_HOST"):
        return postgres_config_from_parts()
    return sqlite_config(base_dir)
