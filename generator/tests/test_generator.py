import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from syncgen.main import app

client = TestClient(app)
T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)  # a Monday


def q(start, end, **extra):
    return {"start": start.isoformat(), "end": end.isoformat(), **extra}


def test_health_and_scenarios():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/v1/scenarios").json() == {"small": 5, "medium": 25, "large": 300}


@pytest.mark.parametrize("scenario,n", [("small", 5), ("medium", 25), ("large", 300)])
def test_inventory_sizes(scenario, n):
    r = client.get("/v1/accounts/acc1/resources", params={"scenario": scenario}).json()
    assert len(r["resources"]) == n
    assert len({x["id"] for x in r["resources"]}) == n


def test_deterministic():
    p = q(T0, T0 + timedelta(days=2), scenario="medium")
    a = client.get("/v1/accounts/acc1/metrics", params=p).json()
    b = client.get("/v1/accounts/acc1/metrics", params=p).json()
    assert a == b and a["series"]
    c = client.get("/v1/accounts/other/metrics", params=p).json()
    assert a != c


def test_window_is_consistent_across_queries():
    """A sub-window equals the matching slice of a larger window (pure function of time)."""
    big = client.get("/v1/accounts/acc1/metrics",
                     params=q(T0, T0 + timedelta(days=1), metrics="cpu_percent")).json()
    small = client.get("/v1/accounts/acc1/metrics",
                       params=q(T0 + timedelta(hours=6), T0 + timedelta(hours=7),
                                metrics="cpu_percent")).json()
    for s in small["series"]:
        full = next(x for x in big["series"] if x["resource_id"] == s["resource_id"])
        lookup = dict(map(tuple, full["points"]))
        assert all(lookup[t] == v for t, v in s["points"])


def _availability_zero_runs(points):
    runs, start, prev = [], None, None
    for ts, v in points:
        if v == 0 and start is None:
            start = ts
        if v == 1 and start is not None:
            runs.append((start, ts))
            start = None
        prev = ts
    if start is not None:
        runs.append((start, None))
    return runs, prev


def test_ground_truth_matches_series():
    end = T0 + timedelta(days=7)
    params = q(T0, end, scenario="medium")
    gt = client.get("/v1/accounts/acc1/ground-truth", params=params).json()
    series = client.get("/v1/accounts/acc1/metrics",
                        params={**params, "metrics": "availability"}).json()["series"]
    by_res = {s["resource_id"]: s["points"] for s in series}
    roles = {r["id"]: r["role"] for r in gt["resources"]}
    def iso(s):
        return s.replace("Z", "+00:00")

    checked = 0
    for rid, pts in by_res.items():
        if roles[rid] == "unresponsive":
            assert all(v == 0 for _, v in pts)
            assert gt["uptime_percent"][rid] == 0
            continue
        expected = sorted(
            (datetime.fromisoformat(iso(f["start"])), datetime.fromisoformat(iso(f["end"])))
            for f in gt["faults"] if f["resource_id"] == rid and f["kind"] == "outage")
        runs, _ = _availability_zero_runs(pts)
        got = sorted((datetime.fromisoformat(iso(a)),
                      datetime.fromisoformat(iso(b)) if b else end) for a, b in runs)
        assert got == expected, rid
        up = 100 * sum(v for _, v in pts) / len(pts)
        assert gt["uptime_percent"][rid] == pytest.approx(up, abs=1e-3)
        checked += 1
    assert checked >= 20


def test_scenario_behaviours_present():
    gt = client.get("/v1/accounts/acc1/ground-truth",
                    params=q(T0, T0 + timedelta(days=7), scenario="medium")).json()
    roles = [r["role"] for r in gt["resources"]]
    for needed in ("leak", "disk", "unresponsive", "stopped", "flaky"):
        assert needed in roles
    assert roles.count("idle") >= 2
    flaky = next(r["id"] for r in gt["resources"] if r["role"] == "flaky")
    outs = [f for f in gt["faults"] if f["resource_id"] == flaky and f["kind"] == "outage"]
    assert len(outs) == 7 and len({f["start"][11:13] for f in outs}) == 1  # same hour daily


def test_resource_shapes():
    gt = client.get("/v1/accounts/acc1/ground-truth",
                    params=q(T0, T0 + timedelta(days=7), scenario="small")).json()
    role = {r["role"]: r["id"] for r in gt["resources"]}
    series = client.get("/v1/accounts/acc1/metrics", params=q(
        T0, T0 + timedelta(days=7), metrics="cpu_percent,memory_percent,disk_used_percent",
        step=3600)).json()["series"]

    def vals(rid, metric):
        return [v for s in series if s["resource_id"] == rid and s["metric"] == metric
                for _, v in s["points"]]

    assert max(vals(role["idle"], "cpu_percent")) < 8
    mem = vals(role["leak"], "memory_percent")
    assert max(mem) - min(mem) > 40
    disk = vals(role["disk"], "disk_used_percent")
    assert max(disk) > 60 and disk[-1] != disk[0]
    assert vals(role["stopped"], "cpu_percent") == []  # stopped VM emits no metrics


def test_api_key_enforced(monkeypatch):
    monkeypatch.setenv("GENERATOR_API_KEY", "k")
    assert client.get("/v1/scenarios").status_code == 401
    assert client.get("/v1/scenarios", headers={"X-API-Key": "k"}).status_code == 200
    assert client.get("/health").status_code == 200


def test_validation():
    assert client.get("/v1/accounts/a/resources", params={"scenario": "nope"}).status_code == 404
    bad = client.get("/v1/accounts/a/metrics", params=q(T0, T0 + timedelta(hours=1), metrics="x"))
    assert bad.status_code == 422


def test_large_scenario_cycle_is_fast():
    """A 5-minute collection cycle asks for ~15 min of data for every VM."""
    t = time.perf_counter()
    r = client.get("/v1/accounts/acc1/metrics",
                   params=q(T0, T0 + timedelta(minutes=15), scenario="large"))
    cycle = time.perf_counter() - t
    assert r.status_code == 200 and len(r.json()["series"]) > 1000
    assert cycle < 2.0
    t = time.perf_counter()  # a 24 h first-run backfill
    r = client.get("/v1/accounts/acc1/metrics",
                   params=q(T0, T0 + timedelta(days=1), scenario="large"))
    assert r.status_code == 200
    assert time.perf_counter() - t < 15
