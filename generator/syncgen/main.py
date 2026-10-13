import os
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from syncgen import control, engine

app = FastAPI(title="SyncViewer Generator", docs_url="/docs")
MAX_POINTS = 2_000_000


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("GENERATOR_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid api key")


def _scenario(name: str) -> str:
    if name not in engine.SCENARIOS:
        raise HTTPException(status_code=404, detail=f"unknown scenario {name!r}")
    return name


def _dt(value: str) -> datetime:
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bad timestamp {value!r}") from exc
    return d if d.tzinfo else d.replace(tzinfo=UTC)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/scenarios", dependencies=[Depends(require_key)])
def scenarios() -> dict[str, int]:
    return engine.SCENARIOS


@app.get("/v1/accounts/{account_ref}/resources", dependencies=[Depends(require_key)])
def resources(account_ref: str, scenario: str = "small") -> dict:
    vms = engine.inventory(account_ref, _scenario(scenario))
    return {"resources": [
        {"id": v.id, "name": v.name, "type": "vm", "region": v.region, "size_sku": v.size_sku,
         "power_state": control.power_state(account_ref, v), "tags": v.tags,
         "attributes": {"os": "linux", "disk_gb": 128}}
        for v in vms]}


@app.get("/v1/accounts/{account_ref}/metrics", dependencies=[Depends(require_key)])
def metrics(
    account_ref: str,
    start: str,
    end: str,
    scenario: str = "small",
    resource_ids: str = "",
    metrics: str = "",
    step: int = Query(300, ge=60, le=86400),
) -> dict:
    vms = engine.inventory(account_ref, _scenario(scenario))
    wanted_ids = {r for r in resource_ids.split(",") if r}
    wanted = [m for m in metrics.split(",") if m] or list(engine.METRICS)
    bad = [m for m in wanted if m not in engine.METRICS]
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown metrics {bad}")
    s, e = _dt(start), _dt(end)
    n_points = len(engine.grid_times(s, e, step))
    selected = [v for v in vms if not wanted_ids or v.id in wanted_ids]
    if n_points * len(selected) * len(wanted) > MAX_POINTS:
        raise HTTPException(status_code=413, detail="window too large; narrow the query")
    out = []
    for vm in selected:
        for m in wanted:
            if control.has_events(account_ref, vm):  # power actions change behaviour over time
                pts = []
                for t in engine.grid_times(s, e, step):
                    acting = control.behaviour_at(account_ref, vm, t)
                    if acting is not None:
                        pts.append((t, engine.value(acting, m, t)))
            else:
                pts = engine.series(vm, m, s, e, step)
            if pts:
                out.append({"resource_id": vm.id, "metric": m, "unit": engine.METRICS[m],
                            "points": [[engine.iso(t), v] for t, v in pts]})
    return {"series": out}


@app.get("/v1/accounts/{account_ref}/ground-truth", dependencies=[Depends(require_key)])
def ground_truth(account_ref: str, start: str, end: str, scenario: str = "small") -> dict:
    return engine.ground_truth(account_ref, _scenario(scenario), _dt(start), _dt(end))


class ActionBody(BaseModel):
    action: str


@app.post("/v1/accounts/{account_ref}/resources/{vm_id}/actions",
          dependencies=[Depends(require_key)])
def act(account_ref: str, vm_id: str, body: ActionBody, scenario: str = "small") -> dict:
    """Start, stop, restart or deallocate a demo VM (kept in memory)."""
    vms = engine.inventory(account_ref, _scenario(scenario))
    vm = next((v for v in vms if v.id == vm_id), None)
    if vm is None:
        raise HTTPException(status_code=404, detail="unknown VM")
    try:
        before, after = control.apply(account_ref, vm, body.action,
                                      int(datetime.now(UTC).timestamp()))
    except control.ActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": vm.id, "action": body.action, "from_state": before, "power_state": after}
