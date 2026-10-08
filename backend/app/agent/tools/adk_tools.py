"""ADK-facing wrappers: plain typed functions with docstrings (these become the tool schema).

`tool_context` is injected by ADK and hidden from the model. The workspace id is read from session
state, which the API sets from the authenticated request -- tools never take a user id argument.
"""
import uuid
from collections.abc import Callable
from typing import Any

from google.adk.tools import ToolContext
from sqlalchemy.orm import Session, sessionmaker

from app.agent.tools import impl

_factory: sessionmaker[Session] | None = None


def configure(factory: sessionmaker[Session]) -> None:
    global _factory
    _factory = factory


def _call(tool_context: ToolContext, fn: Callable, *args: Any, **kwargs: Any) -> dict:
    if _factory is None:
        return {"error": "tools are not configured"}
    owner = tool_context.state.get("workspace_id")
    if not owner:
        return {"error": "no authenticated user"}
    with _factory() as session:
        result = fn(session, uuid.UUID(owner), *args, **kwargs)
        session.commit()
        return result


def list_resources(tool_context: ToolContext, query: str = "") -> dict:
    """List the user's VMs (id, name, region, size, power and health state).

    Args:
        query: optional text to match against VM names.
    """
    return _call(tool_context, impl.list_resources, query)


def get_resource_config(tool_context: ToolContext, resource: str) -> dict:
    """Get configuration and latest metric values of one VM.

    Args:
        resource: VM id or exact name.
    """
    return _call(tool_context, impl.get_resource_config, resource)


def get_uptime_summary(tool_context: ToolContext, resource: str, days: int = 7) -> dict:
    """Uptime percentage, incident count and downtime minutes for one VM.

    Args:
        resource: VM id or exact name.
        days: look-back window in days (1-14).
    """
    return _call(tool_context, impl.get_uptime_summary, resource, days)


def get_fleet_uptime(tool_context: ToolContext, days: int = 7) -> dict:
    """Rank every VM by uptime (lowest first) with downtime minutes. Use this to answer
    'which VM had the most downtime'.

    Args:
        days: look-back window in days (1-14).
    """
    return _call(tool_context, impl.get_fleet_uptime, days)


def list_incidents(tool_context: ToolContext, resource: str, days: int = 7) -> dict:
    """List outages for one VM with start, end and duration.

    Args:
        resource: VM id or exact name.
        days: look-back window in days (1-14).
    """
    return _call(tool_context, impl.list_incidents, resource, days)


def get_metric_stats(tool_context: ToolContext, resource: str, metric: str, days: int = 7) -> dict:
    """Average, min, p95, max and per-day trend of a metric for one VM.

    Args:
        resource: VM id or exact name.
        metric: one of availability, cpu_percent, memory_percent, disk_used_percent,
            network_in_bytes, network_out_bytes.
        days: look-back window in days (1-14).
    """
    return _call(tool_context, impl.get_metric_stats, resource, metric, days)


def compare_metric(tool_context: ToolContext, metric: str, days: int = 7) -> dict:
    """Compare one metric across ALL VMs in a single call (avg, min, p95, max, range, trend),
    highest p95 first. Use this instead of calling get_metric_stats once per VM, e.g. for
    'which VM uses the most memory' or 'which VM looks like a memory leak'.

    Args:
        metric: one of availability, cpu_percent, memory_percent, disk_used_percent,
            network_in_bytes, network_out_bytes.
        days: look-back window in days (1-14).
    """
    return _call(tool_context, impl.compare_metric, metric, days)


def forecast_fleet_disk(tool_context: ToolContext) -> dict:
    """Disk-full forecast for ALL VMs in one call; the ones filling up come first, soonest first.
    Use this for 'which VM will run out of disk first'."""
    return _call(tool_context, impl.forecast_fleet_disk)


def find_anomalies(tool_context: ToolContext, resource: str, metric: str, days: int = 3) -> dict:
    """Find unusual spikes or drops in a metric (EWMA z-score computed in code).

    Args:
        resource: VM id or exact name.
        metric: metric code, e.g. cpu_percent.
        days: look-back window in days (1-14).
    """
    return _call(tool_context, impl.find_anomalies, resource, metric, days)


def find_underused_resources(tool_context: ToolContext, days: int = 14) -> dict:
    """Find VMs whose p95 CPU and memory are low (rightsizing candidates), with evidence.

    Args:
        days: look-back window in days (1-14).
    """
    return _call(tool_context, impl.find_underused_resources, days)


def forecast_disk_full(tool_context: ToolContext, resource: str) -> dict:
    """Project when a VM's disk will be full using a linear trend.

    Args:
        resource: VM id or exact name.
    """
    return _call(tool_context, impl.forecast_disk_full, resource)


def list_recommendations(tool_context: ToolContext, status: str = "new") -> dict:
    """List existing recommendations (from the rules engine or earlier agent runs).

    Args:
        status: new, dismissed or done.
    """
    return _call(tool_context, impl.list_recommendations, status)


def save_recommendation(tool_context: ToolContext, resource: str, category: str, severity: str,
                        title: str, detail: str, evidence_json: str = "{}") -> dict:
    """Save a recommendation for the user. Only call after verifying the numbers with other tools.

    Args:
        resource: VM id or exact name, or empty for an account-wide recommendation.
        category: rightsizing, reliability, capacity, waste or pattern.
        severity: info, warning or critical.
        title: short headline.
        detail: explanation including impact and effort.
        evidence_json: JSON object with the metric, window and values that justify it.
    """
    import json

    if tool_context.state.get("role") not in ("admin", "developer"):
        return {"error": "read-only account: viewers cannot save recommendations"}
    try:
        evidence = json.loads(evidence_json or "{}")
        if not isinstance(evidence, dict):
            raise ValueError
    except ValueError:
        return {"error": "evidence_json must be a JSON object"}
    return _call(tool_context, impl.save_recommendation, resource, category, severity, title,
                 detail, evidence)


ANALYST_TOOLS = [list_resources, get_resource_config, get_uptime_summary, get_fleet_uptime,
                 list_incidents, get_metric_stats, compare_metric, find_anomalies,
                 list_recommendations]
ADVISOR_TOOLS = [list_resources, get_resource_config, find_underused_resources,
                 get_metric_stats, compare_metric, forecast_disk_full, forecast_fleet_disk,
                 list_recommendations, save_recommendation]
