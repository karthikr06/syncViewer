from datetime import datetime

from sqlalchemy.orm import Session

from app.models import CollectorRun


def start(session: Session, started_at: datetime) -> CollectorRun:
    run = CollectorRun(started_at=started_at)
    session.add(run)
    session.flush()
    return run


def finish(run: CollectorRun, finished_at: datetime, accounts: int, samples: int,
           errors: list[dict]) -> None:
    run.finished_at = finished_at
    run.accounts_processed = accounts
    run.samples_inserted = samples
    run.errors = len(errors)
    run.error_details = errors or None
