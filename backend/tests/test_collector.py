import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.collector.adapters import MockAdapter, get_adapter
from app.collector.adapters.stubs import AwsAdapter
from app.collector.cycle import run_cycle
from app.collector.dto import ResourceDTO
from app.core.config import Settings
from app.core.crypto import decrypt_credentials, encrypt_credentials
from app.models import (
    Alert,
    AlertRule,
    CloudAccount,
    CollectorRun,
    Incident,
    MetricSample,
    Recommendation,
    Resource,
    UptimeRollup,
    User,
    Workspace,
)
from tests.conftest import alembic_cfg

NOW = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
FERNET_KEY = "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg="


def make_settings(**kw) -> Settings:
    base = dict(app_env="test", database_url="", supabase_jwks_url="", supabase_jwt_secret="",
                cors_origins=[], admin_emails=[], credential_encryption_key=FERNET_KEY,
                collect_interval_seconds=300, raw_retention_days=14,
                generator_url="http://testserver", generator_api_key="", google_api_key="",
                gemini_model="x")
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def gen_client():
    from syncgen.main import app as gen_app

    return TestClient(gen_app)


@pytest.fixture
def adapter_factory(gen_client):
    mock = MockAdapter("http://testserver", client=gen_client)

    def factory(code):
        return mock if code == "mock" else get_adapter(code, make_settings())

    return factory


@pytest.fixture
def db(make_database):
    """Fresh migrated database per test (the collector commits, so no rollback trick)."""
    url = make_database()
    command.upgrade(alembic_cfg(url), "head")
    engine = create_engine(url, connect_args={"prepare_threshold": None})
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def add_account(factory, owner_id, ref, scenario="small", provider_id=4, name=None):
    with factory() as s:
        if s.get(User, owner_id) is None:  # the owner's workspace shares their id
            s.add(Workspace(id=owner_id, name="ws"))
            s.flush()
            s.add(User(id=owner_id, email=f"{owner_id}@x.com", workspace_id=owner_id))
            s.flush()
        acc = CloudAccount(workspace_id=owner_id, provider_id=provider_id, name=name or ref,
                           external_ref=ref, config={"scenario": scenario})
        s.add(acc)
        s.commit()
        return acc.id


def count(factory, model):
    with factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def ground_truth(client, ref, scenario, start, end):
    r = client.get(f"/v1/accounts/{ref}/ground-truth",
                   params={"scenario": scenario, "start": start.isoformat(),
                           "end": end.isoformat()})
    return r.json()


def test_cycle_fills_samples_and_rollups(db, adapter_factory):
    owner = uuid.uuid4()
    acc_id = add_account(db, owner, "acc-a")
    result = run_cycle(db, make_settings(), adapter_factory, now=NOW)
    assert result.accounts_processed == 1 and not result.errors
    assert result.samples_inserted > 0
    assert count(db, Resource) == 5
    assert count(db, UptimeRollup) > 0
    with db() as s:
        acc = s.get(CloudAccount, acc_id)
        assert acc.last_collected_at == NOW and acc.last_error is None
        run = s.scalars(select(CollectorRun)).one()
        assert run.finished_at is not None and run.accounts_processed == 1 and run.errors == 0
        assert run.samples_inserted == result.samples_inserted


def test_second_run_creates_no_duplicates(db, adapter_factory):
    add_account(db, uuid.uuid4(), "acc-a")
    first = run_cycle(db, make_settings(), adapter_factory, now=NOW)
    n = count(db, MetricSample)
    again = run_cycle(db, make_settings(), adapter_factory, now=NOW)
    assert again.samples_inserted == 0 and count(db, MetricSample) == n
    later = run_cycle(db, make_settings(), adapter_factory, now=NOW + timedelta(hours=1))
    assert 0 < later.samples_inserted < first.samples_inserted
    # overlap re-fetched but nothing duplicated: rows == distinct keys by construction (PK)
    assert count(db, MetricSample) == n + later.samples_inserted
    assert count(db, Resource) == 5


def test_broken_account_does_not_stop_others(db, adapter_factory):
    owner = uuid.uuid4()
    good1 = add_account(db, owner, "acc-good1")
    broken = add_account(db, owner, "sub-azure", provider_id=1)  # Azure adapter: stub
    good2 = add_account(db, uuid.uuid4(), "acc-good2")
    result = run_cycle(db, make_settings(), adapter_factory, now=NOW)
    assert result.accounts_processed == 2 and len(result.errors) == 1
    with db() as s:
        bad = s.get(CloudAccount, broken)
        assert bad.status == "error" and "not implemented" in bad.last_error
        for gid in (good1, good2):
            assert s.get(CloudAccount, gid).last_collected_at == NOW
        run = s.scalars(select(CollectorRun)).one()
        assert run.errors == 1 and run.error_details[0]["account_id"] == str(broken)


def test_errored_account_recovers(db, adapter_factory):
    acc = add_account(db, uuid.uuid4(), "acc-a")
    with db() as s:
        a = s.get(CloudAccount, acc)
        a.status, a.last_error = "error", "boom"
        s.commit()
    run_cycle(db, make_settings(), adapter_factory, now=NOW)
    with db() as s:
        a = s.get(CloudAccount, acc)
        assert a.status == "active" and a.last_error is None


def test_paused_and_deleted_accounts_skipped(db, adapter_factory):
    owner = uuid.uuid4()
    paused = add_account(db, owner, "p")
    deleted = add_account(db, owner, "d")
    with db() as s:
        s.get(CloudAccount, paused).status = "paused"
        s.get(CloudAccount, deleted).deleted_at = NOW
        s.commit()
    result = run_cycle(db, make_settings(), adapter_factory, now=NOW)
    assert result.accounts_processed == 0 and count(db, Resource) == 0


def test_incidents_match_ground_truth(db, adapter_factory, gen_client):
    add_account(db, uuid.uuid4(), "acc-m", scenario="medium")
    run_cycle(db, make_settings(), adapter_factory, now=NOW, backfill_hours=72)
    start = NOW - timedelta(hours=72, minutes=15)
    gt = ground_truth(gen_client, "acc-m", "medium", start, NOW)
    roles = {r["id"]: r["role"] for r in gt["resources"]}
    trusted_from, trusted_to = start + timedelta(hours=1), NOW - timedelta(hours=1)

    def parse(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    expected = {(f["resource_id"], parse(f["start"])) for f in gt["faults"]
                if f["kind"] == "outage" and trusted_from <= parse(f["start"])
                and parse(f["end"]) <= trusted_to}
    assert len(expected) > 10
    with db() as s:
        ext = {r.id: r.external_id for r in s.scalars(select(Resource))}
        incidents = s.scalars(select(Incident)).all()
        got = {(ext[i.resource_id], i.started_at) for i in incidents
               if trusted_from <= i.started_at and (i.ended_at and i.ended_at <= trusted_to)}
        assert got == expected
        ends = {(ext[i.resource_id], i.started_at): i.ended_at for i in incidents}
        for f in gt["faults"]:
            key = (f["resource_id"], parse(f["start"]))
            if f["kind"] == "outage" and key in expected:
                assert ends[key] == parse(f["end"])
        # unresponsive VM: one open incident; stopped VM: none
        unresp = next(i for i, r in roles.items() if r == "unresponsive")
        stopped = next(i for i, r in roles.items() if r == "stopped")
        assert [i.ended_at for i in incidents if ext[i.resource_id] == unresp] == [None]
        assert not [i for i in incidents if ext[i.resource_id] == stopped]


def test_open_incident_closed_on_recovery(db, adapter_factory, gen_client):
    """Cycle ends mid-outage -> open incident; a later cycle closes it with the true end."""
    add_account(db, uuid.uuid4(), "acc-m", scenario="medium")
    start = NOW - timedelta(days=2)
    gt = ground_truth(gen_client, "acc-m", "medium", start, NOW + timedelta(days=1))
    out = next(f for f in gt["faults"] if f["kind"] == "outage"
               and datetime.fromisoformat(f["start"].replace("Z", "+00:00")) > start
               and f["recurring"] is False)
    o_start = datetime.fromisoformat(out["start"].replace("Z", "+00:00"))
    o_end = datetime.fromisoformat(out["end"].replace("Z", "+00:00"))
    mid = o_start + timedelta(minutes=((o_end - o_start).total_seconds() // 60) // 2 + 1)
    run_cycle(db, make_settings(), adapter_factory, now=mid, backfill_hours=48)
    with db() as s:
        ext = {r.id: r.external_id for r in s.scalars(select(Resource))}
        open_ = [i for i in s.scalars(select(Incident)) if ext[i.resource_id] == out["resource_id"]
                 and i.started_at == o_start]
        assert len(open_) == 1 and open_[0].ended_at is None
    run_cycle(db, make_settings(), adapter_factory, now=o_end + timedelta(minutes=30))
    with db() as s:
        inc = [i for i in s.scalars(select(Incident)) if ext[i.resource_id] == out["resource_id"]
               and i.started_at == o_start]
        assert len(inc) == 1 and inc[0].ended_at == o_end


def test_alert_rules_open_once_and_target_right_vms(db, adapter_factory, gen_client):
    owner = uuid.uuid4()
    add_account(db, owner, "acc-m", scenario="medium")
    with db() as s:
        s.add(AlertRule(workspace_id=owner, name="low cpu", metric_id=2, operator="<", threshold=10,
                        duration_minutes=60, severity="info"))
        s.commit()
    run_cycle(db, make_settings(), adapter_factory, now=NOW, backfill_hours=24)
    gt = ground_truth(gen_client, "acc-m", "medium", NOW - timedelta(days=1), NOW)
    idle = {r["id"] for r in gt["resources"] if r["role"] == "idle"}
    with db() as s:
        ext = {r.id: r.external_id for r in s.scalars(select(Resource))}
        alerts = s.scalars(select(Alert)).all()
        assert {ext[a.resource_id] for a in alerts} == idle and len(idle) >= 2
        assert all(a.state == "open" and a.value_at_open < 10 for a in alerts)
    run_cycle(db, make_settings(), adapter_factory, now=NOW + timedelta(minutes=30))
    assert count(db, Alert) == len(idle)  # not duplicated


def test_alert_resolves_when_condition_clears(session):
    from app.services.alert_eval import evaluate_rules

    ws = Workspace(name="ws")
    session.add(ws)
    session.flush()
    owner = User(id=uuid.uuid4(), email="r@x.com", workspace_id=ws.id)
    session.add(owner)
    session.flush()
    acc = CloudAccount(workspace_id=ws.id, provider_id=4, name="a", external_ref="r")
    session.add(acc)
    session.flush()
    res = Resource(account_id=acc.id, type_id=4, external_id="v", name="v", power_state="running")
    session.add(res)
    session.add(AlertRule(workspace_id=ws.id, name="hot", metric_id=2, operator=">", threshold=80))
    session.flush()
    t0 = NOW

    def sample(minutes, v):
        session.add(MetricSample(resource_id=res.id, metric_id=2,
                                 ts=t0 + timedelta(minutes=minutes), value=v))
        session.flush()

    codes = {2: "cpu_percent"}
    sample(0, 95)
    sample(5, 96)
    evaluate_rules(session, ws.id, acc.id, [res], codes, t0 + timedelta(minutes=6))
    alert = session.scalars(select(Alert)).one()
    assert alert.state == "open" and alert.value_at_open == 96
    sample(10, 20)
    sample(15, 25)
    evaluate_rules(session, ws.id, acc.id, [res], codes, t0 + timedelta(minutes=16))
    session.refresh(alert)
    assert alert.state == "resolved" and alert.resolved_at is not None


def test_recommendations_per_rule(db, adapter_factory, gen_client):
    owner = uuid.uuid4()
    add_account(db, owner, "acc-m", scenario="medium")
    run_cycle(db, make_settings(), adapter_factory, now=NOW, backfill_hours=24 * 7)
    gt = ground_truth(gen_client, "acc-m", "medium", NOW - timedelta(days=7), NOW)
    role = {r["id"]: r["role"] for r in gt["resources"]}
    with db() as s:
        ext = {r.id: r.external_id for r in s.scalars(select(Resource))}
        recs = s.scalars(select(Recommendation)).all()
        by_cat: dict[str, set[str]] = {}
        for r in recs:
            by_cat.setdefault(r.category, set()).add(role[ext[r.resource_id]] if r.resource_id
                                                     else "-")
        assert by_cat["rightsizing"] == {"idle"}
        assert by_cat["waste"] == {"stopped"}
        assert by_cat["pattern"] == {"flaky"}
        assert by_cat["capacity"] == {"disk"}
        assert "-" in by_cat["reliability"]  # no alert rules defined
        assert all(r.evidence and r.source == "rule" and r.status == "new" for r in recs)
        right = next(r for r in recs if r.category == "rightsizing")
        assert right.evidence["p95_cpu"] < 20 and right.evidence["cpu_threshold"] == 20
    n = count(db, Recommendation)
    run_cycle(db, make_settings(), adapter_factory, now=NOW + timedelta(minutes=5))
    assert count(db, Recommendation) == n  # deduped


def test_dismissed_recommendation_not_reraised_within_cooldown(db, adapter_factory):
    owner = uuid.uuid4()
    add_account(db, owner, "acc-m", scenario="medium")
    run_cycle(db, make_settings(), adapter_factory, now=NOW, backfill_hours=24 * 7)
    with db() as s:
        rec = s.scalars(select(Recommendation).where(Recommendation.category == "waste")).one()
        rec.status = "dismissed"
        s.commit()
    run_cycle(db, make_settings(), adapter_factory, now=NOW + timedelta(minutes=5))
    with db() as s:
        waste = s.scalars(select(Recommendation).where(Recommendation.category == "waste")).all()
        assert [w.status for w in waste] == ["dismissed"]


def test_vanished_resource_becomes_tombstone(db):
    from app.repositories.resources import sync_inventory

    owner = uuid.uuid4()
    acc_id = add_account(db, owner, "acc-a")
    def dto(n):
        return ResourceDTO(external_id=n, name=n, power_state="running")

    with db() as s:
        sync_inventory(s, acc_id, 4, [dto("a"), dto("b")], NOW)
        s.commit()
        before = {r.external_id: r.version for r in s.scalars(select(Resource))}
        sync_inventory(s, acc_id, 4, [dto("a")], NOW + timedelta(minutes=5))
        s.commit()
        rows = {r.external_id: r for r in s.scalars(select(Resource))}
        assert rows["b"].deleted_at is not None and rows["b"].version > before["b"]
        assert rows["a"].deleted_at is None and rows["a"].version == before["a"]  # no churn
        sync_inventory(s, acc_id, 4, [dto("a"), dto("b")], NOW + timedelta(minutes=10))
        s.commit()
        s.expire_all()
        b = s.scalars(select(Resource).where(Resource.external_id == "b")).one()
        assert b.deleted_at is None


def test_retention_purges_old_samples(db, adapter_factory):
    add_account(db, uuid.uuid4(), "acc-a")
    run_cycle(db, make_settings(), adapter_factory, now=NOW, backfill_hours=24)
    assert count(db, MetricSample) > 0
    run_cycle(db, make_settings(raw_retention_days=0), adapter_factory,
              now=NOW + timedelta(days=30))
    with db() as s:
        newest = s.scalar(select(func.max(MetricSample.ts)))
    assert newest is None or newest >= NOW + timedelta(days=30) - timedelta(minutes=30)
    assert count(db, UptimeRollup) > 0  # rollups outlive raw samples


def test_credentials_roundtrip_and_not_plaintext():
    token = encrypt_credentials(FERNET_KEY, {"client_secret": "s3cret"})
    assert b"s3cret" not in token
    assert decrypt_credentials(FERNET_KEY, token) == {"client_secret": "s3cret"}
    assert decrypt_credentials(FERNET_KEY, None) == {}


def test_unimplemented_adapters_fail_clearly():
    with pytest.raises(NotImplementedError, match="AWS"):
        AwsAdapter().list_resources(None)
