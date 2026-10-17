"""One collection cycle. The account is the unit of work: one transaction, one failure domain."""
from __future__ import annotations

import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.agent.rules.engine import RuleConfig
from app.collector.adapters import ProviderAdapter, get_adapter
from app.collector.dto import AccountRef
from app.core.config import Settings
from app.core.crypto import decrypt_credentials
from app.repositories import accounts as account_repo
from app.repositories import insights as insight_repo
from app.repositories import lookups
from app.repositories import resources as resource_repo
from app.repositories import runs as run_repo
from app.repositories import samples as sample_repo
from app.services import alert_eval, digests, incidents, recommendations

log = logging.getLogger("collector")

OVERLAP = timedelta(minutes=15)  # re-fetch recent data; idempotent inserts make this safe

AdapterFactory = Callable[[str], ProviderAdapter]


@dataclass
class CycleResult:
    accounts_processed: int = 0
    samples_inserted: int = 0
    errors: list[dict] = field(default_factory=list)


def account_ref(account, provider_code: str, settings: Settings) -> AccountRef:
    creds = {}
    if account.credentials_encrypted is not None:
        creds = decrypt_credentials(settings.credential_encryption_key,
                                    account.credentials_encrypted)
    return AccountRef(str(account.id), provider_code, account.external_ref,
                      dict(account.config or {}), creds)


def process_account(session: Session, account_id: uuid.UUID, provider_code: str,
                    adapter: ProviderAdapter, settings: Settings, now: datetime,
                    backfill_hours: int = 24, rule_config: RuleConfig | None = None) -> int:
    """Collect one account inside the caller's transaction. Returns samples inserted."""
    account = account_repo.get(session, account_id)
    if account is None:
        return 0
    ref = account_ref(account, provider_code, settings)
    metric_ids = lookups.metric_ids(session)
    type_id = lookups.resource_type_id(session, provider_code, "vm")
    if type_id is None:
        raise RuntimeError(f"no 'vm' resource type for provider {provider_code}")

    dtos = adapter.list_resources(ref)
    resources = resource_repo.sync_inventory(session, account.id, type_id, dtos, now)

    since = account.last_collected_at or (now - timedelta(hours=backfill_hours))
    # after a long pause catch up on the last `backfill_hours` only, so one cycle stays short
    since = max(since, now - timedelta(hours=backfill_hours))
    fetch_from = since - OVERLAP
    by_ext = {r.external_id: r for r in resources}
    live = [d for d in dtos if d.external_id in by_ext]
    inserted = 0
    samples = adapter.fetch_metrics(ref, live, fetch_from, now)
    rows = [
        {"resource_id": by_ext[s.external_id].id, "metric_id": metric_ids[s.metric],
         "ts": s.ts, "value": s.value}
        for s in samples if s.external_id in by_ext and s.metric in metric_ids
    ]
    if rows:
        inserted = sample_repo.insert_idempotent(session, rows)
        sample_repo.compute_rollup(session, min(r["ts"] for r in rows),
                                   max(r["ts"] for r in rows))
    incidents.update_incidents(session, resources, metric_ids["availability"], fetch_from)
    alert_eval.evaluate_rules(session, account.workspace_id, account.id, resources,
                              {v: k for k, v in metric_ids.items()}, now)
    recommendations.run_recommendation_rules(session, account.workspace_id, resources, now,
                                             rule_config)
    account_repo.mark_success(session, account, now)
    session.flush()
    return inserted


def _digests(session_factory: sessionmaker[Session], now: datetime) -> None:
    """Daily/weekly digests per owner; failures are logged, never fatal to the cycle."""
    with session_factory() as s:
        owners = insight_repo.workspace_ids_with_accounts(s)
    for owner in owners:
        with session_factory() as s:
            try:
                digests.ensure_periodic(s, owner, now)
                s.commit()
            except Exception:  # noqa: BLE001
                s.rollback()
                log.exception("digest generation failed for %s", owner)


def run_cycle(
    session_factory: sessionmaker[Session],
    settings: Settings,
    adapter_factory: AdapterFactory | None = None,
    now: datetime | None = None,
    backfill_hours: int = 24,
    jitter_seconds: float = 0.0,
    rule_config: RuleConfig | None = None,
) -> CycleResult:
    now = now or datetime.now(UTC)
    factory = adapter_factory or (lambda code: get_adapter(code, settings))
    result = CycleResult()

    with session_factory() as s:
        run = run_repo.start(s, now)
        s.commit()
        run_id = run.id
        targets = account_repo.list_collectable(s)

    for i, target in enumerate(targets):
        if i and jitter_seconds:
            time.sleep(random.uniform(0, jitter_seconds))
        session = session_factory()
        try:
            adapter = factory(target.provider_code)
            result.samples_inserted += process_account(
                session, target.id, target.provider_code, adapter, settings, now,
                backfill_hours, rule_config)
            session.commit()
            result.accounts_processed += 1
        except Exception as exc:  # noqa: BLE001 - isolation: one account must not stop the rest
            session.rollback()
            msg = f"{type(exc).__name__}: {exc}"
            log.warning("account %s failed: %s", target.id, msg)
            result.errors.append({"account_id": str(target.id), "error": msg[:500]})
            try:
                account_repo.mark_error(session, target.id, msg)
                session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
        finally:
            session.close()

    if result.accounts_processed:
        _digests(session_factory, now)

    with session_factory() as s:
        purged = sample_repo.purge_older_than(
            s, now - timedelta(days=settings.raw_retention_days))
        run = s.get(type(run), run_id)
        run_repo.finish(run, datetime.now(UTC), result.accounts_processed,
                        result.samples_inserted, result.errors)
        s.commit()
        log.info("cycle done: %d accounts, %d samples, %d errors, %d purged",
                 result.accounts_processed, result.samples_inserted, len(result.errors), purged)
    return result
