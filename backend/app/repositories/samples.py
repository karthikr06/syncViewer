import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import MetricSample, UptimeRollup

CHUNK = 5000


def insert_idempotent(session: Session, rows: list[dict]) -> int:
    """ON CONFLICT DO NOTHING on the (resource, metric, ts) key; returns rows actually inserted."""
    inserted = 0
    for i in range(0, len(rows), CHUNK):
        stmt = (pg_insert(MetricSample).values(rows[i:i + CHUNK]).on_conflict_do_nothing()
                .returning(MetricSample.metric_id))
        inserted += len(session.execute(stmt).all())  # RETURNING yields only inserted rows
    return inserted


def compute_rollup(session: Session, from_ts: datetime, to_ts: datetime) -> int:
    """The single wrapper around the compute_uptime_rollup stored function."""
    return session.execute(select(func.compute_uptime_rollup(from_ts, to_ts))).scalar_one()


def series(session: Session, metric_id: int, resource_ids: list[uuid.UUID], from_ts: datetime,
           to_ts: datetime | None = None) -> dict[uuid.UUID, list[tuple[datetime, float]]]:
    if not resource_ids:
        return {}
    stmt = (select(MetricSample.resource_id, MetricSample.ts, MetricSample.value)
            .where(MetricSample.metric_id == metric_id,
                   MetricSample.resource_id.in_(resource_ids), MetricSample.ts >= from_ts)
            .order_by(MetricSample.resource_id, MetricSample.ts))
    if to_ts is not None:
        stmt = stmt.where(MetricSample.ts < to_ts)
    out: dict[uuid.UUID, list[tuple[datetime, float]]] = defaultdict(list)
    for rid, ts, value in session.execute(stmt):
        out[rid].append((ts, value))
    return out


def purge_older_than(session: Session, cutoff: datetime) -> int:
    return session.execute(delete(MetricSample).where(MetricSample.ts < cutoff)).rowcount or 0


def rollups_since(session: Session, resource_ids: list[uuid.UUID], since: datetime
                  ) -> dict[uuid.UUID, list[UptimeRollup]]:
    out: dict[uuid.UUID, list[UptimeRollup]] = defaultdict(list)
    if not resource_ids:
        return out
    stmt = (select(UptimeRollup)
            .where(UptimeRollup.resource_id.in_(resource_ids), UptimeRollup.bucket_start >= since)
            .order_by(UptimeRollup.resource_id, UptimeRollup.bucket_start))
    for r in session.scalars(stmt):
        out[r.resource_id].append(r)
    return out
