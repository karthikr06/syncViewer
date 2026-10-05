from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Resource
from app.repositories import incidents as incident_repo
from app.repositories import samples as sample_repo

MIN_FAILED_SAMPLES = 2  # one failed probe is treated as noise


def detect_outages(samples: list[tuple[datetime, float]], min_failed: int = MIN_FAILED_SAMPLES
                   ) -> list[tuple[datetime, datetime | None]]:
    """Runs of consecutive availability==0 samples -> (first failed ts, first recovered ts|None)."""
    runs: list[tuple[datetime, datetime | None]] = []
    start: datetime | None = None
    count = 0
    for ts, value in samples:
        if value != 1:
            if start is None:
                start, count = ts, 0
            count += 1
        elif start is not None:
            if count >= min_failed:
                runs.append((start, ts))
            start = None
    if start is not None and count >= min_failed:
        runs.append((start, None))
    return runs


def update_incidents(session: Session, resources: list[Resource], availability_metric_id: int,
                     scan_from: datetime, min_failed: int = MIN_FAILED_SAMPLES) -> int:
    """Create new incidents and close ones that recovered. Returns the number of changes."""
    running = [r for r in resources if r.power_state == "running"]
    ids = [r.id for r in running]
    # still-open incidents must be re-scanned from their start so they can be closed
    open_starts = [i.started_at for i in incident_repo.in_scope(session, ids, scan_from)
                   if i.ended_at is None]
    window_from = min([scan_from, *open_starts])
    existing = incident_repo.in_scope(session, ids, window_from)
    data = sample_repo.series(session, availability_metric_id, ids, window_from)
    by_key = {(i.resource_id, i.started_at, i.kind): i for i in existing}
    changes = 0
    for rid in ids:
        for start, end in detect_outages(data.get(rid, []), min_failed):
            inc = by_key.get((rid, start, "outage"))
            if inc is None:
                incident_repo.add(session, rid, start, end)
                changes += 1
            elif inc.ended_at is None and end is not None:
                inc.ended_at = end
                changes += 1
    session.flush()
    return changes
