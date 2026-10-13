from app.collector.adapters.base import ActionRejected, ProviderAdapter
from app.collector.adapters.mock import MockAdapter
from app.collector.adapters.stubs import AwsAdapter, AzureAdapter, GcpAdapter
from app.core.config import Settings


def get_adapter(provider_code: str, settings: Settings) -> ProviderAdapter:
    if provider_code == "mock":
        return MockAdapter(settings.generator_url, settings.generator_api_key)
    if provider_code == "azure":
        return AzureAdapter()
    if provider_code == "aws":
        return AwsAdapter()
    if provider_code == "gcp":
        return GcpAdapter()
    raise ValueError(f"unknown provider {provider_code!r}")


__all__ = ["ActionRejected", "MockAdapter", "ProviderAdapter", "get_adapter"]
