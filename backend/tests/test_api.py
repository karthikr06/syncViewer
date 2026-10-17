import time
import uuid
from dataclasses import replace

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.collector.adapters import MockAdapter, get_adapter
from app.main import create_app
from app.models import CloudAccount, User
from tests.conftest import alembic_cfg
from tests.test_collector import make_settings

SECRET = "test-secret-test-secret-test-secret-123"
ADMIN_EMAIL = "boss@x.com"


def token(user_id=None, email="user@x.com", exp_in=3600, **extra) -> str:
    claims = {"sub": str(user_id or uuid.uuid4()), "email": email, "aud": "authenticated",
              "exp": int(time.time()) + exp_in, **extra}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def auth(user_id=None, email="user@x.com", **kw) -> dict:
    return {"Authorization": f"Bearer {token(user_id, email, **kw)}"}


class Env:
    def __init__(self, client, factory):
        self.client, self.factory = client, factory

    def user(self, email):
        uid = uuid.uuid4()
        headers = auth(uid, email)
        assert self.client.get("/api/v1/me", headers=headers).status_code == 200
        return uid, headers

    def member(self, admin_headers, email, role="viewer"):
        """Invite `email` into the admin's workspace, then sign them in (accepts the invite)."""
        r = self.client.post("/api/v1/workspace/invites", headers=admin_headers,
                             json={"email": email, "role": role})
        assert r.status_code == 201, r.text
        return self.user(email)

    def set_role(self, uid, role_id):
        with self.factory() as s:
            s.get(User, uid).role_id = role_id
            s.commit()


@pytest.fixture
def env(make_database):
    from syncgen.main import app as gen_app

    url = make_database()
    command.upgrade(alembic_cfg(url), "head")
    engine = create_engine(url, connect_args={"prepare_threshold": None})
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = replace(make_settings(), supabase_jwt_secret=SECRET, admin_emails=[ADMIN_EMAIL],
                       database_url=url)
    mock = MockAdapter("http://testserver", client=TestClient(gen_app))
    app = create_app(settings, factory,
                     lambda code: mock if code == "mock" else get_adapter(code, settings))
    yield Env(TestClient(app, raise_server_exceptions=False), factory)
    engine.dispose()


def new_account(env, headers, ref="acc-1", scenario="small"):
    r = env.client.post("/api/v1/cloud-accounts", headers=headers, json={
        "name": ref, "provider": "mock", "external_ref": ref, "config": {"scenario": scenario}})
    assert r.status_code == 201, r.text
    return r.json()


def test_requires_valid_token(env):
    c = env.client
    assert c.get("/health").json() == {"status": "ok"}
    assert c.get("/api/v1/me").status_code == 401
    assert c.get("/api/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert c.get("/api/v1/me", headers=auth(exp_in=-100)).status_code == 401
    forged = jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated",
                         "exp": int(time.time()) + 99}, "wrong-secret-wrong-secret-wrong-12",
                        algorithm="HS256")
    assert c.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_first_sign_in_creates_a_workspace_and_role_comes_from_db(env):
    c = env.client
    uid = uuid.uuid4()
    me = c.get("/api/v1/me", headers=auth(uid, email="a@x.com", role="viewer")).json()
    # a role claim in the token is ignored: a new sign-up is the admin of a new workspace
    assert me["role"] == "admin" and me["workspace"]["name"] == "a's workspace"
    assert me["is_operator"] is False
    env.set_role(uid, 3)
    assert c.get("/api/v1/me", headers=auth(uid, email="a@x.com")).json()["role"] == "viewer"
    assert c.get("/api/v1/me", headers=auth(email=ADMIN_EMAIL)).json()["is_operator"] is True


def test_viewer_reads_the_workspace_but_cannot_write(env):
    _, admin = env.user("boss@team.com")
    new_account(env, admin)
    _, v = env.member(admin, "v@x.com", "viewer")
    c = env.client
    assert c.get("/api/v1/me", headers=v).json()["role"] == "viewer"
    assert c.get("/api/v1/cloud-accounts", headers=v).json()["total"] == 1  # shared data
    assert c.get("/api/v1/resources", headers=v).json()["total"] == 5
    r = c.post("/api/v1/cloud-accounts", headers=v, json={
        "name": "x", "provider": "mock", "external_ref": "x"})
    assert r.status_code == 403
    rid = c.get("/api/v1/resources", headers=v).json()["items"][0]["id"]
    assert c.post(f"/api/v1/resources/{rid}/actions", headers=v,
                  json={"action": "stop"}).status_code == 403
    assert c.post("/api/v1/workspace/invites", headers=v,
                  json={"email": "z@x.com"}).status_code == 403


def test_tenant_isolation_returns_404(env):
    _, a = env.user("a@x.com")
    _, b = env.user("b@x.com")
    acc = new_account(env, a)
    res = env.client.get("/api/v1/resources", headers=a).json()["items"]
    assert len(res) == 5
    rid = res[0]["id"]
    for method, path in (("get", f"/api/v1/cloud-accounts/{acc['id']}"),
                         ("get", f"/api/v1/resources/{rid}"),
                         ("get", f"/api/v1/resources/{rid}/metrics"),
                         ("patch", f"/api/v1/cloud-accounts/{acc['id']}"),
                         ("delete", f"/api/v1/cloud-accounts/{acc['id']}"),
                         ("post", f"/api/v1/cloud-accounts/{acc['id']}/collect-now")):
        r = getattr(env.client, method)(path, headers=b, **({"json": {}} if method == "patch"
                                                           else {}))
        assert r.status_code == 404, (method, path, r.status_code)
    assert env.client.get("/api/v1/resources", headers=b).json()["total"] == 0
    assert env.client.get("/api/v1/cloud-accounts", headers=b).json()["total"] == 0
    # another user's account/resource cannot be used as an alert scope either
    bad = env.client.post("/api/v1/alert-rules", headers=b, json={
        "name": "r", "metric": "cpu_percent", "operator": ">", "threshold": 90,
        "resource_id": rid})
    assert bad.status_code == 404


def test_account_credentials_never_returned_and_stored_encrypted(env):
    _, h = env.user("a@x.com")
    r = env.client.post("/api/v1/cloud-accounts", headers=h, json={
        "name": "n", "provider": "mock", "external_ref": "c1",
        "credentials": {"client_secret": "s3cret"}})
    assert r.status_code == 201 and "s3cret" not in r.text and "credentials" not in r.text
    with env.factory() as s:
        raw = s.scalars(select(CloudAccount)).one().credentials_encrypted
    assert raw is not None and b"s3cret" not in bytes(raw)


def test_duplicate_account_conflict_and_unavailable_provider(env):
    _, h = env.user("a@x.com")
    new_account(env, h, "dup")
    again = env.client.post("/api/v1/cloud-accounts", headers=h, json={
        "name": "n", "provider": "mock", "external_ref": "dup"})
    assert again.status_code == 409
    azure = env.client.post("/api/v1/cloud-accounts", headers=h, json={
        "name": "n", "provider": "azure", "external_ref": "sub"})
    assert azure.status_code == 400
    assert env.client.get("/api/v1/cloud-accounts", headers=h).json()["total"] == 1


def test_workspace_members_and_invites(env):
    c = env.client
    admin_id, admin = env.user("boss@team.com")
    acc = new_account(env, admin)
    # invite a developer and a viewer; only admins manage members
    inv = c.post("/api/v1/workspace/invites", headers=admin,
                 json={"email": "Dev@Team.com", "role": "developer"})
    assert inv.status_code == 201 and inv.json()["email"] == "dev@team.com"
    assert c.post("/api/v1/workspace/invites", headers=admin,
                  json={"email": "not-an-email", "role": "viewer"}).status_code == 422
    assert c.post("/api/v1/workspace/invites", headers=admin,
                  json={"email": "x@team.com", "role": "admin"}).status_code == 422
    listing = c.get("/api/v1/workspace/members", headers=admin).json()
    assert [i["email"] for i in listing["invites"]] == ["dev@team.com"]
    # the invited person signs up and lands in the same workspace with the invited role
    dev_id, dev = env.user("dev@team.com")
    me = c.get("/api/v1/me", headers=dev).json()
    assert me["role"] == "developer" and me["workspace"]["name"] == "boss's workspace"
    assert c.get(f"/api/v1/cloud-accounts/{acc['id']}", headers=dev).status_code == 200
    assert c.get("/api/v1/workspace/members", headers=admin).json()["invites"] == []
    members = c.get("/api/v1/workspace/members", headers=dev).json()
    assert {m["email"] for m in members["members"]} == {"boss@team.com", "dev@team.com"}
    assert members["invites"] == []  # only admins see pending invites
    assert c.post("/api/v1/workspace/invites", headers=dev,
                  json={"email": "q@x.com"}).status_code == 403
    # someone who already has an account cannot be invited; members change role instead
    env.user("solo@else.com")
    for email in ("solo@else.com", "dev@team.com"):
        assert c.post("/api/v1/workspace/invites", headers=admin,
                      json={"email": email}).status_code == 409
    # role changes and removal
    r = c.patch(f"/api/v1/workspace/members/{dev_id}", headers=admin, json={"role": "viewer"})
    assert r.json()["role"] == "viewer"
    assert c.post("/api/v1/cloud-accounts", headers=dev, json={
        "name": "x", "provider": "mock", "external_ref": "x"}).status_code == 403
    assert c.patch(f"/api/v1/workspace/members/{admin_id}", headers=admin,
                   json={"role": "viewer"}).status_code == 400
    assert c.patch(f"/api/v1/workspace/members/{admin_id}", headers=dev,
                   json={"is_active": False}).status_code == 403
    c.patch(f"/api/v1/workspace/members/{dev_id}", headers=admin, json={"is_active": False})
    assert c.get("/api/v1/me", headers=dev).status_code == 403
    # revoke a pending invite; rename the workspace
    inv2 = c.post("/api/v1/workspace/invites", headers=admin, json={"email": "late@x.com"})
    assert c.delete(f"/api/v1/workspace/invites/{inv2.json()['id']}",
                    headers=admin).status_code == 204
    assert c.patch("/api/v1/workspace", headers=admin,
                   json={"name": "Ops team"}).json()["name"] == "Ops team"
    # collector health is for platform operators only
    assert c.get("/api/v1/admin/collector-runs", headers=admin).status_code == 403
    _, op = env.user(ADMIN_EMAIL)
    assert c.get("/api/v1/admin/collector-runs", headers=op).status_code == 200


def test_other_workspaces_stay_isolated(env):
    _, a = env.user("a@x.com")
    _, op = env.user(ADMIN_EMAIL)  # even a platform operator sees only their own workspace
    new_account(env, a)
    assert env.client.get("/api/v1/resources", headers=op).json()["total"] == 0
    members = env.client.get("/api/v1/workspace/members", headers=op).json()["members"]
    assert [m["email"] for m in members] == [ADMIN_EMAIL]


def test_vm_actions_and_one_click_fix(env):
    c = env.client
    _, admin = env.user("boss@team.com")
    _, dev = env.member(admin, "dev@team.com", "developer")
    _, outsider = env.user("o@else.com")
    acc = new_account(env, admin, scenario="medium")
    c.post(f"/api/v1/cloud-accounts/{acc['id']}/collect-now", headers=admin)
    vms = c.get("/api/v1/resources?page_size=100", headers=dev).json()["items"]
    stopped = next(v for v in vms if v["power_state"] == "stopped")
    running = next(v for v in vms if v["power_state"] == "running")
    recs = c.get("/api/v1/recommendations?category=waste", headers=dev).json()["items"]
    waste = next(r for r in recs if r["resource_id"] == stopped["id"])
    # invalid transitions and other workspaces are refused
    assert c.post(f"/api/v1/resources/{stopped['id']}/actions", headers=dev,
                  json={"action": "stop"}).status_code == 409
    assert c.post(f"/api/v1/resources/{stopped['id']}/actions", headers=outsider,
                  json={"action": "deallocate"}).status_code == 404
    # the developer fixes the "stopped but not deallocated" warning in one click
    r = c.post(f"/api/v1/resources/{stopped['id']}/actions", headers=dev,
               json={"action": "deallocate", "recommendation_id": waste["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded" and r.json()["to_state"] == "deallocated"
    vm = c.get(f"/api/v1/resources/{stopped['id']}", headers=dev).json()
    assert vm["power_state"] == "deallocated"
    done = c.get("/api/v1/recommendations?status=done", headers=dev).json()["items"]
    assert [d["id"] for d in done] == [waste["id"]]
    # stop a running VM; history records who did what
    stop = c.post(f"/api/v1/resources/{running['id']}/actions", headers=admin,
                  json={"action": "stop"})
    assert stop.json()["to_state"] == "stopped"
    history = c.get(f"/api/v1/resources/{stopped['id']}/actions", headers=dev).json()
    assert history[0]["action"] == "deallocate" and history[0]["requested_by"] == "dev@team.com"
    # the next collection confirms the provider state: only the newly stopped VM is now waste
    c.post(f"/api/v1/cloud-accounts/{acc['id']}/collect-now", headers=admin)
    open_waste = c.get("/api/v1/recommendations?category=waste&status=new",
                       headers=dev).json()["items"]
    assert {w["resource_id"] for w in open_waste} == {running["id"]}


def test_500_is_generic_and_docs_hidden_in_production(env, make_database):
    app = env.client.app

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail: SELECT * FROM users")

    r = env.client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert set(body) == {"detail", "request_id"} and "SELECT" not in r.text
    assert r.headers["X-Request-ID"] == body["request_id"]
    assert env.client.get("/docs").status_code == 200

    prod = create_app(replace(make_settings(), supabase_jwt_secret=SECRET, app_env="production"),
                      env.factory, None)
    pc = TestClient(prod)
    assert pc.get("/docs").status_code == 404 and pc.get("/openapi.json").status_code == 404


def test_collect_now_fills_data_and_is_rate_limited(env):
    _, h = env.user("a@x.com")
    acc = new_account(env, h, scenario="medium")
    r = env.client.post(f"/api/v1/cloud-accounts/{acc['id']}/collect-now", headers=h)
    assert r.status_code == 200 and r.json()["samples_inserted"] > 0
    res = env.client.get("/api/v1/resources?page_size=100", headers=h).json()
    assert res["total"] == 25
    rid = res["items"][0]["id"]
    detail = env.client.get(f"/api/v1/resources/{rid}", headers=h).json()
    assert "cpu_percent" in detail["latest"] or detail["power_state"] == "stopped"
    m = env.client.get(f"/api/v1/resources/{rid}/metrics?metric=cpu_percent&step=900", headers=h)
    assert m.status_code == 200
    statuses = [env.client.post(f"/api/v1/cloud-accounts/{acc['id']}/collect-now",
                                headers=h).status_code for _ in range(7)]
    assert 429 in statuses


def test_list_filters_pagination_and_sort(env):
    _, h = env.user("a@x.com")
    new_account(env, h, scenario="medium")
    c = env.client
    page = c.get("/api/v1/resources?page=2&page_size=10&sort=-name", headers=h).json()
    assert page["total"] == 25 and len(page["items"]) == 10 and page["page"] == 2
    assert c.get("/api/v1/resources?power_state=stopped", headers=h).json()["total"] >= 1
    assert c.get("/api/v1/resources?q=%25", headers=h).json()["total"] == 0  # % is literal
    assert c.get("/api/v1/resources?page_size=1000", headers=h).status_code == 422


def test_alert_rule_crud_and_validation(env):
    _, h = env.user("a@x.com")
    c = env.client
    acc = new_account(env, h)
    body = {"name": "hot cpu", "metric": "cpu_percent", "operator": ">", "threshold": 90,
            "duration_minutes": 10, "severity": "critical", "account_id": acc["id"]}
    rule = c.post("/api/v1/alert-rules", headers=h, json=body)
    assert rule.status_code == 201 and rule.json()["metric"] == "cpu_percent"
    rid = rule.json()["id"]
    assert c.patch(f"/api/v1/alert-rules/{rid}", headers=h,
                   json={"threshold": 95}).json()["threshold"] == 95
    assert c.post("/api/v1/alert-rules", headers=h,
                  json={**body, "metric": "bogus"}).status_code == 422
    assert c.delete(f"/api/v1/alert-rules/{rid}", headers=h).status_code == 204
    assert c.get("/api/v1/alert-rules", headers=h).json()["total"] == 0


def test_recommendations_status_update_and_isolation(env):
    _, a = env.user("a@x.com")
    _, b = env.user("b@x.com")
    acc = new_account(env, a, scenario="medium")
    env.client.post(f"/api/v1/cloud-accounts/{acc['id']}/collect-now", headers=a)
    recs = env.client.get("/api/v1/recommendations?status=new", headers=a).json()
    assert recs["total"] > 0
    rid = recs["items"][0]["id"]
    assert env.client.patch(f"/api/v1/recommendations/{rid}", headers=b,
                            json={"status": "dismissed"}).status_code == 404
    ok = env.client.patch(f"/api/v1/recommendations/{rid}", headers=a, json={"status": "done"})
    assert ok.json()["status"] == "done"
    assert env.client.get("/api/v1/recommendations", headers=b).json()["total"] == 0


def test_delta_sync_insert_update_delete(env):
    _, h = env.user("a@x.com")
    _, other = env.user("b@x.com")
    c = env.client

    def changes(entity, since, headers=h):
        return c.get(f"/api/v1/sync/changes?entity={entity}&since={since}", headers=headers).json()

    acc = new_account(env, h)
    first = changes("cloud_accounts", 0)
    assert [r["id"] for r in first["rows"]] == [acc["id"]]
    cursor = first["next_since"]
    assert changes("cloud_accounts", cursor)["rows"] == []  # nothing new

    c.patch(f"/api/v1/cloud-accounts/{acc['id']}", headers=h, json={"name": "renamed"})
    upd = changes("cloud_accounts", cursor)
    assert upd["rows"][0]["name"] == "renamed" and upd["next_since"] > cursor
    assert changes("cloud_accounts", 0, other)["rows"] == []  # other tenants see nothing

    res0 = changes("resources", 0)
    assert len(res0["rows"]) == 5 and all(r["deleted_at"] is None for r in res0["rows"])
    c.delete(f"/api/v1/cloud-accounts/{acc['id']}", headers=h)
    tomb = changes("cloud_accounts", upd["next_since"])
    assert tomb["rows"][0]["deleted_at"] is not None  # tombstone
    res1 = changes("resources", res0["next_since"])
    assert len(res1["rows"]) == 5 and all(r["deleted_at"] for r in res1["rows"])
    assert c.get("/api/v1/resources", headers=h).json()["total"] == 0
    # overlap re-read returns the same rows again; clients upsert idempotently
    again = changes("resources", res0["next_since"] - 3)
    assert {r["id"] for r in again["rows"]} >= {r["id"] for r in res1["rows"]}
    assert c.get("/api/v1/sync/changes?entity=nope", headers=h).status_code == 422


def test_sync_bootstrap_metrics_and_paging(env):
    _, h = env.user("a@x.com")
    c = env.client
    acc = new_account(env, h, scenario="medium")
    c.post(f"/api/v1/cloud-accounts/{acc['id']}/collect-now", headers=h)
    boot = c.get("/api/v1/sync/bootstrap?limit=10", headers=h).json()
    assert boot["me"]["email"] == "a@x.com"
    assert boot["entities"]["resources"]["has_more"] is True
    assert len(boot["entities"]["resources"]["rows"]) == 10
    nxt = c.get(f"/api/v1/sync/changes?entity=resources&limit=10&since="
                f"{boot['entities']['resources']['next_since']}", headers=h).json()
    assert nxt["rows"] and nxt["rows"][0]["id"] not in {
        r["id"] for r in boot["entities"]["resources"]["rows"]}
    assert boot["entities"]["uptime_rollups"]["rows"]
    m = c.get("/api/v1/sync/metrics?window=24&step=900", headers=h).json()
    assert m["rows"] and {r["metric"] for r in m["rows"]} <= {
        "availability", "cpu_percent", "memory_percent", "disk_used_percent"}
    later = c.get(f"/api/v1/sync/metrics?since={m['next_since']}", headers=h).json()
    assert later["rows"]  # `since` is inclusive: re-reads the newest timestamp


def test_digest_generation_and_chat_without_key(env):
    _, h = env.user("a@x.com")
    acc = new_account(env, h, scenario="medium")
    env.client.post(f"/api/v1/cloud-accounts/{acc['id']}/collect-now", headers=h)
    d = env.client.post("/api/v1/insights/digests/generate?days=1", headers=h)
    assert d.status_code == 201 and "Fleet uptime" in d.json()["summary_md"]
    assert env.client.get("/api/v1/insights/digests", headers=h).json()["total"] == 1
    chat = env.client.post("/api/v1/agent/chat", headers=h, json={"message": "hi"}).json()
    assert chat["configured"] is False and "not configured" in chat["reply"]



def test_writes_commit_before_the_response_is_sent(env):
    """FastAPI runs a yield dependency's exit code after the response is sent unless its scope
    is "function"; get_db commits there, so with the default scope a client could read stale
    data right after a write (seen against a remote database) or get 2xx for a failed commit."""
    from sqlalchemy.orm import Session

    events: list[str] = []

    class RecordingSession(Session):
        def commit(self):
            super().commit()
            events.append("commit")

    inner = env.client.app
    inner.state.session_factory.class_ = RecordingSession

    async def recording_app(scope, receive, send):
        async def tap(message):
            if message["type"] == "http.response.start":
                events.append("response")
            await send(message)
        await inner(scope, receive, tap)

    client = TestClient(recording_app)
    r = client.post("/api/v1/alert-rules", headers=auth(),
                    json={"name": "x", "metric": "cpu_percent", "operator": ">", "threshold": 1})
    assert r.status_code == 201
    assert "commit" in events and events.index("commit") < events.index("response")


def test_scheduled_collect_needs_the_token_and_runs_in_background(env):
    _, admin = env.user("boss@sched.com")
    account = new_account(env, admin)
    assert account["last_collected_at"] is None
    app, c = env.client.app, env.client
    assert c.post("/api/v1/internal/collect").status_code == 404  # no token configured
    app.state.settings = replace(app.state.settings, collector_token="tok-123")
    wrong = {"X-Collector-Token": "nope"}
    assert c.post("/api/v1/internal/collect", headers=wrong).status_code == 404
    r = c.post("/api/v1/internal/collect", headers={"X-Collector-Token": "tok-123"})
    assert r.status_code == 202 and r.json() == {"status": "started"}
    app.state.collector_thread.join(timeout=60)
    with env.factory() as s:
        assert s.get(CloudAccount, uuid.UUID(account["id"])).last_collected_at is not None
    assert c.post("/api/v1/internal/collect?token=tok-123").status_code == 202
    app.state.collector_thread.join(timeout=60)
