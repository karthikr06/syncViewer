# Monitoring real VMs through Prometheus

SyncViewer can watch real machines in **Azure, AWS, GCP or anywhere else** through one
**Prometheus** account. Prometheus (or any server with its query API: Grafana Cloud, Thanos,
Mimir, VictoriaMetrics) holds the metrics; SyncViewer reads them every collection and runs the
usual uptime, incidents, alerts, recommendations and AI assistant on top.

```
VMs ──► Prometheus ◄── SyncViewer collector (PrometheusAdapter, read-only)
```

Prometheus accounts are **read-only**: SyncViewer can't start, stop or deallocate these VMs, so
the power buttons and one-click fixes are hidden for them.

## Two ways VMs can report
| | node_exporter (default) | OpenTelemetry Collector |
|---|---|---|
| How | Prometheus **scrapes** each VM on port 9100 | each VM **pushes** to Prometheus (remote write or OTLP) |
| Network | Prometheus must reach every VM | VMs only need outbound HTTPS |
| Down VM | `up` = 0: Prometheus tried and the VM didn't answer | the VM goes quiet: no data in a 5-minute step counts as down |
| VM disappears from SyncViewer | when it leaves Prometheus' target list | after 7 days without data |
| Region, size, cloud | `relabel_configs` from cloud discovery | `resourcedetection` processor (azure, ec2, gcp detectors) |
| Pick it for | local demo, VMs Prometheus can reach | VMs behind firewalls, several clouds, Grafana Cloud |

With either one, **you never add VMs one by one in SyncViewer**: add the Prometheus account once,
and every VM in its job shows up (and new ones appear on the next collection).

## Try it locally
```bash
docker compose --profile monitoring up -d prometheus node-exporter otel-collector
```
This starts a Prometheus on <http://localhost:9090>, a node_exporter (`demo-vm-1`), an
OpenTelemetry Collector (`demo-vm-2`) and a target that is always down (`offline-vm`). Then in
SyncViewer, **Cloud accounts > Add account**:

| Field | node_exporter account | OpenTelemetry account |
|---|---|---|
| Provider | Prometheus | Prometheus |
| Prometheus URL | `http://localhost:9090` (`http://prometheus:9090` if the API runs in Docker) | same |
| How the VMs report | node_exporter | OpenTelemetry Collector |
| Job name | empty (defaults to `node`) | empty (defaults to `hosts`) |
| Authentication | None | None |

Press **Collect now** after a few minutes (rates need 5 minutes of data). `offline-vm` shows as
unavailable with an open outage incident.

Private addresses such as `localhost` are allowed only while `ALLOW_PRIVATE_URLS` is on: by
default in development, never in production. A hosted SyncViewer needs a Prometheus with a public
HTTPS address.

## Adding an Azure VM
**Option A: node_exporter + Azure discovery** (Prometheus can reach the VMs, e.g. it runs in the
same virtual network)
1. Once: create a service principal with the **Reader** role on the subscription, and uncomment
   the `azure_sd_configs` job in `deploy/monitoring/prometheus.yml` with its ids and secret.
   Prometheus now lists every VM in the subscription by itself.
2. Per VM: install node_exporter (most Linux distributions: `sudo apt install
   prometheus-node-exporter`) and allow port 9100 from Prometheus in the VM's network security
   group.
3. The VM appears in SyncViewer on the next collection, with region and size from Azure.

**Option B: OpenTelemetry Collector** (VMs push; nothing inbound to open)
1. Once: a Prometheus with a public HTTPS address and remote write turned on
   (`--web.enable-remote-write-receiver`), or Grafana Cloud's free hosted Prometheus.
2. Per VM: install the OpenTelemetry Collector (contrib build) with
   `deploy/monitoring/otel-collector.yaml`, set the exporter `endpoint` to your Prometheus, and
   use `detectors: [azure, system]` so region and VM size are filled in automatically.
3. The VM appears in SyncViewer as soon as its data arrives (next collection).

AWS and GCP work the same way: `ec2_sd_configs` / `gce_sd_configs` for option A, or the `ec2` /
`gcp` detectors for option B.

## Account settings
| Field | Meaning |
|---|---|
| Prometheus URL | the base URL (the API is `<url>/api/v1/...`) |
| How the VMs report | `node_exporter` or `otel` (`config.source`) |
| Job name | Prometheus `job` label; `node` / `hosts` by default |
| Authentication | none, a bearer token, or a username and password (Grafana Cloud: instance id and an access policy token) |

Advanced, through the API (`config`): `id_label` (what makes a VM, default `instance`),
`name_label`, `region_label`, `size_label`, `cloud_label`, and `queries` to replace the PromQL of
any metric (for example Windows exporter metrics). In a query, `{sel}` is the job matcher and
`{id}` the id label; literal braces are doubled.

## What SyncViewer reads
| Metric | node_exporter | OpenTelemetry (hostmetrics) |
|---|---|---|
| availability | `up` | data present in the step (`target_info`) |
| cpu_percent | non-idle share of `node_cpu_seconds_total` | non-idle share of `system_cpu_time_seconds_total` |
| memory_percent | `1 - MemAvailable / MemTotal` | `used` / all states except `slab_*` |
| disk_used_percent | root filesystem, like `df` | root filesystem, like `df` |
| network in/out | bytes per second, all devices except `lo` | same |

Labels that are not the id, name, region or size become the VM's tags.

## Limits
- **No power actions** and no one-click fixes for these VMs.
- **Stopped or crashed?** Prometheus alone can't tell. A VM that doesn't answer counts as running
  and unavailable, so it opens an incident even if someone shut it down on purpose. Copying a
  cloud's power state into a `power_state` target label fixes that where discovery provides one.
- **"Stopped but not deallocated" advice** only appears when a `power_state` label says
  `stopped` on Azure; AWS and GCP don't bill compute for stopped instances.
- The figures are as good as Prometheus' scrape interval and retention; SyncViewer catches up on
  at most the last 24 hours, so the default 15-day retention is plenty.
