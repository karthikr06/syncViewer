# SyncViewer generator

A fake cloud provider. Standalone (no dependency on `backend/`). Output is a pure function of
`(account_ref, scenario, resource index, timestamp)`, so any time window can be queried or backfilled
and results are reproducible.

```
uvicorn syncgen.main:app --port 8100        # GENERATOR_API_KEY enables X-API-Key auth
GET /v1/scenarios                            # small=5, medium=25, large=300 VMs
GET /v1/accounts/{ref}/resources?scenario=
GET /v1/accounts/{ref}/metrics?scenario=&resource_ids=&metrics=&start=&end=&step=
GET /v1/accounts/{ref}/ground-truth?scenario=&start=&end=   # labelled faults, for tests/evals
GET /health
```

## Behaviours
| Role | What it does |
|---|---|
| normal | daily + weekly CPU/memory cycle + noise; random outages (~30% of days, 10-50 min) |
| flaky | outage of 15 min at the same UTC hour every day (recurring pattern) |
| leak | memory sawtooth (30% to 92% over 3 days, then reset) |
| disk | disk fills 40% to 95% over 10 days, then cleanup |
| idle | CPU ~3%, memory ~14%, oversized SKU (rightsizing) |
| unresponsive | power state `running` but availability always 0 |
| stopped | power state `stopped`, emits no metrics (waste) |

`small` has index 0-4 = leak, disk, idle, unresponsive, stopped. `medium`/`large` add a second idle
VM, a flaky VM and a repeating pattern. Uptime = share of samples with `availability == 1`.

Outages never span UTC days and align to a 5-minute grid, so a series' zero-runs equal the
ground-truth outage intervals exactly.

Tests: `python -m pytest` from this directory.
