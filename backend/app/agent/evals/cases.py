"""Agent eval cases checked against the generator's ground truth (tool checks run in CI)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools import impl


@dataclass
class EvalContext:
    session: Session
    owner: Any
    other_owner: Any
    truth: dict  # generator ground-truth payload
    names: dict[str, str]  # generator resource id -> VM name (as stored in our DB)
    by_role: dict[str, list[str]] = field(default_factory=dict)  # role -> [VM names]

    def role(self, role: str) -> list[str]:
        return self.by_role[role]


@dataclass(frozen=True)
class EvalCase:
    """`question` may name VMs by role ({leak}); with `match_any` one expected name is enough."""
    id: str
    question: str
    check_tools: Callable[[EvalContext], None]
    expected_in_answer: Callable[[EvalContext], list[str]]
    match_any: bool = False

    def ask(self, ctx: EvalContext) -> str:
        return self.question.format(**{role: names[0] for role, names in ctx.by_role.items()})

    def passes(self, ctx: EvalContext, reply: str) -> bool:
        expected = [e.lower() for e in self.expected_in_answer(ctx)]
        hits = [e in reply.lower() for e in expected]
        return (any(hits) if self.match_any else all(hits)) if expected else bool(reply)


def _ranking(ctx: EvalContext) -> list[dict]:
    return impl.get_fleet_uptime(ctx.session, ctx.owner, 7)["ranking"]


def _truth_uptime(ctx: EvalContext, name: str) -> float:
    rid = next(i for i, n in ctx.names.items() if n == name)
    return ctx.truth["uptime_percent"][rid]


def c_most_downtime(ctx):
    assert _ranking(ctx)[0]["resource"] == ctx.role("unresponsive")[0]


def c_ranking_excludes_stopped(ctx):
    assert ctx.role("stopped")[0] not in {r["resource"] for r in _ranking(ctx)}


def c_uptime_matches_truth(ctx):
    name = ctx.role("flaky")[0]
    got = impl.get_uptime_summary(ctx.session, ctx.owner, name, 7)["uptime_percent"]
    assert abs(got - _truth_uptime(ctx, name)) < 1.0


def c_unresponsive_zero(ctx):
    name = ctx.role("unresponsive")[0]
    cfg = impl.get_resource_config(ctx.session, ctx.owner, name)
    assert cfg["power_state"] == "running"  # running yet unavailable
    assert impl.get_uptime_summary(ctx.session, ctx.owner, name, 7)["uptime_percent"] == 0


def c_memory_leak(ctx):
    # every leaking VM (there can be several) out-swings every other VM
    vms = impl.compare_metric(ctx.session, ctx.owner, "memory_percent", 7, limit=50)["vms"]
    by_range = sorted(vms, key=lambda r: r["range"], reverse=True)
    leaks = set(ctx.role("leak"))
    assert {r["resource"] for r in by_range[:len(leaks)]} == leaks


def c_memory_leak_range(ctx):
    s = impl.get_metric_stats(ctx.session, ctx.owner, ctx.role("leak")[0], "memory_percent", 7)
    assert s["max"] - s["min"] > 40 and s["max"] > 80


def c_memory_leak_anomaly(ctx):
    r = impl.find_anomalies(ctx.session, ctx.owner, ctx.role("leak")[0], "memory_percent", 7)
    assert r["count"] >= 1  # the restart drops memory sharply


def c_disk_filling(ctx):
    r = impl.forecast_disk_full(ctx.session, ctx.owner, ctx.role("disk")[0])
    assert r["enough_data"] and r["slope_percent_per_day"] > 3
    assert r["days_until_full"] is not None and r["days_until_full"] <= 12
    fleet = impl.forecast_fleet_disk(ctx.session, ctx.owner)
    assert fleet["filling_up"] and {f["resource"] for f in fleet["filling_up"]} <= set(
        ctx.role("disk"))


def c_disk_stable_elsewhere(ctx):
    r = impl.forecast_disk_full(ctx.session, ctx.owner, ctx.role("normal")[0])
    assert r["days_until_full"] is None or r["days_until_full"] > 365


def c_idle_vms(ctx):
    got = {u["resource"] for u in
           impl.find_underused_resources(ctx.session, ctx.owner, 14)["underused"]}
    assert got == set(ctx.role("idle")) and len(got) >= 2


def c_idle_cpu_low(ctx):
    s = impl.get_metric_stats(ctx.session, ctx.owner, ctx.role("idle")[0], "cpu_percent", 7)
    assert s["max"] < 8 and s["avg"] < 6


def c_stopped_vm(ctx):
    cfg = impl.get_resource_config(ctx.session, ctx.owner, ctx.role("stopped")[0])
    assert cfg["power_state"] == "stopped"


def c_flaky_incidents(ctx):
    name = ctx.role("flaky")[0]
    rid = next(i for i, n in ctx.names.items() if n == name)
    expected = [f for f in ctx.truth["faults"] if f["resource_id"] == rid
                and f["kind"] == "outage"]
    got = impl.list_incidents(ctx.session, ctx.owner, name, 7)["incidents"]
    assert abs(len(got) - len(expected)) <= 1 and len(got) >= 5
    assert len({i["started_at"][11:13] for i in got}) == 1  # always the same hour


def c_recommendations_present(ctx):
    recs = impl.list_recommendations(ctx.session, ctx.owner, "new")["recommendations"]
    cats = {r["category"] for r in recs}
    assert {"rightsizing", "waste", "pattern", "capacity"} <= cats
    assert all(r["evidence"] for r in recs)


def c_resolve_by_name_and_id(ctx):
    name = ctx.role("idle")[0]
    by_name = impl.get_resource_config(ctx.session, ctx.owner, name)
    by_id = impl.get_resource_config(ctx.session, ctx.owner, by_name["id"])
    assert by_name["id"] == by_id["id"] and by_name["tags"]


def c_other_tenant_sees_nothing(ctx):
    name = ctx.role("idle")[0]
    assert impl.get_resource_config(ctx.session, ctx.other_owner, name) == impl.NOT_FOUND
    assert impl.list_resources(ctx.session, ctx.other_owner)["total"] == 0
    assert impl.get_fleet_uptime(ctx.session, ctx.other_owner, 7)["ranking"] == []
    assert impl.list_recommendations(ctx.session, ctx.other_owner)["total"] == 0


def c_unknown_inputs(ctx):
    assert impl.get_uptime_summary(ctx.session, ctx.owner, "no-such-vm", 7) == impl.NOT_FOUND
    assert "error" in impl.get_metric_stats(ctx.session, ctx.owner, ctx.role("idle")[0], "bogus")


def c_save_recommendation(ctx):
    name = ctx.role("idle")[0]
    ok = impl.save_recommendation(ctx.session, ctx.owner, name, "rightsizing", "info",
                                  "Eval: downsize", "because", {"p95_cpu": 5})
    assert ok["saved"] is True
    again = impl.save_recommendation(ctx.session, ctx.owner, name, "rightsizing", "info",
                                     "Eval: downsize", "because", {"p95_cpu": 5})
    assert again["saved"] is False
    assert "error" in impl.save_recommendation(ctx.session, ctx.owner, name, "bogus", "info", "t",
                                               "d")
    assert impl.save_recommendation(ctx.session, ctx.other_owner, name, "waste", "info", "t",
                                    "d") == impl.NOT_FOUND


EVAL_CASES = [
    EvalCase("most-downtime", "Which VM had the most downtime this week?", c_most_downtime,
             lambda c: [c.role("unresponsive")[0]]),
    EvalCase("stopped-not-ranked", "Rank my VMs by uptime.", c_ranking_excludes_stopped,
             lambda c: [c.role("unresponsive")[0]]),
    EvalCase("flaky-uptime", "What was the uptime of {flaky} this week?",
             c_uptime_matches_truth, lambda c: [c.role("flaky")[0]]),
    EvalCase("running-but-down", "A VM shows as running but is not responding - which one?",
             c_unresponsive_zero, lambda c: [c.role("unresponsive")[0]]),
    EvalCase("memory-leak", "Which VM looks like it has a memory leak?", c_memory_leak,
             lambda c: c.role("leak"), match_any=True),
    EvalCase("memory-range", "How much does {leak}'s memory swing?", c_memory_leak_range,
             lambda c: [c.role("leak")[0]]),
    EvalCase("memory-anomaly", "Any memory anomalies on {leak} in the last week?",
             c_memory_leak_anomaly, lambda c: [c.role("leak")[0]]),
    EvalCase("disk-full", "Which VM will run out of disk first and when?", c_disk_filling,
             lambda c: c.role("disk"), match_any=True),
    EvalCase("disk-ok", "Is {normal}'s disk growing?", c_disk_stable_elsewhere,
             lambda c: [c.role("normal")[0]]),
    EvalCase("downsize", "What can I downsize?", c_idle_vms, lambda c: c.role("idle")),
    EvalCase("idle-cpu", "How busy is {idle}'s CPU?", c_idle_cpu_low,
             lambda c: [c.role("idle")[0]]),
    EvalCase("waste", "Am I paying for any VM that is stopped?", c_stopped_vm,
             lambda c: [c.role("stopped")[0]]),
    EvalCase("recurring-outage", "Does any VM fail at the same time every day?",
             c_flaky_incidents, lambda c: c.role("flaky"), match_any=True),
    EvalCase("recommendations", "What are my open recommendations?", c_recommendations_present,
             lambda c: ["rightsizing"]),
    EvalCase("resolve-name-id", "Show the config of {idle}.",
             c_resolve_by_name_and_id, lambda c: [c.role("idle")[0]]),
    EvalCase("tenant-scope", "Show me another user's VMs.", c_other_tenant_sees_nothing,
             lambda c: []),
    EvalCase("bad-input", "Uptime of a VM that does not exist?", c_unknown_inputs, lambda c: []),
    EvalCase("save-rec", "Save a rightsizing recommendation for {idle}.",
             c_save_recommendation, lambda c: [c.role("idle")[0]]),
]
