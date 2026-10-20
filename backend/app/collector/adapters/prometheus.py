"""Read-only adapter for any Prometheus-compatible query API (Prometheus, Grafana Cloud, Thanos...).

One account = one Prometheus server and job. Every distinct value of the id label (default
`instance`) is a VM. Two metric sources are supported (`config.source`):

- `node_exporter` (default): Prometheus scrapes each VM, so `up` says whether the VM answered.
  Prometheus can discover VMs in Azure, AWS and GCP itself (azure_sd_configs, ec2_sd_configs,
  gce_sd_configs), so this one adapter monitors all three clouds.
- `otel`: an OpenTelemetry Collector on each VM (hostmetrics receiver) pushes to Prometheus via
  remote write or OTLP. There is no `up`: a VM is available while its data keeps arriving, and
  VMs that sent nothing for 7 days drop out of the inventory.

The adapter cannot start or stop VMs.

Account fields: `external_ref` is the base URL; `config` may set `source`, `job`, `id_label`,
`name_label`, `region_label`, `size_label`, `cloud_label` and `queries` (per-metric PromQL
overrides); `credentials` may hold `token` (bearer) or `username` + `password` (basic auth,
e.g. Grafana Cloud).
"""
import ipaddress
import json
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from app.collector.dto import AccountRef, MetricSampleDTO, ResourceDTO

STEP_SECONDS = 300
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
# In `queries`, `{sel}` is the series selector (job matcher) and `{id}` the id label.
# Network is bytes per second.
SOURCES: dict[str, dict] = {
    "node_exporter": {
        "labels": {"job": "node", "id_label": "instance", "name_label": "nodename",
                   "region_label": "region", "size_label": "instance_type",
                   "cloud_label": "cloud"},
        "inventory": "up{{{sel}}}",
        "health": "max by ({id}) (up{{{sel}}})",
        "names": "last_over_time(node_uname_info{{{sel}}}[1d])",
        "lag": timedelta(0),
        "queries": {
            "availability": "max by ({id}) (up{{{sel}}})",
            "cpu_percent": "100 * (1 - avg by ({id}) "
                           '(rate(node_cpu_seconds_total{{{sel},mode="idle"}}[5m])))',
            "memory_percent": "100 * (1 - max by ({id}) (node_memory_MemAvailable_bytes{{{sel}}})"
                              " / max by ({id}) (node_memory_MemTotal_bytes{{{sel}}}))",
            # like `df`: used / (used + what a normal user can still write); blocks reserved
            # for root count as neither
            "disk_used_percent": "100 * (1 - max by ({id}) "
                                 '(node_filesystem_avail_bytes{{{sel},mountpoint="/"}})'
                                 " / max by ({id}) (node_filesystem_size_bytes"
                                 '{{{sel},mountpoint="/"}} - node_filesystem_free_bytes'
                                 '{{{sel},mountpoint="/"}} + node_filesystem_avail_bytes'
                                 '{{{sel},mountpoint="/"}}))',
            "network_in_bytes": "sum by ({id}) (rate(node_network_receive_bytes_total"
                                '{{{sel},device!="lo"}}[5m]))',
            "network_out_bytes": "sum by ({id}) (rate(node_network_transmit_bytes_total"
                                 '{{{sel},device!="lo"}}[5m]))',
        },
    },
    "otel": {
        # resource attributes (resourcedetection processor) arrive on target_info
        "labels": {"job": "hosts", "id_label": "instance", "name_label": "host_name",
                   "region_label": "cloud_region", "size_label": "host_type",
                   "cloud_label": "cloud_provider"},
        "inventory": "last_over_time(target_info{{{sel}}}[7d])",
        "health": "max by ({id}) (present_over_time(target_info{{{sel}}}[10m]))",
        "names": None,  # target_info carries the host name already
        # pushed data lands a little late; asking for the newest minutes would read as "down"
        # and the idempotent insert would keep that wrong 0 for good
        "lag": timedelta(minutes=2),
        "queries": {
            # 1 while data arrives, 0 for VMs seen in the last 7 days that went quiet
            "availability": "max by ({id}) (present_over_time(target_info{{{sel}}}[5m]))"
                            " or max by ({id}) (last_over_time(target_info{{{sel}}}[7d])) * 0",
            "cpu_percent": "100 * (1 - sum by ({id}) "
                           '(rate(system_cpu_time_seconds_total{{{sel},state="idle"}}[5m]))'
                           " / sum by ({id}) (rate(system_cpu_time_seconds_total{{{sel}}}[5m])))",
            # slab_* states overlap the others, so they are left out of the total
            "memory_percent": "100 * sum by ({id}) "
                              '(system_memory_usage_bytes{{{sel},state="used"}})'
                              " / sum by ({id}) "
                              '(system_memory_usage_bytes{{{sel},state!~"slab_.*"}})',
            # like `df`: hostmetrics' "free" is what a normal user can still write
            "disk_used_percent": "100 * sum by ({id}) (system_filesystem_usage_bytes"
                                 '{{{sel},mountpoint="/",state="used"}})'
                                 " / sum by ({id}) (system_filesystem_usage_bytes"
                                 '{{{sel},mountpoint="/",state=~"used|free"}})',
            "network_in_bytes": "sum by ({id}) (rate(system_network_io_bytes_total"
                                '{{{sel},direction="receive",device!="lo"}}[5m]))',
            "network_out_bytes": "sum by ({id}) (rate(system_network_io_bytes_total"
                                 '{{{sel},direction="transmit",device!="lo"}}[5m]))',
        },
    },
}
# Labels that describe the scrape or the export, not the VM, so they are not copied into tags.
NOT_TAGS = {"__name__", "job", "power_state", "otel_scope_name", "otel_scope_version"}
POWER = {"running": "running", "stopping": "stopped", "stopped": "stopped",
         "deallocating": "deallocated", "deallocated": "deallocated",
         "terminated": "deallocated", "suspended": "deallocated"}


class PrometheusError(ValueError):
    """A problem the user can fix in the account settings; the message is safe to show."""


class UnsafeUrl(PrometheusError):
    """The Prometheus URL points somewhere the API must not call (private network, metadata...)."""


def check_url(url: str, allow_private: bool,
              resolve: Callable[..., list] = socket.getaddrinfo) -> None:
    """Block requests to internal addresses, e.g. the cloud metadata service 169.254.169.254."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeUrl("The Prometheus URL must start with http:// or https://.")
    if allow_private:
        return
    if parts.scheme != "https":
        raise UnsafeUrl("The Prometheus URL must use https://.")
    try:
        infos = resolve(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrl("The Prometheus host name could not be resolved.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeUrl("The Prometheus URL points to a private or reserved address.")


def power_state(labels: dict[str, str], cloud_label: str = "cloud") -> str:
    """From a `power_state` target label (relabelled from cloud discovery), else assume running.

    AWS and GCP don't bill compute for stopped instances, which is what "deallocated" means here.
    """
    raw = labels.get("power_state", "").lower().removeprefix("powerstate/")
    if not raw:
        return "running"  # a known VM that does not answer is running but unresponsive
    state = POWER.get(raw, "unknown")
    cloud = labels.get(cloud_label, "").lower()
    if state == "stopped" and (cloud in ("aws", "gcp") or cloud.startswith("gcp_")):
        return "deallocated"
    return state


def source_of(config: dict) -> dict:
    return SOURCES[config.get("source") or "node_exporter"]


class PrometheusAdapter:
    def __init__(self, allow_private: bool = False, client: httpx.Client | None = None,
                 resolve: Callable[..., list] = socket.getaddrinfo):
        self._allow_private = allow_private
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=False)
        self._resolve = resolve

    @staticmethod
    def _cfg(account: AccountRef) -> dict:
        src = source_of(account.config)
        return {**src["labels"], **{k: v for k, v in account.config.items() if v}}

    @staticmethod
    def _selector(cfg: dict) -> str:
        job = str(cfg["job"]).replace("\\", "\\\\").replace('"', '\\"')
        return f'job="{job}"'

    def _query(self, account: AccountRef, path: str, params: dict) -> list[dict]:
        base = account.external_ref.rstrip("/")
        check_url(base, self._allow_private, self._resolve)
        creds = account.credentials or {}
        headers, auth = {}, None
        if creds.get("token"):
            headers["Authorization"] = f"Bearer {creds['token']}"
        elif creds.get("username"):
            auth = httpx.BasicAuth(creds["username"], creds.get("password", ""))
        with self._client.stream("GET", f"{base}{path}", params=params, headers=headers,
                                 auth=auth) as resp:
            resp.raise_for_status()
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    raise PrometheusError("The Prometheus response is too large.")
        data = json.loads(body)
        if data.get("status") != "success":
            raise PrometheusError(f"Prometheus query failed: {data.get('error', 'unknown error')}")
        return data["data"]["result"]

    def _instant(self, account: AccountRef, template: str, cfg: dict) -> list[dict]:
        query = template.format(sel=self._selector(cfg), id=cfg["id_label"])
        return self._query(account, "/api/v1/query", {"query": query})

    def list_resources(self, account: AccountRef) -> list[ResourceDTO]:
        src, cfg = source_of(account.config), self._cfg(account)
        id_label = cfg["id_label"]
        inventory = self._instant(account, src["inventory"], cfg)
        if not inventory:
            # an empty answer is a wrong job or a Prometheus outage, not "every VM was deleted"
            raise PrometheusError(f"Prometheus has no VMs for {self._selector(cfg)}; check the "
                                  "job name and how the VMs report.")
        healthy = {s["metric"].get(id_label) for s in self._instant(account, src["health"], cfg)
                   if s["value"][1] == "1"}
        names = {}
        for s in self._instant(account, src["names"], cfg) if src["names"] else inventory:
            if s["metric"].get(id_label) and s["metric"].get(cfg["name_label"]):
                names.setdefault(s["metric"][id_label], s["metric"][cfg["name_label"]])
        own = {id_label, cfg["region_label"], cfg["size_label"], cfg["name_label"]}
        out: dict[str, ResourceDTO] = {}
        for s in inventory:
            labels = s["metric"]
            ext = labels.get(id_label)
            if not ext or ext in out:
                continue
            out[ext] = ResourceDTO(
                external_id=ext,
                name=names.get(ext) or ext,
                region=labels.get(cfg["region_label"]),
                size_sku=labels.get(cfg["size_label"]),
                power_state=power_state(labels, cfg["cloud_label"]),
                health_state="healthy" if ext in healthy else "unavailable",
                tags={k: v for k, v in labels.items() if k not in NOT_TAGS and k not in own},
                # `provider` tells the browser this VM is read-only (no power actions)
                attributes={"provider": "prometheus", "job": cfg["job"],
                            "source": account.config.get("source") or "node_exporter"},
            )
        return list(out.values())

    def fetch_metrics(self, account: AccountRef, resources: list[ResourceDTO], since: datetime,
                      until: datetime) -> list[MetricSampleDTO]:
        if not resources:
            return []
        src, cfg = source_of(account.config), self._cfg(account)
        sel, id_label = self._selector(cfg), cfg["id_label"]
        until = until - src["lag"]
        if until <= since:
            return []
        wanted = {r.external_id for r in resources}
        queries = {**src["queries"], **(cfg.get("queries") or {})}
        out = []
        for metric in src["queries"]:
            series = self._query(account, "/api/v1/query_range", {
                "query": queries[metric].format(sel=sel, id=id_label),
                "start": since.timestamp(), "end": until.timestamp(), "step": STEP_SECONDS})
            for s in series:
                ext = s["metric"].get(id_label)
                if ext not in wanted:
                    continue
                for ts, value in s["values"]:
                    v = float(value)
                    if v == v:  # skip NaN (e.g. a division by zero in the query)
                        out.append(MetricSampleDTO(ext, metric,
                                                   datetime.fromtimestamp(float(ts), UTC), v))
        return out

    def perform_action(self, account: AccountRef, external_id: str, action: str) -> str:
        raise NotImplementedError("Prometheus is a read-only source; VM actions need a cloud API")
