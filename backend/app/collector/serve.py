"""`python -m app.collector.serve` runs cycles forever (local dev / Docker)."""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.collector.run import REQUIRED, run_once
from app.core.config import load_settings_or_exit


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = load_settings_or_exit(REQUIRED)
    sched = BlockingScheduler()
    # max_instances=1 + coalesce: a slow cycle never overlaps itself
    sched.add_job(run_once, "interval", seconds=settings.collect_interval_seconds,
                  max_instances=1, coalesce=True)
    logging.getLogger("collector").info("running every %ss", settings.collect_interval_seconds)
    run_once()
    sched.start()


if __name__ == "__main__":
    main()
