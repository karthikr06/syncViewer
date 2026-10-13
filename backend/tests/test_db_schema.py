import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.models import (
    Alert,
    AlertRule,
    AuditLog,
    CloudAccount,
    MetricSample,
    Recommendation,
    Resource,
    Role,
    UptimeRollup,
    User,
    Workspace,
)
from tests.conftest import alembic_cfg

T0 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


def make_user(s, email="a@x.com", role_id=2):
    ws = Workspace(name="ws")
    s.add(ws)
    s.flush()
    u = User(id=uuid.uuid4(), email=email, role_id=role_id, workspace_id=ws.id)
    s.add(u)
    s.flush()
    return u


def make_account(s, owner, ref="acc1"):
    a = CloudAccount(workspace_id=owner.workspace_id, provider_id=4, name="acc", external_ref=ref)
    s.add(a)
    s.flush()
    return a


def make_resource(s, account, ext="vm1"):
    r = Resource(account_id=account.id, type_id=4, external_id=ext, name=ext)
    s.add(r)
    s.flush()
    return r


def test_seed_and_table_count(session):
    assert {r.name for r in session.scalars(select(Role))} == {"admin", "developer", "viewer"}
    tables = set(inspect(session.connection()).get_table_names()) - {"alembic_version"}
    assert len(tables) == 20


def test_user_defaults_to_developer_role(session):
    u = make_user(session)
    session.refresh(u)
    assert u.role_id == 2 and u.is_active is True


def test_unique_and_check_constraints(session):
    u = make_user(session)
    a = make_account(session, u)
    r = make_resource(session, a)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(Resource(account_id=a.id, type_id=4, external_id="vm1", name="dup"))
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        r.power_state = "exploding"
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(CloudAccount(workspace_id=u.workspace_id,
                                 provider_id=4, name="x", external_ref="r",
                                 status="bogus"))
        session.flush()


def test_alert_rule_single_scope(session):
    u = make_user(session)
    a = make_account(session, u)
    r = make_resource(session, a)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(AlertRule(workspace_id=u.workspace_id,
                              name="n", account_id=a.id, resource_id=r.id,
                             metric_id=2, operator=">", threshold=90))
        session.flush()


def test_one_open_alert_per_rule_resource(session):
    u = make_user(session)
    a = make_account(session, u)
    r = make_resource(session, a)
    rule = AlertRule(workspace_id=u.workspace_id,
                     name="n", resource_id=r.id, metric_id=2, operator=">",
                     threshold=90)
    session.add(rule)
    session.flush()
    session.add(Alert(rule_id=rule.id, resource_id=r.id))
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(Alert(rule_id=rule.id, resource_id=r.id))
        session.flush()


def test_recommendation_dedupe_only_while_new(session):
    u = make_user(session)

    def rec(status="new"):
        return Recommendation(workspace_id=u.workspace_id,
                              category="waste", title="t", dedupe_key="k",
                              status=status)

    first = rec()
    session.add(first)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(rec())
        session.flush()
    first.status = "dismissed"
    session.flush()
    session.add(rec())
    session.flush()


def test_version_bumps_on_insert_and_update(session):
    u = make_user(session)
    a = make_account(session, u)
    session.refresh(a)
    v1 = a.version
    assert v1 > 0
    a.name = "renamed"
    session.flush()
    session.refresh(a)
    assert a.version > v1


def test_versions_are_global_and_monotonic(session):
    u = make_user(session)
    a = make_account(session, u)
    r = make_resource(session, a)
    session.refresh(a)
    session.refresh(r)
    assert r.version > a.version


def test_soft_delete_propagates_as_tombstone(session):
    u = make_user(session)
    a = make_account(session, u)
    r = make_resource(session, a)
    session.refresh(r)
    cursor = r.version
    r.deleted_at = func.now()
    session.flush()
    changed = session.scalars(select(Resource).where(Resource.version > cursor)).all()
    assert [c.id for c in changed] == [r.id] and changed[0].deleted_at is not None


def test_audit_trigger_records_without_credentials(session):
    u = make_user(session)
    a = make_account(session, u)
    a.credentials_encrypted = b"secret"
    a.name = "changed"
    session.flush()
    rows = session.scalars(
        select(AuditLog).where(AuditLog.entity == "cloud_accounts", AuditLog.entity_id == str(a.id))
    ).all()
    assert [r.action for r in rows] == ["INSERT", "UPDATE"]
    assert all("credentials_encrypted" not in (r.after or {}) for r in rows)
    assert rows[1].before["name"] == "acc" and rows[1].after["name"] == "changed"


def _add_samples(session, r, hour_start, availability, cpus):
    for i, (av, cpu) in enumerate(zip(availability, cpus, strict=True)):
        ts = hour_start + timedelta(minutes=5 * i)
        session.add(MetricSample(resource_id=r.id, metric_id=1, ts=ts, value=av))
        session.add(MetricSample(resource_id=r.id, metric_id=2, ts=ts, value=cpu))
    session.flush()


def test_compute_uptime_rollup_math(session):
    u = make_user(session)
    r = make_resource(session, make_account(session, u))
    _add_samples(session, r, T0, [1, 1, 1, 0], [10, 20, 30, 40])
    n = session.execute(
        text("SELECT compute_uptime_rollup(:a, :b)"), {"a": T0, "b": T0 + timedelta(minutes=15)}
    ).scalar_one()
    assert n == 1
    roll = session.get(UptimeRollup, (r.id, T0))
    assert (roll.up_samples, roll.total_samples) == (3, 4)
    assert roll.avg_cpu == pytest.approx(25.0) and roll.max_cpu == 40
    assert roll.p95_cpu == pytest.approx(38.5)


def test_rollup_is_idempotent_and_updates(session):
    u = make_user(session)
    r = make_resource(session, make_account(session, u))
    _add_samples(session, r, T0, [1, 1], [10, 10])
    call = text("SELECT compute_uptime_rollup(:a, :b)")
    args = {"a": T0, "b": T0 + timedelta(hours=1)}
    session.execute(call, args)
    session.execute(call, args)
    assert session.scalar(select(func.count()).select_from(UptimeRollup)) == 1
    session.add(MetricSample(resource_id=r.id, metric_id=1, ts=T0 + timedelta(minutes=30), value=0))
    session.flush()
    session.execute(call, args)
    roll = session.get(UptimeRollup, (r.id, T0))
    session.refresh(roll)
    assert (roll.up_samples, roll.total_samples) == (2, 3)


def test_views_exist_and_work(session):
    u = make_user(session)
    a = make_account(session, u)
    r = make_resource(session, a)
    _add_samples(session, r, T0, [1, 0], [50, 60])
    latest = session.execute(
        text("SELECT availability, cpu_percent FROM v_resource_latest WHERE resource_id = :r"),
        {"r": r.id},
    ).one()
    assert (latest.availability, latest.cpu_percent) == (0, 60)
    assert session.execute(text("SELECT count(*) FROM v_open_alerts")).scalar_one() == 0
    assert session.execute(
        text("SELECT total_samples FROM v_account_uptime_7d WHERE account_id = :a"), {"a": a.id}
    ).scalar_one() == 0


def test_rls_enabled_on_all_tables(session):
    off = session.execute(
        text("SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace "
             "AND relkind = 'r' AND NOT relrowsecurity")
    ).scalars().all()
    assert off == []


def test_out_of_order_commit_needs_overlap(migrated_url):
    """Two transactions take versions v1<v2; the later one commits first. A strict
    `version > cursor` read taken between the commits permanently skips v1, an overlapped
    read (cursor - overlap) recovers it."""
    eng = create_engine(migrated_url, connect_args={"prepare_threshold": None})
    owner_id = uuid.uuid4()
    with eng.begin() as c:
        c.execute(text("INSERT INTO workspaces(id,name) VALUES (:i,'w')"), {"i": owner_id})
        c.execute(text("INSERT INTO users(id,email,workspace_id) VALUES (:i,'ooo@x.com',:i)"),
                  {"i": owner_id})
    ins = text("INSERT INTO cloud_accounts(workspace_id,provider_id,name,external_ref) "
               "VALUES (:o,4,'n',:r)")
    c1, c2 = eng.connect(), eng.connect()
    t1, t2 = c1.begin(), c2.begin()
    c1.execute(ins, {"o": owner_id, "r": "first"})   # gets the lower version
    c2.execute(ins, {"o": owner_id, "r": "second"})  # higher version
    t2.commit()                                      # higher commits first
    with eng.connect() as reader:
        seen = reader.execute(
            text("SELECT external_ref, version FROM cloud_accounts WHERE workspace_id=:o"),
            {"o": owner_id}).all()
        cursor = max(v for _, v in seen)
        assert [r for r, _ in seen] == ["second"]
    t1.commit()
    c1.close(), c2.close()
    with eng.connect() as reader:
        strict = reader.execute(
            text("SELECT external_ref FROM cloud_accounts "
                 "WHERE workspace_id=:o AND version > :c"),
            {"o": owner_id, "c": cursor}).scalars().all()
        overlap = reader.execute(
            text("SELECT external_ref FROM cloud_accounts "
                 "WHERE workspace_id=:o AND version > :c"),
            {"o": owner_id, "c": cursor - 500}).scalars().all()
    assert strict == []                       # the row was skipped
    assert set(overlap) == {"first", "second"}  # overlap + idempotent upsert recovers it
    eng.dispose()


def test_migrate_down_and_up(make_database):
    url = make_database()
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    eng = create_engine(url)
    with eng.connect() as c:
        left = c.execute(text(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
            "AND tablename <> 'alembic_version'")).scalar_one()
    eng.dispose()
    assert left == 0
    command.upgrade(cfg, "head")


def test_workspace_migration_keeps_existing_data(make_database):
    """Upgrading a populated 0004 database: each user becomes the admin of a workspace with the
    same id, and their accounts and advice belong to it."""
    url = make_database()
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "0004")
    eng = create_engine(url, connect_args={"prepare_threshold": None})
    uid, vid = uuid.uuid4(), uuid.uuid4()
    with eng.begin() as c:
        c.execute(text("INSERT INTO users(id,email,role_id) VALUES (:u,'own@x.com',2),"
                       "(:v,'view@x.com',3)"), {"u": uid, "v": vid})
        c.execute(text("INSERT INTO cloud_accounts(owner_id,provider_id,name,external_ref) "
                       "VALUES (:u,4,'demo','ref')"), {"u": uid})
        c.execute(text("INSERT INTO recommendations(owner_id,category,title,dedupe_key) "
                       "VALUES (:u,'waste','t','k')"), {"u": uid})
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT u.email, r.name, u.workspace_id = u.id, w.name FROM users u "
            "JOIN roles r ON r.id = u.role_id JOIN workspaces w ON w.id = u.workspace_id "
            "ORDER BY u.email")).all()
        assert rows == [("own@x.com", "admin", True, "own's workspace"),
                        ("view@x.com", "viewer", True, "view's workspace")]
        assert c.execute(text("SELECT workspace_id FROM cloud_accounts")).scalar() == uid
        assert c.execute(text("SELECT workspace_id FROM recommendations")).scalar() == uid
        assert c.execute(text("SELECT count(*) FROM v_account_uptime_7d "
                              "WHERE workspace_id = :u"), {"u": uid}).scalar() == 1
    eng.dispose()


def test_one_pending_invite_per_email(session):
    from app.models import WorkspaceInvite

    u = make_user(session)
    session.add(WorkspaceInvite(workspace_id=u.workspace_id, email="new@x.com", role_id=3))
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(WorkspaceInvite(workspace_id=u.workspace_id, email="new@x.com", role_id=2))
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():  # admin is not invitable
        session.add(WorkspaceInvite(workspace_id=u.workspace_id, email="b@x.com", role_id=1))
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():  # stored lower-case
        session.add(WorkspaceInvite(workspace_id=u.workspace_id, email="C@x.com", role_id=3))
        session.flush()
