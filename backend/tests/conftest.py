import sys
import tempfile
import uuid
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alembic import command

BACKEND = Path(__file__).resolve().parent.parent
# the generator is a standalone project; tests import it as an in-process fake cloud
sys.path.insert(0, str(BACKEND.parent / "generator"))


def to_sa_url(uri: str) -> str:
    return uri.replace("postgresql://", "postgresql+psycopg://", 1)


def alembic_cfg(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def pg_server():
    import pgembed

    server = pgembed.get_server(tempfile.mkdtemp(prefix="syncviewer_pg_"), cleanup_mode="delete")
    yield server


@pytest.fixture(scope="session")
def make_database(pg_server):
    """Factory: create a fresh empty database and return its SQLAlchemy URL."""
    base = pg_server.get_uri()

    def _make() -> str:
        name = "t_" + uuid.uuid4().hex[:10]
        with psycopg.connect(base, autocommit=True) as c:
            c.execute(f'CREATE DATABASE "{name}"')
        return to_sa_url(base.rsplit("/", 1)[0] + "/" + name)

    return _make


@pytest.fixture(scope="session")
def migrated_url(make_database):
    url = make_database()
    command.upgrade(alembic_cfg(url), "head")
    return url


@pytest.fixture(scope="session")
def engine(migrated_url):
    eng = create_engine(migrated_url, connect_args={"prepare_threshold": None})
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Per-test session rolled back at the end (savepoints let tests catch DB errors)."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield s
    s.close()
    trans.rollback()
    conn.close()
