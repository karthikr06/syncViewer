"""Prometheus adapter: canned query API answers (no server), the URL guard and a full cycle."""
import socket
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.collector.adapters import get_adapter
from app.collector.adapters.prometheus import (
    PrometheusAdapter,
    PrometheusError,
    UnsafeUrl,
    check_url,
    power_state,
)
from app.collector.cycle import run_cycle
from app.collector.dto import AccountRef
from app.models import Incident, MetricSample, Resource
from tests.test_collector import NOW, add_account, db, make_settings  # noqa: F401 - fixture

URL = "https://prom.example.com"
UP_LABELS = {"job": "node", "region": "centralindia", "instance_type": "Standard_B2s",
             "cloud": "azure", "team": "web"}


def public(host, port, proto=0):  # noqa: ARG001 - getaddrinfo signature
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port))]


def resolver(ip):
    return lambda host, port, proto=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


class FakeProm:
    """Answers the adapter's queries for two VMs: `web-1` is up, `web-2` does not answer."""

    def __init__(self, targets=("web-1:9100", "web-2:9100"), down=("web-2:9100",)):
        self.targets, self.down = targets, set(down)
        self.requests: list[httpx.Request] = []

    def vector(self, query):
        if 'job="nope"' in query:
            return []
        if query.startswith("up{"):
            return [{"metric": {"__name__": "up", "instance": t, **UP_LABELS},
                     "value": [0, "0" if t in self.down else "1"]} for t in self.targets]
        if query.startswith("max by (instance) (up"):
            return [{"metric": {"instance": t}, "value": [0, "0" if t in self.down else "1"]}
                    for t in self.targets]
        if "node_uname_info" in query:
            return [{"metric": {"instance": t, "nodename": t.split(":")[0].upper()},
                     "value": [0, "1"]} for t in self.targets]
        raise AssertionError(f"unexpected query {query}")

    def matrix(self, query, start, end, step):
        times = list(range(int(start) - int(start) % step + step, int(end) + 1, step))
        out = []
        for t in self.targets:
            down = t in self.down
            if "up{" in query:
                value = "0" if down else "1"
            elif down:
                continue  # an unreachable VM has no node_exporter series
            elif "MemAvailable" in query:
                value = "NaN" if t == "web-1:9100" and "mem-nan" in self.targets else "42.5"
            else:
                value = "12.5"
            out.append({"metric": {"instance": t}, "values": [[ts, value] for ts in times]})
        return out

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        q = request.url.params["query"]
        if request.url.path == "/api/v1/query":
            return httpx.Response(200, json={"status": "success", "data": {
                "resultType": "vector", "result": self.vector(q)}})
        assert request.url.path == "/api/v1/query_range"
        p = request.url.params
        res = self.matrix(q, float(p["start"]), float(p["end"]), int(p["step"]))
        return httpx.Response(200, json={"status": "success", "data": {
            "resultType": "matrix", "result": res}})


def adapter(fake, allow_private=False):
    return PrometheusAdapter(allow_private, httpx.Client(transport=httpx.MockTransport(fake)),
                             resolve=public)


def ref(config=None, credentials=None, url=URL):
    return AccountRef("a", "prometheus", url, config or {}, credentials or {})


def test_list_resources_maps_labels_and_health():
    vms = {r.external_id: r for r in adapter(FakeProm()).list_resources(ref())}
    assert set(vms) == {"web-1:9100", "web-2:9100"}
    one, two = vms["web-1:9100"], vms["web-2:9100"]
    assert (one.name, one.region, one.size_sku) == ("WEB-1", "centralindia", "Standard_B2s")
    assert one.tags == {"cloud": "azure", "team": "web"}
    assert (one.power_state, one.health_state) == ("running", "healthy")
    # unreachable but still a target: running and unavailable, so incidents open for it
    assert (two.power_state, two.health_state) == ("running", "unavailable")


def test_empty_answer_is_an_error_not_a_mass_delete():
    with pytest.raises(PrometheusError, match="no VMs"):
        adapter(FakeProm(targets=())).list_resources(ref())


def test_fetch_metrics_all_six_and_down_vm_availability():
    fake = FakeProm()
    a = adapter(fake)
    vms = a.list_resources(ref())
    samples = a.fetch_metrics(ref(), vms, NOW - timedelta(hours=1), NOW)
    by = {(s.external_id, s.metric) for s in samples}
    metrics = {"availability", "cpu_percent", "memory_percent", "disk_used_percent",
               "network_in_bytes", "network_out_bytes"}
    assert {m for e, m in by if e == "web-1:9100"} == metrics
    assert {m for e, m in by if e == "web-2:9100"} == {"availability"}
    assert all(s.value == 0 for s in samples if s.external_id == "web-2:9100")
    assert all(s.ts.tzinfo is not None and s.ts <= NOW for s in samples)
    ranged = [r for r in fake.requests if r.url.path.endswith("query_range")]
    assert len(ranged) == 6  # one query per metric for the whole account
    assert all('job="node"' in r.url.params["query"] for r in ranged)


def test_nan_points_are_skipped():
    fake = FakeProm(targets=("web-1:9100", "mem-nan"), down=())
    samples = adapter(fake).fetch_metrics(ref(), adapter(fake).list_resources(ref()),
                                          NOW - timedelta(hours=1), NOW)
    assert not [s for s in samples if s.metric == "memory_percent" and s.value != s.value]
    assert not [s for s in samples if s.external_id == "web-1:9100"
                and s.metric == "memory_percent"]


def test_config_overrides_job_and_queries():
    fake = FakeProm()
    a = adapter(fake)
    cfg = {"job": 'my"job', "queries": {"cpu_percent": "up{{{sel}}} * 0 + 7"}}
    samples = a.fetch_metrics(ref(cfg), a.list_resources(ref(cfg)), NOW - timedelta(hours=1), NOW)
    queries = [r.url.params["query"] for r in fake.requests]
    assert all('job="my\\"job"' in q for q in queries)  # quotes escaped, no PromQL injection
    assert "up{job=\"my\\\"job\"} * 0 + 7" in queries
    assert any(s.metric == "cpu_percent" for s in samples)


def test_bearer_and_basic_auth():
    fake = FakeProm()
    adapter(fake).list_resources(ref(credentials={"token": "t0k"}))
    assert fake.requests[-1].headers["Authorization"] == "Bearer t0k"
    adapter(fake).list_resources(ref(credentials={"username": "u", "password": "p"}))
    assert fake.requests[-1].headers["Authorization"].startswith("Basic ")


def test_query_error_and_http_error_raise():
    def failing(request):
        return httpx.Response(200, json={"status": "error", "error": "parse error"})

    with pytest.raises(ValueError, match="parse error"):
        adapter(failing).list_resources(ref())
    with pytest.raises(httpx.HTTPStatusError):
        adapter(lambda r: httpx.Response(401)).list_resources(ref())


@pytest.mark.parametrize("ip", ["169.254.169.254", "10.0.0.5", "127.0.0.1", "192.168.1.2",
                                "::1", "fd00::1", "100.64.0.1"])
def test_url_guard_blocks_internal_addresses(ip):
    with pytest.raises(UnsafeUrl):
        check_url("https://looks-public.example.com", False, resolver(ip))


def test_url_guard_rules():
    check_url("https://prom.example.com", False, public)
    with pytest.raises(UnsafeUrl, match="https"):
        check_url("http://prom.example.com", False, public)
    with pytest.raises(UnsafeUrl, match="start with"):
        check_url("file:///etc/passwd", True, public)
    check_url("http://localhost:9090", True, resolver("127.0.0.1"))  # development

    calls = []
    fake = FakeProm()
    a = PrometheusAdapter(False, httpx.Client(transport=httpx.MockTransport(fake)),
                          resolve=lambda *a, **k: calls.append(a) or resolver("10.1.1.1")(*a))
    with pytest.raises(UnsafeUrl):
        a.list_resources(ref())
    assert calls and not fake.requests  # refused before any request is sent


def test_power_state_from_cloud_discovery_labels():
    assert power_state({}) == "running"
    assert power_state({"power_state": "PowerState/deallocated"}) == "deallocated"
    assert power_state({"power_state": "stopped", "cloud": "azure"}) == "stopped"
    # AWS and GCP don't bill stopped instances: same as Azure's deallocated
    assert power_state({"power_state": "stopped", "cloud": "aws"}) == "deallocated"
    assert power_state({"power_state": "TERMINATED", "cloud": "gcp"}) == "deallocated"
    assert power_state({"power_state": "weird"}) == "unknown"


def test_actions_not_supported():
    with pytest.raises(NotImplementedError, match="read-only"):
        adapter(FakeProm()).perform_action(ref(), "web-1:9100", "stop")


def test_factory_honours_private_url_setting():
    assert get_adapter("prometheus", make_settings())._allow_private is False
    assert get_adapter("prometheus", make_settings(allow_private_urls=True))._allow_private


def test_full_cycle_stores_samples_and_opens_incident_for_down_vm(db):  # noqa: F811
    fake = FakeProm()
    prom = adapter(fake)
    owner = uuid.uuid4()
    add_account(db, owner, URL, provider_id=5)
    result = run_cycle(db, make_settings(), lambda code: prom, now=NOW, backfill_hours=6)
    assert not result.errors
    with db() as s:
        names = set(s.scalars(select(Resource.name)))
        assert names == {"WEB-1", "WEB-2"}
        assert s.scalar(select(func.count()).select_from(MetricSample)) > 0
        down = s.scalars(select(Resource).where(Resource.name == "WEB-2")).one()
        incident = s.scalars(select(Incident).where(Incident.resource_id == down.id)).one()
        assert incident.ended_at is None
        assert not s.scalars(select(Incident).join(Resource)
                             .where(Resource.name == "WEB-1")).all()


@pytest.fixture
def api(make_database):
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from alembic import command
    from app.main import create_app
    from tests.conftest import alembic_cfg
    from tests.test_api import SECRET, Env

    url = make_database()
    command.upgrade(alembic_cfg(url), "head")
    engine = create_engine(url, connect_args={"prepare_threshold": None})
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = replace(make_settings(), supabase_jwt_secret=SECRET, database_url=url)
    prom = adapter(FakeProm())
    app = create_app(settings, factory,
                     lambda code: prom if code == "prometheus" else get_adapter(code, settings))
    yield Env(TestClient(app, raise_server_exceptions=False), factory)
    engine.dispose()


def test_api_prometheus_account_discovers_vms_and_is_read_only(api):
    _, h = api.user("ops@x.com")
    bad = api.client.post("/api/v1/cloud-accounts", headers=h, json={
        "name": "p", "provider": "prometheus", "external_ref": "prom.example.com"})
    assert bad.status_code == 422
    bad_source = api.client.post("/api/v1/cloud-accounts", headers=h, json={
        "name": "p", "provider": "prometheus", "external_ref": URL, "config": {"source": "snmp"}})
    assert bad_source.status_code == 422
    empty = api.client.post("/api/v1/cloud-accounts", headers=h, json={
        "name": "p", "provider": "prometheus", "external_ref": URL, "config": {"job": "nope"}})
    assert empty.status_code == 400 and "check the job name" in empty.json()["detail"]

    r = api.client.post("/api/v1/cloud-accounts", headers=h, json={
        "name": "Prod", "provider": "prometheus", "external_ref": URL + "/",
        "config": {"source": "node_exporter"}, "credentials": {"token": "t0k"}})
    assert r.status_code == 201, r.text
    assert r.json()["external_ref"] == URL and "credentials" not in r.json()
    vms = api.client.get("/api/v1/resources", headers=h).json()["items"]
    assert {v["name"] for v in vms} == {"WEB-1", "WEB-2"}
    assert all(v["attributes"]["provider"] == "prometheus" for v in vms)

    act = api.client.post(f"/api/v1/resources/{vms[0]['id']}/actions", headers=h,
                          json={"action": "restart"})
    assert act.status_code == 400
    assert "not available" in act.json()["detail"]
    collect = api.client.post(f"/api/v1/cloud-accounts/{r.json()['id']}/collect-now", headers=h)
    assert collect.status_code == 200 and collect.json()["samples_inserted"] > 0
