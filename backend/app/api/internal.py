"""Scheduler hook: start a collection cycle in the background and answer at once."""
import hmac
import logging
import threading

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.deps import get_settings
from app.collector.cycle import run_cycle
from app.core.config import Settings

log = logging.getLogger("api.internal")
router = APIRouter(prefix="/internal", tags=["internal"])
_running = threading.Lock()  # one cycle at a time per process


@router.post("/collect", status_code=202)
def collect(request: Request, token: str = "",
            x_collector_token: str | None = Header(default=None),
            settings: Settings = Depends(get_settings)) -> dict[str, str]:
    """`COLLECTOR_TOKEN` in the X-Collector-Token header (or ?token=); 404 when not configured."""
    given = x_collector_token or token
    if not settings.collector_token or not hmac.compare_digest(given, settings.collector_token):
        raise HTTPException(404, "Not found")
    if not _running.acquire(blocking=False):
        return {"status": "already running"}

    def work() -> None:
        try:
            r = run_cycle(request.app.state.session_factory, settings,
                          request.app.state.adapter_factory, jitter_seconds=1.0)
            log.info("scheduled cycle: %d accounts, %d samples, %d errors",
                     r.accounts_processed, r.samples_inserted, len(r.errors))
        except Exception:  # noqa: BLE001 - a failed cycle must not take the API down
            log.exception("scheduled cycle failed")
        finally:
            _running.release()

    request.app.state.collector_thread = threading.Thread(target=work, name="collector",
                                                          daemon=True)
    request.app.state.collector_thread.start()
    return {"status": "started"}
