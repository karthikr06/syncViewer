import os

from sqlalchemy import create_engine

from alembic import context
from app.core.config import normalize_db_url  # also loads the repo-root .env
from app.models import Base

target_metadata = Base.metadata


def _url() -> str:
    url = (
        context.config.get_main_option("sqlalchemy.url")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        raise RuntimeError("Set MIGRATION_DATABASE_URL (or DATABASE_URL) in .env to run migrations")
    return normalize_db_url(url)


def run_migrations_online() -> None:
    engine = create_engine(_url(), connect_args={"prepare_threshold": None})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
