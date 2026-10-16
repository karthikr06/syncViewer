"""Budget kill switch: unlinks billing from the project once the month's spend reaches the budget."""
import base64
import json
import os

import functions_framework
import google.auth
from google.auth.transport.requests import AuthorizedSession

PROJECT = os.environ["GCP_PROJECT_ID"]
BILLING_INFO = f"https://cloudbilling.googleapis.com/v1/projects/{PROJECT}/billingInfo"


@functions_framework.cloud_event
def stop_billing(event) -> None:
    budget = json.loads(base64.b64decode(event.data["message"]["data"]))
    if budget["costAmount"] < budget["budgetAmount"]:
        return
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(creds)
    if not session.get(BILLING_INFO).json().get("billingEnabled"):
        return
    session.put(BILLING_INFO, json={"billingAccountName": ""}).raise_for_status()
    print(f"Billing disabled for {PROJECT}: spent {budget['costAmount']} "
          f"of {budget['budgetAmount']} {budget.get('currencyCode', '')}")
