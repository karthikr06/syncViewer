"""Tool-level evals (no API key needed). Answers derive from the generator's ground truth."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.agent.evals.cases import EVAL_CASES, EvalContext
from app.collector.adapters import MockAdapter
from app.collector.cycle import run_cycle
from app.models import CloudAccount, Resource, User, Workspace
from tests.conftest import alembic_cfg
from tests.test_collector import make_settings


@pytest.fixture(scope="module")
def ctx(make_database):
    from syncgen.main import app as gen_app

    url = make_database()
    command.upgrade(alembic_cfg(url), "head")
    engine = create_engine(url, connect_args={"prepare_threshold": None})
    factory = sessionmaker(engine, expire_on_commit=False)
    owner, other = uuid.uuid4(), uuid.uuid4()
    with factory() as s:
        # each user's workspace shares their id, so `owner` is also the workspace id
        s.add_all([Workspace(id=owner, name="o"), Workspace(id=other, name="p")])
        s.flush()
        s.add_all([User(id=owner, email="o@x.com", workspace_id=owner),
                   User(id=other, email="p@x.com", workspace_id=other)])
        s.flush()
        s.add(CloudAccount(workspace_id=owner, provider_id=4, name="m", external_ref="eval-acc",
                           config={"scenario": "medium"}))
        s.commit()
    client = TestClient(gen_app)
    adapter = MockAdapter("http://testserver", client=client)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    run_cycle(factory, make_settings(), lambda code: adapter, now=now, backfill_hours=24 * 7)
    truth = client.get("/v1/accounts/eval-acc/ground-truth", params={
        "scenario": "medium", "start": (now - timedelta(days=7)).isoformat(),
        "end": now.isoformat()}).json()
    session = factory()
    names = {r.external_id: r.name for r in session.scalars(select(Resource))}
    by_role: dict[str, list[str]] = {}
    for r in truth["resources"]:
        by_role.setdefault(r["role"], []).append(names[r["id"]])
    yield EvalContext(session, owner, other, truth, names, by_role)
    session.close()
    engine.dispose()


def test_there_are_at_least_15_cases():
    assert len(EVAL_CASES) >= 15


@pytest.mark.parametrize("case", EVAL_CASES, ids=[c.id for c in EVAL_CASES])
def test_tools_answer_correctly(ctx, case):
    case.check_tools(ctx)
    ctx.session.rollback()
