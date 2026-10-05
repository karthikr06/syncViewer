"""`python -m app.collector.run` runs exactly one cycle."""
import logging

from app.collector.cycle import CycleResult, run_cycle
from app.core.config import load_settings_or_exit
from app.core.db import get_session_factory

REQUIRED = ["DATABASE_URL", "CREDENTIAL_ENCRYPTION_KEY"]


def run_once() -> CycleResult:
    settings = load_settings_or_exit(REQUIRED)
    return run_cycle(get_session_factory(settings.database_url), settings, jitter_seconds=1.0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    r = run_once()
    print(f"accounts={r.accounts_processed} samples={r.samples_inserted} errors={len(r.errors)}")
