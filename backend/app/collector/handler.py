"""Single entrypoint a scheduler (e.g. Zoho Catalyst Cron) can call. Keep it trivial."""
from app.collector.run import run_once


def handler(event=None, context=None) -> dict:
    result = run_once()
    return {"accounts": result.accounts_processed, "samples": result.samples_inserted,
            "errors": len(result.errors)}
