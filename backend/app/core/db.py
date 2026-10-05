from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    # prepare_threshold=None: safe behind Supabase's transaction-mode pooler.
    return create_engine(url, pool_pre_ping=True, connect_args={"prepare_threshold": None})


@lru_cache
def _engine_and_factory(url: str):
    engine = make_engine(url)
    return engine, sessionmaker(engine, expire_on_commit=False)


def get_session_factory(url: str) -> sessionmaker[Session]:
    return _engine_and_factory(url)[1]
