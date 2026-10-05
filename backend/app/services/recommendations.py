import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.agent.rules.engine import (
    AccountFacts,
    Finding,
    ResourceFacts,
    RollupPoint,
    RuleConfig,
    run_rules,
)
from app.models import Resource
from app.repositories import alerts as alert_repo
from app.repositories import incidents as incident_repo
from app.repositories import recommendations as rec_repo
from app.repositories import samples as sample_repo


def gather_facts(session: Session, owner_id: uuid.UUID, resources: list[Resource], now: datetime,
                 cfg: RuleConfig) -> AccountFacts:
    ids = [r.id for r in resources]
    window = timedelta(days=max(cfg.rightsizing_window_days, cfg.pattern_window_days))
    rollups = sample_repo.rollups_since(session, ids, now - window)
    incidents = incident_repo.in_scope(session, ids, now - timedelta(days=cfg.pattern_window_days))
    starts: dict[uuid.UUID, list[datetime]] = {}
    for inc in incidents:
        if inc.kind == "outage":
            starts.setdefault(inc.resource_id, []).append(inc.started_at)
    return AccountFacts(
        owner_has_alert_rules=alert_repo.owner_has_rules(session, owner_id),
        resources=[
            ResourceFacts(
                id=r.id, name=r.name, power_state=r.power_state, size_sku=r.size_sku,
                rollups=[RollupPoint(u.bucket_start, u.avg_cpu, u.p95_cpu, u.avg_memory,
                                     u.max_disk) for u in rollups.get(r.id, [])],
                outage_starts=starts.get(r.id, []))
            for r in resources
        ])


def persist_findings(session: Session, owner_id: uuid.UUID, findings: list[Finding],
                     now: datetime, cfg: RuleConfig) -> int:
    """Insert new recommendations; leave existing open ones alone unless severity changed;
    do not re-raise something the user dismissed/completed within the cooldown."""
    changes = 0
    cooldown_start = now - timedelta(days=cfg.closed_cooldown_days)
    for f in findings:
        existing = rec_repo.open_by_key(session, owner_id, f.dedupe_key)
        if existing is not None:
            if existing.severity != f.severity:
                existing.severity, existing.detail, existing.evidence = (
                    f.severity, f.detail, f.evidence)
                changes += 1
            continue
        if rec_repo.recently_closed(session, owner_id, f.dedupe_key, cooldown_start):
            continue
        rec_repo.add(session, owner_id=owner_id, resource_id=f.resource_id, category=f.category,
                     severity=f.severity, title=f.title, detail=f.detail, evidence=f.evidence,
                     source="rule", dedupe_key=f.dedupe_key)
        changes += 1
    session.flush()
    return changes


def run_recommendation_rules(session: Session, owner_id: uuid.UUID, resources: list[Resource],
                             now: datetime, cfg: RuleConfig | None = None) -> int:
    cfg = cfg or RuleConfig()
    facts = gather_facts(session, owner_id, resources, now, cfg)
    return persist_findings(session, owner_id, run_rules(facts, cfg), now, cfg)
