"""Environment-driven settings. Fails fast with a list of every missing variable."""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Repo-root .env for local runs; real environment variables (Docker, hosting) always win.
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)


def normalize_db_url(url: str) -> str:
    """Accept the plain URL Supabase shows and select the psycopg 3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class ConfigError(RuntimeError):
    pass


def _require(names: list[str]) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise ConfigError("Missing required environment variables: " + ", ".join(missing))
    return {n: os.environ[n] for n in names}


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    supabase_jwks_url: str
    supabase_jwt_secret: str
    cors_origins: list[str]
    admin_emails: list[str]
    credential_encryption_key: str
    collect_interval_seconds: int
    raw_retention_days: int
    generator_url: str
    generator_api_key: str
    google_api_key: str
    gemini_model: str
    migration_database_url: str = field(default="")
    supabase_url: str = field(default="")
    sync_overlap: int = field(default=500)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def load_settings(required: list[str] | None = None) -> Settings:
    """`required` lets each entrypoint demand only what it needs (e.g. the generator needs none)."""
    required = required if required is not None else [
        "DATABASE_URL",
        "SUPABASE_JWKS_URL",
        "CREDENTIAL_ENCRYPTION_KEY",
    ]
    _require(required)
    env = os.environ.get
    return Settings(
        app_env=env("APP_ENV", "development"),
        database_url=normalize_db_url(env("DATABASE_URL", "")),
        migration_database_url=normalize_db_url(env("MIGRATION_DATABASE_URL", "")),
        supabase_url=env("SUPABASE_URL", "").rstrip("/"),
        supabase_jwks_url=env("SUPABASE_JWKS_URL", ""),
        supabase_jwt_secret=env("SUPABASE_JWT_SECRET", ""),
        cors_origins=_split(env("CORS_ORIGINS", "")),
        admin_emails=[e.lower() for e in _split(env("ADMIN_EMAILS", ""))],
        credential_encryption_key=env("CREDENTIAL_ENCRYPTION_KEY", ""),
        collect_interval_seconds=int(env("COLLECT_INTERVAL_SECONDS", "300")),
        raw_retention_days=int(env("RAW_RETENTION_DAYS", "14")),
        generator_url=env("GENERATOR_URL", "http://generator:8100"),
        generator_api_key=env("GENERATOR_API_KEY", ""),
        google_api_key=env("GOOGLE_API_KEY", ""),
        gemini_model=env("GEMINI_MODEL", "gemini-2.5-flash"),
    )


def load_settings_or_exit(required: list[str] | None = None) -> Settings:
    try:
        return load_settings(required)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
