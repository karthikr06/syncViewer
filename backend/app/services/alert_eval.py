import operator
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Resource
from app.repositories import alerts as alert_repo
from app.repositories import samples as sample_repo

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
SAMPLE_STEP = timedelta(minutes=5)


def evaluate_rules(session: Session, workspace_id: uuid.UUID, account_id: uuid.UUID,
                   resources: list[Resource], metric_codes: dict[int, str], now: datetime) -> int:
    """Open an alert when the condition held for the whole duration, resolve when it clears."""
    running = [r for r in resources if r.power_state == "running"]
    changes = 0
    for rule in alert_repo.rules_for_account(session, workspace_id, account_id):
        if rule.metric_id not in metric_codes:
            continue
        targets = [r for r in running if rule.resource_id in (None, r.id)]
        duration = timedelta(minutes=rule.duration_minutes)
        window = max(duration, 2 * SAMPLE_STEP)
        data = sample_repo.series(session, rule.metric_id, [r.id for r in targets], now - window,
                                  now + SAMPLE_STEP)
        active = alert_repo.unresolved(session, rule.id)
        compare = OPS[rule.operator]
        for res in targets:
            points = data.get(res.id, [])
            if not points:
                continue
            # enough history to claim the condition held for `duration`
            covered = points[0][0] <= now - duration + 2 * SAMPLE_STEP
            firing = covered and all(compare(v, rule.threshold) for _, v in points)
            current = active.get(res.id)
            if firing and current is None:
                alert_repo.open_alert(session, rule.id, res.id, points[-1][1], now)
                changes += 1
            elif not firing and current is not None and not compare(points[-1][1], rule.threshold):
                alert_repo.resolve(current, now)
                changes += 1
    session.flush()
    return changes
