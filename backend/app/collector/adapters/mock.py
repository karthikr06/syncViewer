from datetime import UTC, datetime

import httpx

from app.collector.adapters.base import ActionRejected
from app.collector.dto import AccountRef, MetricSampleDTO, ResourceDTO

HEALTH_BY_POWER = {"running": "healthy", "stopped": "unavailable", "deallocated": "unavailable"}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def _fmt(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


class MockAdapter:
    """Talks to the generator over HTTP exactly as AzureAdapter will talk to Azure."""

    def __init__(self, base_url: str, api_key: str = "", client: httpx.Client | None = None):
        headers = {"X-API-Key": api_key} if api_key else {}
        self._client = client or httpx.Client(base_url=base_url, headers=headers, timeout=60.0)
        self._headers = headers

    def _get(self, path: str, params: dict) -> dict:
        resp = self._client.get(path, params=params, headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _scenario(account: AccountRef) -> str:
        return str(account.config.get("scenario", "small"))

    def list_resources(self, account: AccountRef) -> list[ResourceDTO]:
        data = self._get(
            f"/v1/accounts/{account.external_ref}/resources",
            {"scenario": self._scenario(account)},
        )
        return [
            ResourceDTO(
                external_id=r["id"],
                name=r["name"],
                type_code=r.get("type", "vm"),
                region=r.get("region"),
                size_sku=r.get("size_sku"),
                power_state=r.get("power_state", "unknown"),
                health_state=HEALTH_BY_POWER.get(r.get("power_state", ""), "unknown"),
                tags=r.get("tags", {}),
                attributes=r.get("attributes", {}),
            )
            for r in data["resources"]
        ]

    def fetch_metrics(
        self, account: AccountRef, resources: list[ResourceDTO], since: datetime, until: datetime
    ) -> list[MetricSampleDTO]:
        if not resources:
            return []
        data = self._get(
            f"/v1/accounts/{account.external_ref}/metrics",
            {
                "scenario": self._scenario(account),
                "resource_ids": ",".join(r.external_id for r in resources),
                "start": _fmt(since),
                "end": _fmt(until),
                "step": 300,
            },
        )
        return [
            MetricSampleDTO(s["resource_id"], s["metric"], _parse(ts), float(v))
            for s in data["series"]
            for ts, v in s["points"]
        ]

    def perform_action(self, account: AccountRef, external_id: str, action: str) -> str:
        resp = self._client.post(
            f"/v1/accounts/{account.external_ref}/resources/{external_id}/actions",
            params={"scenario": self._scenario(account)}, json={"action": action},
            headers=self._headers)
        if resp.status_code in (404, 409):
            raise ActionRejected(resp.json().get("detail", "the provider refused the action"))
        resp.raise_for_status()
        return resp.json()["power_state"]
