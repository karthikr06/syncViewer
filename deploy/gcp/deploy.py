"""Deploy SyncViewer to Google Cloud with free-tier settings. Run from the repo root:

    backend\\.venv\\Scripts\\python deploy\\gcp\\deploy.py budget     # budget alerts + kill switch (once)
    backend\\.venv\\Scripts\\python deploy\\gcp\\deploy.py deploy     # build and deploy everything
    add --dry-run to print the gcloud commands without running them

Settings come from the repo-root .env; secrets are passed to Cloud Run through a temporary file
outside the repo and never appear on the command line.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

# Cost guards: one instance at most per service, scale to zero when idle, CPU only during requests
SERVICE_FLAGS = ["--min-instances=0", "--max-instances=1", "--cpu=1", "--concurrency=80",
                 "--cpu-throttling", "--allow-unauthenticated"]
APIS = ["run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
        "cloudscheduler.googleapis.com", "iam.googleapis.com"]
GUARD_APIS = ["pubsub.googleapis.com", "cloudfunctions.googleapis.com", "eventarc.googleapis.com",
              "cloudbilling.googleapis.com", "billingbudgets.googleapis.com"]
# Artifact Registry: keep the two newest builds of each image, delete the rest after a day
CLEANUP_POLICY = [
    {"name": "keep-two-newest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 2}},
    {"name": "delete-older", "action": {"type": "Delete"},
     "condition": {"tagState": "any", "olderThan": "1d"}},
]

DRY_RUN = False
GCLOUD = "gcloud"


def fail(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def gcloud(*args: str, capture: bool = False, check: bool = True, retries: int = 1) -> str:
    """Run a gcloud command (printed first); `retries` covers IAM changes that take a moment."""
    cmd = [GCLOUD, *args, "--quiet"]
    print("  $ gcloud " + " ".join(args))
    if DRY_RUN:
        return ""
    for attempt in range(retries):
        result = subprocess.run(cmd, check=False, capture_output=capture, text=True)
        if result.returncode == 0:
            return (result.stdout or "").strip()
        if attempt < retries - 1:
            time.sleep(10)
    if check:
        fail(f"gcloud {args[0]} {args[1] if len(args) > 1 else ''} failed"
             + (f":\n{result.stderr}" if capture else ""))
    return ""


def exists(*describe: str) -> bool:
    if DRY_RUN:
        return False
    result = subprocess.run([GCLOUD, *describe, "--quiet"], check=False, capture_output=True)
    return result.returncode == 0


def load_env(required: list[str]) -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        fail(".env not found in the repo root")
    env = {k: (v or "") for k, v in dotenv_values(path).items()}
    missing = [k for k in required if not env.get(k)]
    if missing:
        fail("set these in .env first: " + ", ".join(missing))
    env.setdefault("GCP_REGION", "asia-south1")
    env["GCP_REGION"] = env["GCP_REGION"] or "asia-south1"
    return env


def preflight(env: dict[str, str], apis: list[str]) -> str:
    """Check gcloud, login and billing; enable APIs. Returns the project number."""
    global GCLOUD
    found = shutil.which("gcloud")
    if not found and not DRY_RUN:
        fail("Google Cloud CLI not found. Install it (winget install Google.CloudSDK), "
             "open a new terminal, then run: gcloud auth login")
    GCLOUD = found or "gcloud"
    project = env["GCP_PROJECT_ID"]
    if not DRY_RUN:
        if not gcloud("auth", "list", "--filter=status:ACTIVE", "--format=value(account)",
                      capture=True):
            fail("not logged in: run gcloud auth login")
        billing = gcloud("billing", "projects", "describe", project,
                         "--format=value(billingEnabled)", capture=True)
        if billing.lower() != "true":
            fail(f"billing is not enabled on {project}; link a billing account in the console")
    gcloud("config", "set", "project", project)
    gcloud("services", "enable", *apis)
    number = gcloud("projects", "describe", project, "--format=value(projectNumber)",
                    capture=True)
    return number or "PROJECT_NUMBER"


def ensure_service_account(project: str, name: str, title: str) -> str:
    email = f"{name}@{project}.iam.gserviceaccount.com"
    if not exists("iam", "service-accounts", "describe", email):
        gcloud("iam", "service-accounts", "create", name, f"--display-name={title}")
    return email


def write_env_file(folder: Path, name: str, values: dict[str, str]) -> str:
    path = folder / f"{name}.yaml"
    path.write_text(json.dumps({k: v for k, v in values.items() if v}), encoding="utf-8")
    return str(path)


def check_health(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=60) as resp:
            return resp.status == 200
    except OSError:
        return False


def deploy(env: dict[str, str]) -> None:
    project, region = env["GCP_PROJECT_ID"], env["GCP_REGION"]
    if env.get("GENERATOR_API_KEY") in (None, "", "change-me"):
        fail("set GENERATOR_API_KEY in .env to a random value; the demo cloud is public otherwise")
    if ":6543/" not in env["DATABASE_URL"]:
        print("WARNING: DATABASE_URL is not the transaction pooler (port 6543)")

    print("\n[1/6] Checking the project")
    number = preflight(env, APIS)
    registry = f"{region}-docker.pkg.dev/{project}/syncviewer"
    url = {s: f"https://syncviewer-{s}-{number}.{region}.run.app" for s in ("api", "gen", "web")}

    print("\n[2/6] Image registry with automatic cleanup")
    if not exists("artifacts", "repositories", "describe", "syncviewer", f"--location={region}"):
        gcloud("artifacts", "repositories", "create", "syncviewer", "--repository-format=docker",
               f"--location={region}")
    runtime_sa = ensure_service_account(project, "syncviewer-run", "SyncViewer services")
    scheduler_sa = ensure_service_account(project, "syncviewer-scheduler",
                                          "SyncViewer collector trigger")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        policy = folder / "cleanup.json"
        policy.write_text(json.dumps(CLEANUP_POLICY), encoding="utf-8")
        gcloud("artifacts", "repositories", "set-cleanup-policies", "syncviewer",
               f"--location={region}", f"--policy={policy}", "--no-dry-run")

        print("\n[3/6] Building images with Cloud Build (takes a few minutes)")
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=False, capture_output=True,
                             text=True, cwd=ROOT).stdout.strip() or "local"
        tag = datetime.now(UTC).strftime("%Y%m%d-%H%M") + "-" + sha
        subs = {"_REGION": region, "_TAG": tag, "_VITE_API_URL": url["api"],
                "_VITE_SUPABASE_URL": env.get("VITE_SUPABASE_URL") or env["SUPABASE_URL"],
                "_VITE_SUPABASE_ANON_KEY": env["VITE_SUPABASE_ANON_KEY"],
                "_VITE_ENABLE_GOOGLE_AUTH": env.get("VITE_ENABLE_GOOGLE_AUTH") or "false"}
        gcloud("builds", "submit", str(ROOT), f"--config={HERE / 'cloudbuild.yaml'}",
               "--substitutions=" + ",".join(f"{k}={v}" for k, v in subs.items()))

        shared = {"DATABASE_URL": env["DATABASE_URL"],
                  "CREDENTIAL_ENCRYPTION_KEY": env["CREDENTIAL_ENCRYPTION_KEY"],
                  "GENERATOR_URL": url["gen"], "GENERATOR_API_KEY": env["GENERATOR_API_KEY"],
                  "RAW_RETENTION_DAYS": env.get("RAW_RETENTION_DAYS") or "14",
                  "APP_ENV": "production"}
        api_env = {**shared, "SUPABASE_URL": env["SUPABASE_URL"],
                   "SUPABASE_JWKS_URL": env["SUPABASE_JWKS_URL"],
                   "SUPABASE_JWT_SECRET": env.get("SUPABASE_JWT_SECRET", ""),
                   "CORS_ORIGINS": url["web"], "ADMIN_EMAILS": env.get("ADMIN_EMAILS", ""),
                   "GOOGLE_API_KEY": env.get("GOOGLE_API_KEY", ""),
                   "GEMINI_MODEL": env.get("GEMINI_MODEL", "")}
        supabase = (env.get("VITE_SUPABASE_URL") or env["SUPABASE_URL"]).rstrip("/")
        web_env = {"CSP_CONNECT_SRC": f"'self' {supabase} {url['api']}"}

        print("\n[4/6] Deploying the services")
        common = [f"--region={region}", f"--service-account={runtime_sa}", *SERVICE_FLAGS]
        gen_env = {"GENERATOR_API_KEY": env["GENERATOR_API_KEY"]}
        gcloud("run", "deploy", "syncviewer-gen", f"--image={registry}/generator:{tag}",
               "--port=8100", "--memory=512Mi", "--timeout=60", *common,
               f"--env-vars-file={write_env_file(folder, 'gen', gen_env)}")
        gcloud("run", "deploy", "syncviewer-api", f"--image={registry}/backend:{tag}",
               "--port=8000", "--memory=1Gi", "--timeout=300", *common,
               f"--env-vars-file={write_env_file(folder, 'api', api_env)}")
        gcloud("run", "deploy", "syncviewer-web", f"--image={registry}/frontend:{tag}",
               "--port=80", "--memory=256Mi", "--timeout=30", *common,
               f"--env-vars-file={write_env_file(folder, 'web', web_env)}")

        print("\n[5/6] Collector job and schedule")
        gcloud("run", "jobs", "deploy", "syncviewer-collector", f"--image={registry}/backend:{tag}",
               f"--region={region}", f"--service-account={runtime_sa}", "--command=python",
               "--args=-m,app.collector.run", "--cpu=1", "--memory=512Mi", "--tasks=1",
               "--max-retries=0", "--task-timeout=900s",
               f"--env-vars-file={write_env_file(folder, 'collector', shared)}")

    gcloud("run", "jobs", "add-iam-policy-binding", "syncviewer-collector", f"--region={region}",
           f"--member=serviceAccount:{scheduler_sa}", "--role=roles/run.invoker", retries=3)
    schedule = env.get("COLLECT_SCHEDULE") or "*/30 * * * *"
    target = (f"https://run.googleapis.com/v2/projects/{project}/locations/{region}"
              f"/jobs/syncviewer-collector:run")
    action = "update" if exists("scheduler", "jobs", "describe", "syncviewer-collect",
                                f"--location={region}") else "create"
    gcloud("scheduler", "jobs", action, "http", "syncviewer-collect", f"--location={region}",
           f"--schedule={schedule}", "--time-zone=Asia/Kolkata", f"--uri={target}",
           "--http-method=POST", f"--oauth-service-account-email={scheduler_sa}")

    print("\n[6/6] Checking the deployment")
    if not DRY_RUN:
        for name in ("gen", "api"):
            ok = check_health(url[name])
            print(f"  {name}: {'ok' if ok else 'NOT RESPONDING (see Cloud Run logs)'}")
    print(f"""
Done. Open {url['web']}

Still to do once, in Supabase > Authentication > URL Configuration:
  Site URL:       {url['web']}
  Redirect URLs:  {url['web']}/**
The collector runs on "{schedule}"; use "Collect now" on the Accounts page for fresh data.""")


def budget(env: dict[str, str]) -> None:
    """Budget alerts by email plus a kill switch that unlinks billing when the budget is reached."""
    project, region = env["GCP_PROJECT_ID"], env["GCP_REGION"]
    amount = env.get("BUDGET_AMOUNT") or "100INR"
    preflight(env, APIS + GUARD_APIS)
    account = gcloud("billing", "projects", "describe", project,
                     "--format=value(billingAccountName)", capture=True).rsplit("/", 1)[-1]
    topic = f"projects/{project}/topics/billing-alerts"

    print("\n[1/3] Notification topic")
    if not exists("pubsub", "topics", "describe", "billing-alerts"):
        gcloud("pubsub", "topics", "create", "billing-alerts")

    print(f"\n[2/3] Budget of {amount} with email alerts at 50%, 90% and 100%")
    existing = gcloud("billing", "budgets", "list", f"--billing-account={account or 'ACCOUNT'}",
                      "--filter=displayName=syncviewer", "--format=value(name)", capture=True)
    if existing:
        print("  a budget named syncviewer already exists; change it in Billing > Budgets & alerts")
    else:
        gcloud("billing", "budgets", "create", f"--billing-account={account or 'ACCOUNT'}",
               "--display-name=syncviewer", f"--budget-amount={amount}",
               f"--filter-projects=projects/{project}", "--threshold-rule=percent=0.5",
               "--threshold-rule=percent=0.9", "--threshold-rule=percent=1.0",
               f"--notifications-rule-pubsub-topic={topic}")

    print("\n[3/3] Kill switch (unlinks billing from the project when the budget is reached)")
    guard_sa = ensure_service_account(project, "syncviewer-budget-guard", "SyncViewer budget guard")
    # Project Billing Manager can unlink this project's billing and nothing else
    gcloud("projects", "add-iam-policy-binding", project, f"--member=serviceAccount:{guard_sa}",
           "--role=roles/billing.projectManager", "--condition=None", retries=3)
    gcloud("functions", "deploy", "syncviewer-budget-guard", "--gen2", "--runtime=python312",
           f"--region={region}", f"--source={HERE / 'budget_guard'}", "--entry-point=stop_billing",
           "--trigger-topic=billing-alerts", f"--service-account={guard_sa}",
           f"--trigger-service-account={guard_sa}", "--memory=256Mi", "--max-instances=1",
           "--no-allow-unauthenticated", "--ingress-settings=internal-only",
           f"--set-env-vars=GCP_PROJECT_ID={project}")
    gcloud("functions", "add-invoker-policy-binding", "syncviewer-budget-guard",
           f"--region={region}", f"--member=serviceAccount:{guard_sa}", retries=3)
    print(f"""
Done. Budget alerts go to your billing account's email. If spend reaches {amount}, billing is
unlinked and every service stops until you re-link it (Billing > Account management). Your data
lives in Supabase, so nothing is lost; redeploy after re-linking.""")


def main() -> None:
    global DRY_RUN
    parser = argparse.ArgumentParser(description="Deploy SyncViewer to Google Cloud.")
    parser.add_argument("command", choices=["deploy", "budget"])
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    args = parser.parse_args()
    DRY_RUN = args.dry_run
    if args.command == "deploy":
        deploy(load_env(["GCP_PROJECT_ID", "DATABASE_URL", "SUPABASE_URL", "SUPABASE_JWKS_URL",
                         "VITE_SUPABASE_ANON_KEY", "CREDENTIAL_ENCRYPTION_KEY",
                         "GENERATOR_API_KEY"]))
    else:
        budget(load_env(["GCP_PROJECT_ID"]))


if __name__ == "__main__":
    main()
