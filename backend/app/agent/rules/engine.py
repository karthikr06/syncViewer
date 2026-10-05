"""Deterministic recommendation rules. Pure functions over plain facts (no DB, no LLM).

Every finding carries `evidence`: the metric, window, observed values and threshold used.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RuleConfig:
    rightsizing_cpu_p95: float = 20.0
    rightsizing_memory_p95: float = 40.0
    rightsizing_window_days: int = 14
    rightsizing_min_hours: int = 18
    disk_high_percent: float = 85.0
    disk_forecast_days: float = 14.0
    disk_min_hours: int = 12
    disk_min_slope_per_day: float = 1.0
    pattern_min_days: int = 3
    pattern_window_days: int = 14
    closed_cooldown_days: int = 7


@dataclass(frozen=True)
class RollupPoint:
    bucket_start: datetime
    avg_cpu: float | None
    p95_cpu: float | None
    avg_memory: float | None
    max_disk: float | None


@dataclass
class ResourceFacts:
    id: uuid.UUID
    name: str
    power_state: str
    size_sku: str | None
    rollups: list[RollupPoint] = field(default_factory=list)
    outage_starts: list[datetime] = field(default_factory=list)


@dataclass
class AccountFacts:
    owner_has_alert_rules: bool
    resources: list[ResourceFacts]


@dataclass(frozen=True)
class Finding:
    category: str
    severity: str
    title: str
    detail: str
    evidence: dict
    dedupe_key: str
    resource_id: uuid.UUID | None = None


def percentile(values: list[float], q: float) -> float:
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def linear_slope_per_day(points: list[tuple[datetime, float]]) -> float:
    """Least-squares slope in value units per day."""
    n = len(points)
    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 86400 for t, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denom


def rightsizing(facts: AccountFacts, cfg: RuleConfig) -> list[Finding]:
    out = []
    for r in facts.resources:
        if r.power_state != "running":
            continue
        cpu = [p.p95_cpu for p in r.rollups if p.p95_cpu is not None]
        mem = [p.avg_memory for p in r.rollups if p.avg_memory is not None]
        if len(cpu) < cfg.rightsizing_min_hours or len(mem) < cfg.rightsizing_min_hours:
            continue
        cpu_p95, mem_p95 = percentile(cpu, 0.95), percentile(mem, 0.95)
        if cpu_p95 < cfg.rightsizing_cpu_p95 and mem_p95 < cfg.rightsizing_memory_p95:
            out.append(Finding(
                "rightsizing", "info", f"{r.name} is oversized",
                f"p95 CPU {cpu_p95:.1f}% and p95 memory {mem_p95:.1f}% over the observed window; "
                "a smaller size would likely cost less with no impact.",
                {"metrics": ["cpu_percent", "memory_percent"], "window_hours": len(cpu),
                 "window_days": cfg.rightsizing_window_days, "p95_cpu": round(cpu_p95, 2),
                 "p95_memory": round(mem_p95, 2), "cpu_threshold": cfg.rightsizing_cpu_p95,
                 "memory_threshold": cfg.rightsizing_memory_p95, "size_sku": r.size_sku},
                f"rightsizing:{r.id}", r.id))
    return out


def reliability(facts: AccountFacts, cfg: RuleConfig) -> list[Finding]:
    out = []
    active = [r for r in facts.resources]
    if len(active) == 1:
        r = active[0]
        out.append(Finding(
            "reliability", "warning", f"{r.name} is the only VM in this account",
            "A single VM has no redundancy; an outage means full downtime.",
            {"resource_count": 1}, f"reliability:single-vm:{r.id}", r.id))
    if not facts.owner_has_alert_rules:
        out.append(Finding(
            "reliability", "warning", "No alert rules defined",
            "Without alert rules you will not be notified about CPU, memory, disk or outages.",
            {"alert_rules": 0}, "reliability:no-alert-rules", None))
    return out


def capacity(facts: AccountFacts, cfg: RuleConfig) -> list[Finding]:
    out = []
    for r in facts.resources:
        pts = [(p.bucket_start, p.max_disk) for p in r.rollups if p.max_disk is not None]
        # a cleanup shows up as a sudden drop: only the growth after the last one is a trend
        for i in range(len(pts) - 1, 0, -1):
            if pts[i][1] < pts[i - 1][1] - 10:
                pts = pts[i:]
                break
        if r.power_state != "running" or len(pts) < cfg.disk_min_hours:
            continue
        latest = pts[-1][1]
        slope = linear_slope_per_day(pts)
        days_left = (100 - latest) / slope if slope > 0 else None
        evidence = {"metric": "disk_used_percent", "window_hours": len(pts),
                    "latest_percent": round(latest, 2), "slope_percent_per_day": round(slope, 3),
                    "threshold_percent": cfg.disk_high_percent,
                    "forecast_days": cfg.disk_forecast_days}
        if latest >= cfg.disk_high_percent:
            out.append(Finding(
                "capacity", "critical", f"{r.name} disk is {latest:.0f}% full",
                "Disk usage is above the safe threshold.", evidence,
                f"capacity:disk-high:{r.id}", r.id))
        elif (slope >= cfg.disk_min_slope_per_day and days_left is not None
              and days_left <= cfg.disk_forecast_days):
            evidence["projected_days_to_full"] = round(days_left, 1)
            out.append(Finding(
                "capacity", "warning", f"{r.name} disk projected full in {days_left:.0f} days",
                f"Disk grows ~{slope:.1f} points/day and is at {latest:.0f}%.", evidence,
                f"capacity:disk-forecast:{r.id}", r.id))
    return out


def waste(facts: AccountFacts, cfg: RuleConfig) -> list[Finding]:
    return [
        Finding("waste", "warning", f"{r.name} is stopped but not deallocated",
                "A stopped (not deallocated) VM still incurs compute charges. Deallocate or "
                "delete it.", {"power_state": r.power_state, "size_sku": r.size_sku},
                f"waste:stopped:{r.id}", r.id)
        for r in facts.resources if r.power_state == "stopped"
    ]


def pattern(facts: AccountFacts, cfg: RuleConfig) -> list[Finding]:
    out = []
    for r in facts.resources:
        days_by_hour: dict[int, set] = defaultdict(set)
        for s in r.outage_starts:
            days_by_hour[s.hour].add(s.date())
        for hour, days in sorted(days_by_hour.items()):
            if len(days) >= cfg.pattern_min_days:
                out.append(Finding(
                    "pattern", "warning", f"{r.name} fails around {hour:02d}:00 UTC",
                    f"{len(days)} outages started in the {hour:02d}:00 UTC hour on different "
                    "days. Look for a scheduled job, backup or deployment at that time.",
                    {"hour_utc": hour, "occurrences": len(days), "min_days": cfg.pattern_min_days,
                     "days": sorted(d.isoformat() for d in days)},
                    f"pattern:hour:{r.id}:{hour}", r.id))
    return out


ALL_RULES = (rightsizing, reliability, capacity, waste, pattern)


def run_rules(facts: AccountFacts, cfg: RuleConfig | None = None) -> list[Finding]:
    cfg = cfg or RuleConfig()
    return [f for rule in ALL_RULES for f in rule(facts, cfg)]
