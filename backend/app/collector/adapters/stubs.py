class _NotImplementedAdapter:
    provider = ""

    def _fail(self):
        raise NotImplementedError(f"The {self.provider} adapter is not implemented yet")

    def list_resources(self, account):
        self._fail()

    def fetch_metrics(self, account, resources, since, until):
        self._fail()


class AzureAdapter(_NotImplementedAdapter):
    provider = "Azure (planned for phase 8)"


class AwsAdapter(_NotImplementedAdapter):
    provider = "AWS"


class GcpAdapter(_NotImplementedAdapter):
    provider = "GCP"
