"""Deterministic insight digests (rules only; an LLM narrative may be layered on later)."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import InsightDigest
from app.repositories import insights as repo


def build_summary(session: Session, owner: uuid.UUID, start: datetime, end: datetime) -> str:
    uptime = repo.fleet_uptime(session, owner, start, end)
    incidents = repo.incidents_between(session, owner, start, end)
    recs = repo.new_recommendations(session, owner)
    open_alerts = repo.open_alert_count(session, owner)
    days = max(1, round((end - start).total_seconds() / 86400))

    lines = [f"## Summary for the last {days} day{'s' if days != 1 else ''}", ""]
    measured = [u for u in uptime if u.total]
    if measured:
        up, total = sum(u.up for u in measured), sum(u.total for u in measured)
        lines.append(f"- **Fleet uptime:** {100 * up / total:.2f}% across {len(measured)} VMs")
    else:
        lines.append("- **Fleet uptime:** no data yet")
    lines.append(f"- **Incidents:** {len(incidents)}   **Open alerts:** {open_alerts}   "
                 f"**New recommendations:** {len(recs)}")

    worst = sorted((u for u in measured if u.percent is not None and u.percent < 100),
                   key=lambda u: u.percent)[:5]
    if worst:
        lines += ["", "### Lowest uptime", "", "| VM | Uptime |", "|---|---|"]
        lines += [f"| {u.name} | {u.percent:.2f}% |" for u in worst]
    if recs:
        lines += ["", "### Top recommendations", ""]
        lines += [f"- **{r.severity.upper()}** ({r.category}): {r.title}" for r in recs]
    return "\n".join(lines)


def generate(session: Session, owner: uuid.UUID, now: datetime, days: int = 1) -> InsightDigest:
    start = now - timedelta(days=days)
    return repo.add_digest(session, owner, start, now, build_summary(session, owner, start, now))


def ensure_periodic(session: Session, owner: uuid.UUID, now: datetime) -> int:
    """Create a daily and a weekly digest when the last one of that kind is stale."""
    made = 0
    for days, lo, hi, every in ((1, 0.9, 1.1, timedelta(hours=24)),
                                (7, 6.9, 7.1, timedelta(days=7))):
        last = repo.latest_digest_end(session, owner, lo, hi)
        if last is None or now - last >= every:
            generate(session, owner, now, days)
            made += 1
    return made
