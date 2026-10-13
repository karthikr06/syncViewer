from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from syncgen import control, engine
from syncgen.main import app


@pytest.fixture(autouse=True)
def clean():
    control.reset()
    yield
    control.reset()


def _vm(role: str):
    return next(v for v in engine.inventory("act", "small") if v.role == role)


def _series(client, vm, start, end):
    r = client.get("/v1/accounts/act/metrics", params={
        "scenario": "small", "resource_ids": vm.id, "metrics": "availability",
        "start": start.isoformat(), "end": end.isoformat()})
    pts = r.json()["series"]
    return pts[0]["points"] if pts else []


def test_actions_change_power_state_and_metrics():
    client = TestClient(app)
    stopped = _vm("stopped")
    url = f"/v1/accounts/act/resources/{stopped.id}/actions"
    assert client.post(url, json={"action": "stop"}).status_code == 409  # already stopped
    r = client.post(url, json={"action": "deallocate"})
    assert r.status_code == 200 and r.json() == {
        "id": stopped.id, "action": "deallocate", "from_state": "stopped",
        "power_state": "deallocated"}
    inv = client.get("/v1/accounts/act/resources", params={"scenario": "small"}).json()
    assert next(v for v in inv["resources"] if v["id"] == stopped.id)["power_state"] == \
        "deallocated"
    assert client.post(url, json={"action": "start"}).json()["power_state"] == "running"
    now = datetime.now(UTC)
    # running again: samples resume (healthy), but nothing before the start
    pts = _series(client, stopped, now - timedelta(hours=1), now + timedelta(minutes=10))
    assert pts and all(v == 1.0 for _, v in pts)
    assert all(datetime.fromisoformat(t.replace("Z", "+00:00")) >= now - timedelta(minutes=5)
               for t, _ in pts)


def test_restart_heals_unresponsive_vm():
    client = TestClient(app)
    vm = _vm("unresponsive")
    now = datetime.now(UTC)
    before = _series(client, vm, now - timedelta(hours=1), now)
    assert before and all(v == 0.0 for _, v in before)
    assert client.post(f"/v1/accounts/act/resources/{vm.id}/actions",
                       json={"action": "restart"}).status_code == 200
    after = _series(client, vm, now, now + timedelta(minutes=30))
    assert after and all(v == 1.0 for _, v in after)
    # history before the restart is unchanged
    assert _series(client, vm, now - timedelta(hours=1), now) == before


def test_unknown_vm_and_action():
    client = TestClient(app)
    assert client.post("/v1/accounts/act/resources/vm-nope/actions",
                       json={"action": "stop"}).status_code == 404
    vm = _vm("normal") if any(v.role == "normal" for v in engine.inventory("act", "small")) \
        else _vm("idle")
    assert client.post(f"/v1/accounts/act/resources/{vm.id}/actions",
                       json={"action": "explode"}).status_code == 409
