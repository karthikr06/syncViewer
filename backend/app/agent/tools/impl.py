"""Deterministic, owner-scoped analysis tools.

Code computes, the LLM explains: every number the agent quotes comes from here. Each function
takes (session, owner_id, ...) -- the owner comes from the authenticated request, never from the
model -- and reads through the same owner-scoped repositories as the API. Resources may be given
by id, external id or exact name; anything not owned by the caller is simply "not found".
"""
from __future__ import annotations

import hashlib
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agent.rules.engine import RuleConfig, linear_slope_per_day, percentile, rightsizing
from app.models import Recommendation
from app.repositories import insights as insight_repo
from app.repositories import lookups, owned
from app.repositories import recommendations as rec_repo
from app.repositories import samples as sample_repo
from app.services.recommendations import gather_facts

MAX_DAYS = 14  # raw samples are retained for RAW_RETENTION_DAYS
SAMPLE_MINUTES = 5
CATEGORIES = ("rightsizing", "reliability", "capacity", "waste", "pattern")
SEVERITIES = ("info", "warning", "critical")
NOT_FOUND = {"error": "resource not found"}


def _days(days: int) -> int:
    return max(1, min(int(days), MAX_DAYS))


def _now() -> datetime:
    return datetime.now(UTC)


def _resolve(session: Session, owner: uuid.UUID, key: str):
    return owned.find_resource(session, owner, key.strip()) if key else None


def _iso(ts: datetime | None) -> str | None:
    return ts.astimezone(UTC).isoformat() if ts else None


def list_resources(session: Session, owner: uuid.UUID, query: str = "", limit: int = 50) -> dict:
    rows, total, _, _ = owned.list_resources(session, owner, query or None, None, None, None,
                                             None, 1, max(1, min(limit, 100)), None)
    return {"total": total, "resources": [
        {"id": str(r.id), "name": r.name, "region": r.region, "size_sku": r.size_sku,
         "power_state": r.power_state, "health_state": r.health_state} for r in rows]}


def get_resource_config(session: Session, owner: uuid.UUID, resource: str) -> dict:
    res = _resolve(session, owner, resource)
    if res is None:
        return NOT_FOUND
    return {"id": str(res.id), "name": res.name, "region": res.region, "size_sku": res.size_sku,
            "power_state": res.power_state, "health_state": res.health_state, "tags": res.tags,
            "attributes": res.attributes, "first_seen_at": _iso(res.first_seen_at),
            "latest_metrics": owned.latest_values(session, res.id)}


def _uptime(session: Session, owner: uuid.UUID, rid: uuid.UUID, start: datetime, end: datetime):
    rows = insight_repo.fleet_uptime(session, owner, start, end)
    rows = [u for u in rows if u.resource_id == rid]
    return rows[0] if rows else None


def get_uptime_summary(session: Session, owner: uuid.UUID, resource: str, days: int = 7) -> dict:
    res = _resolve(session, owner, resource)
    if res is None:
        return NOT_FOUND
    days = _days(days)
    end = _now()
    row = _uptime(session, owner, res.id, end - timedelta(days=days), end)
    incidents = owned.incidents_for(session, owner, res.id, end - timedelta(days=days))
    downtime = sum(((i.ended_at or end) - i.started_at).total_seconds() / 60 for i in incidents
                   if i.started_at >= end - timedelta(days=days))
    return {"resource": res.name, "days": days,
            "uptime_percent": None if row is None or row.percent is None
            else round(row.percent, 3),
            "up_samples": row.up if row else 0, "total_samples": row.total if row else 0,
            "observed_hours": round((row.total if row else 0) * SAMPLE_MINUTES / 60, 1),
            "incident_count": len(incidents), "downtime_minutes": round(downtime, 1),
            "definition": "uptime = share of 5-minute samples where availability == 1"}


def get_fleet_uptime(session: Session, owner: uuid.UUID, days: int = 7) -> dict:
    """All VMs ranked from lowest uptime to highest, with downtime minutes."""
    days = _days(days)
    end = _now()
    rows = [u for u in insight_repo.fleet_uptime(session, owner, end - timedelta(days=days), end)
            if u.total]
    rows.sort(key=lambda u: u.percent)
    observed = max((u.total for u in rows), default=0) * SAMPLE_MINUTES / 60
    return {"days": days, "observed_hours": round(observed, 1),
            "note": "if observed_hours is below days*24, say how much history there is",
            "ranking": [
                {"resource": u.name, "resource_id": str(u.resource_id),
                 "uptime_percent": round(u.percent, 3),
                 "downtime_minutes": (u.total - u.up) * SAMPLE_MINUTES} for u in rows]}


def list_incidents(session: Session, owner: uuid.UUID, resource: str, days: int = 7) -> dict:
    res = _resolve(session, owner, resource)
    if res is None:
        return NOT_FOUND
    days = _days(days)
    end = _now()
    items = owned.incidents_for(session, owner, res.id, end - timedelta(days=days))
    return {"resource": res.name, "days": days, "incidents": [
        {"kind": i.kind, "started_at": _iso(i.started_at), "ended_at": _iso(i.ended_at),
         "minutes": round(((i.ended_at or end) - i.started_at).total_seconds() / 60, 1),
         "ongoing": i.ended_at is None} for i in items]}


def _samples(session: Session, owner: uuid.UUID, res, metric: str, days: int):
    metric_id = lookups.metric_ids(session).get(metric)
    if metric_id is None:
        return None
    since = _now() - timedelta(days=days)
    return sample_repo.series(session, metric_id, [res.id], since).get(res.id, [])


def get_metric_stats(session: Session, owner: uuid.UUID, resource: str, metric: str,
                     days: int = 7) -> dict:
    res = _resolve(session, owner, resource)
    if res is None:
        return NOT_FOUND
    days = _days(days)
    pts = _samples(session, owner, res, metric, days)
    if pts is None:
        return {"error": f"unknown metric {metric!r}"}
    if not pts:
        return {"resource": res.name, "metric": metric, "days": days, "samples": 0}
    values = [v for _, v in pts]
    return {"resource": res.name, "metric": metric, "days": days, "samples": len(values),
            "avg": round(sum(values) / len(values), 3), "min": round(min(values), 3),
            "p95": round(percentile(values, 0.95), 3), "max": round(max(values), 3),
            "trend_per_day": round(linear_slope_per_day(pts), 4) if len(pts) > 2 else 0.0}


def compare_metric(session: Session, owner: uuid.UUID, metric: str, days: int = 7,
                   limit: int = 10) -> dict:
    """Every VM's stats for one metric in a single call, highest p95 first."""
    days = _days(days)
    metric_id = lookups.metric_ids(session).get(metric)
    if metric_id is None:
        return {"error": f"unknown metric {metric!r}"}
    resources = {r.id: r for r in owned.all_resources(session, owner)}
    series = sample_repo.series(session, metric_id, list(resources), _now() - timedelta(days=days))
    rows = []
    for rid, pts in series.items():
        if not pts:
            continue
        values = [v for _, v in pts]
        rows.append({"resource": resources[rid].name, "samples": len(values),
                     "avg": round(sum(values) / len(values), 3), "min": round(min(values), 3),
                     "p95": round(percentile(values, 0.95), 3), "max": round(max(values), 3),
                     "range": round(max(values) - min(values), 3),
                     "trend_per_day": round(linear_slope_per_day(pts), 4) if len(pts) > 2
                     else 0.0})
    rows.sort(key=lambda r: r["p95"], reverse=True)
    return {"metric": metric, "days": days, "vm_count": len(rows),
            "vms": rows[:max(1, min(int(limit), 50))],
            "hint": "a memory leak shows as a large range (steady climb, then a drop on restart)"}


def find_anomalies(session: Session, owner: uuid.UUID, resource: str, metric: str,
                   days: int = 3, z_threshold: float = 4.0) -> dict:
    """EWMA residual z-score: flags points far from the recent smoothed level."""
    res = _resolve(session, owner, resource)
    if res is None:
        return NOT_FOUND
    days = _days(days)
    pts = _samples(session, owner, res, metric, days)
    if pts is None:
        return {"error": f"unknown metric {metric!r}"}
    alpha, mean, var, found = 0.1, None, 0.0, []
    for i, (ts, v) in enumerate(pts):
        if mean is not None and i > 12 and var > 0:
            z = (v - mean) / math.sqrt(var)
            if abs(z) >= z_threshold:
                found.append({"ts": _iso(ts), "value": round(v, 3), "z": round(z, 2)})
        if mean is None:
            mean = v
        else:
            diff = v - mean
            mean += alpha * diff
            var = (1 - alpha) * (var + alpha * diff * diff)
    return {"resource": res.name, "metric": metric, "days": days, "method": "ewma_zscore",
            "z_threshold": z_threshold, "count": len(found), "anomalies": found[:10]}


def find_underused_resources(session: Session, owner: uuid.UUID, days: int = 14) -> dict:
    days = _days(days)
    resources = owned.all_resources(session, owner)
    cfg = RuleConfig(rightsizing_window_days=days)
    facts = gather_facts(session, owner, resources, _now(), cfg)
    findings = rightsizing(facts, cfg)
    return {"days": days, "count": len(findings), "underused": [
        {"resource": f.title.removesuffix(" is oversized"), "resource_id": str(f.resource_id),
         "evidence": f.evidence} for f in findings]}


def forecast_disk_full(session: Session, owner: uuid.UUID, resource: str) -> dict:
    res = _resolve(session, owner, resource)
    if res is None:
        return NOT_FOUND
    since = _now() - timedelta(days=MAX_DAYS)
    rolls = sample_repo.rollups_since(session, [res.id], since).get(res.id, [])
    return _disk_forecast(res.name, rolls)


def forecast_fleet_disk(session: Session, owner: uuid.UUID) -> dict:
    """Disk forecast for every VM in one call; VMs that will fill up come first, soonest first."""
    resources = {r.id: r for r in owned.all_resources(session, owner)}
    rolls = sample_repo.rollups_since(session, list(resources), _now() - timedelta(days=MAX_DAYS))
    rows = [_disk_forecast(resources[rid].name, rolls.get(rid, [])) for rid in resources]
    filling = sorted((r for r in rows if r.get("days_until_full") is not None),
                     key=lambda r: r["days_until_full"])
    return {"method": "linear_trend", "filling_up": filling,
            "stable_count": len(rows) - len(filling)}


def _disk_forecast(name: str, rolls) -> dict:
    pts = [(r.bucket_start, r.max_disk) for r in rolls if r.max_disk is not None]
    for i in range(len(pts) - 1, 0, -1):  # only growth since the last cleanup is a trend
        if pts[i][1] < pts[i - 1][1] - 10:
            pts = pts[i:]
            break
    if len(pts) < 6:
        return {"resource": name, "method": "linear_trend", "enough_data": False}
    slope = linear_slope_per_day(pts)
    latest = pts[-1][1]
    days_left = (100 - latest) / slope if slope > 0.05 else None
    return {"resource": name, "method": "linear_trend", "enough_data": True,
            "latest_percent": round(latest, 2), "slope_percent_per_day": round(slope, 3),
            "days_until_full": None if days_left is None else round(days_left, 1)}


def list_recommendations(session: Session, owner: uuid.UUID, status: str = "new") -> dict:
    rows, total, _, _ = owned.list_recommendations(session, owner, status or None, None, None,
                                                   None, 1, 50)
    return {"total": total, "recommendations": [
        {"id": r.id, "category": r.category, "severity": r.severity, "title": r.title,
         "detail": r.detail, "evidence": r.evidence, "status": r.status, "source": r.source}
        for r in rows]}


def save_recommendation(session: Session, owner: uuid.UUID, resource: str, category: str,
                        severity: str, title: str, detail: str,
                        evidence: dict[str, Any] | None = None) -> dict:
    """The agent's only write: a row in `recommendations`, owned by the caller."""
    if category not in CATEGORIES or severity not in SEVERITIES:
        return {"error": f"category must be one of {CATEGORIES}, severity one of {SEVERITIES}"}
    title, detail = title.strip()[:200], detail.strip()[:4000]
    if not title:
        return {"error": "title is required"}
    res = _resolve(session, owner, resource) if resource else None
    if resource and res is None:
        return NOT_FOUND
    key = "agent:{}:{}:{}".format(category, res.id if res else "-",
                                  hashlib.sha1(title.lower().encode()).hexdigest()[:10])
    existing = rec_repo.open_by_key(session, owner, key)
    if existing is not None:
        return {"saved": False, "reason": "already exists", "id": existing.id}
    rec: Recommendation = rec_repo.add(
        session, owner_id=owner, resource_id=res.id if res else None, category=category,
        severity=severity, title=title, detail=detail, evidence=evidence or {}, source="agent",
        dedupe_key=key)
    session.flush()
    return {"saved": True, "id": rec.id}
