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


def test_me_provisions_user_and_role_comes_from_db(env):
    c = env.client
    me = c.get("/api/v1/me", headers=auth(email="a@x.com", role="admin")).json()
    assert me["role"] == "user"  # a role claim in the token is ignored
    assert c.get("/api/v1/me", headers=auth(email=ADMIN_EMAIL)).json()["role"] == "admin"


def test_viewer_cannot_write(env):
    uid, h = env.user("v@x.com")
    env.set_role(uid, 3)
    r = env.client.post("/api/v1/cloud-accounts", headers=h, json={
        "name": "x", "provider": "mock", "external_ref": "x"})
    assert r.status_code == 403
    assert env.client.get("/api/v1/cloud-accounts", headers=h).status_code == 200


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


def test_admin_routes_and_role_management(env):
    uid, user_h = env.user("u@x.com")
    _, admin_h = env.user(ADMIN_EMAIL)
    c = env.client
    assert c.get("/api/v1/admin/users", headers=user_h).status_code == 403
    assert c.get("/api/v1/admin/collector-runs", headers=user_h).status_code == 403
    users = c.get("/api/v1/admin/users?q=u@", headers=admin_h).json()
    assert users["total"] == 1 and users["items"][0]["email"] == "u@x.com"
    r = c.patch(f"/api/v1/admin/users/{uid}", headers=admin_h, json={"role": "viewer"})
    assert r.json()["role"] == "viewer"
    assert c.post("/api/v1/cloud-accounts", headers=user_h, json={
        "name": "x", "provider": "mock", "external_ref": "x"}).status_code == 403
    c.patch(f"/api/v1/admin/users/{uid}", headers=admin_h, json={"is_active": False})
    assert c.get("/api/v1/me", headers=user_h).status_code == 403
    admin_id = next(u["id"] for u in c.get("/api/v1/admin/users", headers=admin_h).json()["items"]
                    if u["email"] == ADMIN_EMAIL)
    assert c.patch(f"/api/v1/admin/users/{admin_id}", headers=admin_h,
                   json={"role": "user"}).status_code == 400
    assert c.get("/api/v1/admin/collector-runs", headers=admin_h).status_code == 200


def test_admin_cannot_see_other_users_data(env):
    _, a = env.user("a@x.com")
    _, admin = env.user(ADMIN_EMAIL)
    new_account(env, a)
    assert env.client.get("/api/v1/resources", headers=admin).json()["total"] == 0


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
