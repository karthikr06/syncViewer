"""Read-only adapter for any Prometheus-compatible query API (Prometheus, Grafana Cloud, Thanos...).

One account = one Prometheus server and job. Every distinct value of the id label (default
`instance`) is a VM; node_exporter series provide the metrics. Prometheus can discover VMs in
Azure, AWS and GCP itself (azure_sd_configs, ec2_sd_configs, gce_sd_configs), so this one adapter
monitors all three clouds. It cannot start or stop VMs.

Account fields: `external_ref` is the base URL; `config` may set `job`, `id_label`, `name_label`,
`region_label`, `size_label` and `queries` (per-metric PromQL overrides); `credentials` may hold
`token` (bearer) or `username` + `password` (basic auth, e.g. Grafana Cloud).
"""
import ipaddress
import json
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.collector.dto import AccountRef, MetricSampleDTO, ResourceDTO

STEP_SECONDS = 300
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
DEFAULTS = {"job": "node", "id_label": "instance", "name_label": "nodename",
            "region_label": "region", "size_label": "instance_type"}
# `{sel}` is the series selector (job matcher), `{id}` the id label. Network is bytes per second.
QUERIES = {
    "availability": "max by ({id}) (up{{{sel}}})",
    "cpu_percent": "100 * (1 - avg by ({id}) "
                   '(rate(node_cpu_seconds_total{{{sel},mode="idle"}}[5m])))',
    "memory_percent": "100 * (1 - max by ({id}) (node_memory_MemAvailable_bytes{{{sel}}})"
                      " / max by ({id}) (node_memory_MemTotal_bytes{{{sel}}}))",
    "disk_used_percent": "100 * (1 - max by ({id}) "
                         '(node_filesystem_avail_bytes{{{sel},mountpoint="/"}})'
                         " / max by ({id}) "
                         '(node_filesystem_size_bytes{{{sel},mountpoint="/"}}))',
    "network_in_bytes": "sum by ({id}) "
                        '(rate(node_network_receive_bytes_total{{{sel},device!="lo"}}[5m]))',
    "network_out_bytes": "sum by ({id}) "
                         '(rate(node_network_transmit_bytes_total{{{sel},device!="lo"}}[5m]))',
}
# Labels that describe the scrape, not the VM, so they are not copied into tags.
NOT_TAGS = {"__name__", "job", "power_state"}
POWER = {"running": "running", "stopping": "stopped", "stopped": "stopped",
         "deallocating": "deallocated", "deallocated": "deallocated",
         "terminated": "deallocated", "suspended": "deallocated"}


class UnsafeUrl(ValueError):
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


def power_state(labels: dict[str, str]) -> str:
    """From a `power_state` target label (relabelled from cloud discovery), else assume running.

    AWS and GCP don't bill compute for stopped instances, which is what "deallocated" means here.
    """
    raw = labels.get("power_state", "").lower().removeprefix("powerstate/")
    if not raw:
        return "running"  # a scraped target that does not answer is running but unresponsive
    state = POWER.get(raw, "unknown")
    if state == "stopped" and labels.get("cloud", "").lower() in ("aws", "gcp"):
        return "deallocated"
    return state


class PrometheusAdapter:
    def __init__(self, allow_private: bool = False, client: httpx.Client | None = None,
                 resolve: Callable[..., list] = socket.getaddrinfo):
        self._allow_private = allow_private
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=False)
        self._resolve = resolve

    @staticmethod
    def _cfg(account: AccountRef) -> dict:
        return {**DEFAULTS, **{k: v for k, v in account.config.items() if v}}

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
                    raise ValueError("Prometheus response too large")
        data = json.loads(body)
        if data.get("status") != "success":
            raise ValueError(f"Prometheus query failed: {data.get('error', 'unknown error')}")
        return data["data"]["result"]

    def list_resources(self, account: AccountRef) -> list[ResourceDTO]:
        cfg = self._cfg(account)
        sel, id_label = self._selector(cfg), cfg["id_label"]
        targets = self._query(account, "/api/v1/query", {"query": f"up{{{sel}}}"})
        if not targets:
            # an empty answer is a wrong job or a Prometheus outage, not "every VM was deleted"
            raise ValueError(f"Prometheus has no targets for {sel}")
        names = {}
        for s in self._query(account, "/api/v1/query",
                             {"query": f"last_over_time(node_uname_info{{{sel}}}[1d])"}):
            if id_label in s["metric"]:
                names[s["metric"][id_label]] = s["metric"].get(cfg["name_label"])
        out: dict[str, ResourceDTO] = {}
        for s in targets:
            labels = s["metric"]
            ext = labels.get(id_label)
            if not ext or ext in out:
                continue
            up = s["value"][1] == "1"
            state = power_state(labels)
            out[ext] = ResourceDTO(
                external_id=ext,
                name=names.get(ext) or ext,
                region=labels.get(cfg["region_label"]),
                size_sku=labels.get(cfg["size_label"]),
                power_state=state,
                health_state="healthy" if up else "unavailable",
                tags={k: v for k, v in labels.items()
                      if k not in NOT_TAGS and k not in (id_label, cfg["region_label"],
                                                         cfg["size_label"])},
                attributes={"source": "prometheus", "job": cfg["job"]},
            )
        return list(out.values())

    def fetch_metrics(self, account: AccountRef, resources: list[ResourceDTO], since: datetime,
                      until: datetime) -> list[MetricSampleDTO]:
        if not resources:
            return []
        cfg = self._cfg(account)
        sel, id_label = self._selector(cfg), cfg["id_label"]
        wanted = {r.external_id for r in resources}
        queries = {**QUERIES, **(cfg.get("queries") or {})}
        out = []
        for metric, template in queries.items():
            if metric not in QUERIES:
                continue
            series = self._query(account, "/api/v1/query_range", {
                "query": template.format(sel=sel, id=id_label),
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
