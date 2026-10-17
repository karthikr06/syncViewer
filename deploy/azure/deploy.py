"""Deploy SyncViewer to Azure (Container Apps + Static Web Apps). Run from the repo root:

    backend\\.venv\\Scripts\\python deploy\\azure\\deploy.py            # build and deploy everything
    backend\\.venv\\Scripts\\python deploy\\azure\\deploy.py --dry-run  # print the commands only
    add --skip-web to leave the website alone, --skip-images to reuse the last pushed images

Needs the Azure CLI (az login), Docker Desktop running, and Node.js. Settings come from the
repo-root .env; secrets reach Azure through temporary files outside the repo.
"""
import argparse
import hashlib
import json
import os
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
ENV_NAME = "syncviewer-env"
API, GEN, JOB, WEB = "syncviewer-api", "syncviewer-gen", "syncviewer-collector", "syncviewer-web"
# Cost guards: scale to zero, one replica at most, small CPU and memory
SCALE = {"minReplicas": 0, "maxReplicas": 1}
DRY_RUN = False
TOOLS: dict[str, str] = {}


def fail(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def run(*cmd: str, capture: bool = False, check: bool = True, stdin: str | None = None,
        cwd: Path = ROOT, env: dict | None = None, quiet: bool = False) -> str:
    """Run a command (printed first); returns stdout when `capture`."""
    if not quiet:
        print("  $ " + " ".join(cmd))
    if DRY_RUN:
        return ""
    exe = TOOLS.get(cmd[0]) or shutil.which(cmd[0])
    if not exe:
        fail(f"{cmd[0]} not found on PATH")
    result = subprocess.run([exe, *cmd[1:]], cwd=cwd, check=False, text=True, input=stdin,
                            capture_output=capture, env=env)
    if check and result.returncode != 0:
        fail(f"{cmd[0]} {cmd[1]} failed" + (f":\n{result.stderr}" if capture else ""))
    return (result.stdout or "").strip() if capture else ""


def exists(*cmd: str) -> bool:
    if DRY_RUN:
        return False
    exe = TOOLS.get(cmd[0]) or shutil.which(cmd[0])
    return subprocess.run([exe, *cmd[1:]], check=False, capture_output=True).returncode == 0


def load_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        fail(".env not found in the repo root")
    env = {k: (v or "") for k, v in dotenv_values(path).items()}
    required = ["DATABASE_URL", "SUPABASE_URL", "SUPABASE_JWKS_URL", "VITE_SUPABASE_ANON_KEY",
                "CREDENTIAL_ENCRYPTION_KEY"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        fail("set these in .env first: " + ", ".join(missing))
    if env.get("GENERATOR_API_KEY") in (None, "", "change-me"):
        fail("set GENERATOR_API_KEY in .env to a long random value")
    if ":6543/" not in env["DATABASE_URL"]:
        print("WARNING: DATABASE_URL is not the Supabase transaction pooler (port 6543)")
    env["AZURE_RESOURCE_GROUP"] = env.get("AZURE_RESOURCE_GROUP") or "syncviewer-rg"
    env["AZURE_LOCATION"] = env.get("AZURE_LOCATION") or "centralindia"
    env["AZURE_WEB_LOCATION"] = env.get("AZURE_WEB_LOCATION") or "eastasia"
    env["COLLECT_SCHEDULE"] = env.get("COLLECT_SCHEDULE") or "0 * * * *"
    return env


def az(*args: str, capture: bool = False, check: bool = True) -> str:
    return run("az", *args, "--only-show-errors", capture=capture, check=check)


def write_spec(folder: Path, name: str, spec: dict) -> str:
    """Container Apps accept JSON for --yaml (JSON is valid YAML)."""
    path = folder / f"{name}.yaml"
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return str(path)


def secrets_and_env(plain: dict[str, str], secret: dict[str, str]):
    secrets = [{"name": k.lower().replace("_", "-"), "value": v} for k, v in secret.items() if v]
    env = [{"name": k, "value": v} for k, v in plain.items() if v]
    env += [{"name": k, "secretRef": k.lower().replace("_", "-")} for k, v in secret.items() if v]
    return secrets, env


def preflight(env: dict[str, str]) -> tuple[str, str]:
    """Login, extension, resource providers and resource group. Returns (subscription, acr)."""
    for tool in ("az", "docker", "npx"):
        found = shutil.which(tool)
        if not found and not DRY_RUN:
            fail({"az": "Azure CLI not found: winget install Microsoft.AzureCLI, then az login",
                  "docker": "Docker not found: install and start Docker Desktop",
                  "npx": "Node.js not found"}[tool])
        TOOLS[tool] = found or tool
    if env.get("AZURE_SUBSCRIPTION_ID"):
        az("account", "set", "--subscription", env["AZURE_SUBSCRIPTION_ID"])
    sub = az("account", "show", "--query", "id", "-o", "tsv", capture=True)
    if not sub and not DRY_RUN:
        fail("not logged in: run az login")
    sub = sub or "SUBSCRIPTION"
    if not DRY_RUN:
        run("docker", "info", capture=True, quiet=True)  # fails early if Docker is not running
    az("extension", "add", "--name", "containerapp", "--upgrade")
    for ns in ("Microsoft.App", "Microsoft.ContainerRegistry", "Microsoft.Web",
               "Microsoft.OperationalInsights"):
        az("provider", "register", "--namespace", ns, "--wait")
    az("group", "create", "--name", env["AZURE_RESOURCE_GROUP"],
       "--location", env["AZURE_LOCATION"], "-o", "none")
    # registry names are global; derive a stable one from the subscription
    acr = env.get("AZURE_REGISTRY") or "syncviewer" + hashlib.sha1(sub.encode()).hexdigest()[:8]
    return sub, acr


def push_images(env: dict[str, str], acr: str, tag: str) -> None:
    rg = env["AZURE_RESOURCE_GROUP"]
    if not exists("az", "acr", "show", "--name", acr, "--resource-group", rg):
        az("acr", "create", "--name", acr, "--resource-group", rg, "--sku", "Basic",
           "--admin-enabled", "true", "-o", "none")
    az("acr", "login", "--name", acr)
    for image, folder in (("backend", "backend"), ("generator", "generator")):
        ref = f"{acr}.azurecr.io/{image}:{tag}"
        run("docker", "build", "--platform=linux/amd64", "-t", ref, folder)
        run("docker", "push", ref)


def latest_tag(acr: str) -> str:
    tags = az("acr", "repository", "show-tags", "--name", acr, "--repository", "backend",
              "--orderby", "time_desc", "--top", "1", "-o", "tsv", capture=True)
    if not tags and not DRY_RUN:
        fail("no images in the registry yet; run without --skip-images")
    return tags or "TAG"


def deploy_app(folder: Path, rg: str, name: str, spec: dict) -> str:
    """Create or update a container app; returns its FQDN."""
    action = "update" if exists("az", "containerapp", "show", "-n", name, "-g", rg) else "create"
    az("containerapp", action, "-n", name, "-g", rg, "--yaml", write_spec(folder, name, spec),
       "-o", "none")
    fqdn = az("containerapp", "show", "-n", name, "-g", rg, "--query",
              "properties.configuration.ingress.fqdn", "-o", "tsv", capture=True)
    return fqdn or f"{name}.example.azurecontainerapps.io"


def deploy_web(env: dict[str, str], rg: str, api_url: str) -> str:
    """Build the website with the production settings and upload it to Static Web Apps."""
    token = az("staticwebapp", "secrets", "list", "-n", WEB, "-g", rg, "--query",
               "properties.apiKey", "-o", "tsv", capture=True)
    build_env = {**os.environ, "VITE_API_URL": api_url,
                 "VITE_SUPABASE_URL": env.get("VITE_SUPABASE_URL") or env["SUPABASE_URL"],
                 "VITE_SUPABASE_ANON_KEY": env["VITE_SUPABASE_ANON_KEY"],
                 "VITE_ENABLE_GOOGLE_AUTH": env.get("VITE_ENABLE_GOOGLE_AUTH") or "false"}
    frontend = ROOT / "frontend"
    if not (frontend / "node_modules").exists():
        run("npm", "ci", cwd=frontend)
    run("npm", "run", "build", cwd=frontend, env=build_env)
    deploy_env = {**os.environ, "SWA_CLI_DEPLOYMENT_TOKEN": token}
    run("npx", "--yes", "@azure/static-web-apps-cli@2", "deploy", "dist", "--env", "production",
        cwd=frontend, env=deploy_env)
    # let pushes to main redeploy the site (.github/workflows/web.yml)
    if shutil.which("gh") and not DRY_RUN:
        run("gh", "secret", "set", "AZURE_STATIC_WEB_APPS_API_TOKEN", stdin=token, check=False)
        for key in ("VITE_API_URL", "VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY",
                    "VITE_ENABLE_GOOGLE_AUTH"):
            run("gh", "variable", "set", key, "--body", build_env[key], check=False)
    return token


def deploy(env: dict[str, str], skip_images: bool, skip_web: bool) -> None:
    rg, location = env["AZURE_RESOURCE_GROUP"], env["AZURE_LOCATION"]
    print("\n[1/6] Checking Azure")
    sub, acr = preflight(env)

    print("\n[2/6] Images")
    if skip_images:
        tag = latest_tag(acr)
    else:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=False,
                             capture_output=True, text=True).stdout.strip() or "local"
        tag = datetime.now(UTC).strftime("%Y%m%d-%H%M") + "-" + sha
        push_images(env, acr, tag)
    registry_password = az("acr", "credential", "show", "-n", acr, "--query",
                           "passwords[0].value", "-o", "tsv", capture=True)
    registry = [{"server": f"{acr}.azurecr.io", "username": acr,
                 "passwordSecretRef": "registry-password"}]

    print("\n[3/6] Container Apps environment and website")
    if not exists("az", "containerapp", "env", "show", "-n", ENV_NAME, "-g", rg):
        # logs off: Log Analytics charges per GB; `az containerapp logs show` still streams logs
        az("containerapp", "env", "create", "-n", ENV_NAME, "-g", rg, "--location", location,
           "--logs-destination", "none", "-o", "none")
    env_id = (f"/subscriptions/{sub}/resourceGroups/{rg}"
              f"/providers/Microsoft.App/managedEnvironments/{ENV_NAME}")
    if not exists("az", "staticwebapp", "show", "-n", WEB, "-g", rg):
        az("staticwebapp", "create", "-n", WEB, "-g", rg, "--location",
           env["AZURE_WEB_LOCATION"], "--sku", "Free", "-o", "none")
    web_host = az("staticwebapp", "show", "-n", WEB, "-g", rg, "--query", "defaultHostname",
                  "-o", "tsv", capture=True) or "WEB.azurestaticapps.net"
    web_url = f"https://{web_host}"

    def spec(container: dict, ingress: dict | None, plain: dict, secret: dict) -> dict:
        secrets, env_vars = secrets_and_env(plain, secret)
        config = {"activeRevisionsMode": "Single", "registries": registry,
                  "secrets": [{"name": "registry-password", "value": registry_password},
                              *secrets]}
        if ingress:
            config["ingress"] = ingress
        return {"location": location, "properties": {
            "managedEnvironmentId": env_id, "configuration": config,
            "template": {"containers": [{**container, "env": env_vars}], "scale": SCALE}}}

    shared_plain = {"APP_ENV": "production",
                    "RAW_RETENTION_DAYS": env.get("RAW_RETENTION_DAYS") or "14"}
    shared_secret = {"DATABASE_URL": env["DATABASE_URL"],
                     "CREDENTIAL_ENCRYPTION_KEY": env["CREDENTIAL_ENCRYPTION_KEY"],
                     "GENERATOR_API_KEY": env["GENERATOR_API_KEY"]}

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        print("\n[4/6] Demo cloud (internal only) and API")
        gen_fqdn = deploy_app(folder, rg, GEN, spec(
            {"name": "generator", "image": f"{acr}.azurecr.io/generator:{tag}",
             "resources": {"cpu": 0.25, "memory": "0.5Gi"}},
            {"external": False, "targetPort": 8100, "transport": "auto"},
            {}, {"GENERATOR_API_KEY": env["GENERATOR_API_KEY"]}))
        gen_url = f"https://{gen_fqdn}"
        api_fqdn = deploy_app(folder, rg, API, spec(
            {"name": "api", "image": f"{acr}.azurecr.io/backend:{tag}",
             "resources": {"cpu": 0.5, "memory": "1Gi"}},
            {"external": True, "targetPort": 8000, "transport": "auto"},
            {**shared_plain, "GENERATOR_URL": gen_url, "SUPABASE_URL": env["SUPABASE_URL"],
             "SUPABASE_JWKS_URL": env["SUPABASE_JWKS_URL"], "CORS_ORIGINS": web_url,
             "ADMIN_EMAILS": env.get("ADMIN_EMAILS", ""),
             "GEMINI_MODEL": env.get("GEMINI_MODEL", "")},
            {**shared_secret, "GOOGLE_API_KEY": env.get("GOOGLE_API_KEY", ""),
             "SUPABASE_JWT_SECRET": env.get("SUPABASE_JWT_SECRET", "")}))
        api_url = f"https://{api_fqdn}"

        print("\n[5/6] Collector job")
        secrets, env_vars = secrets_and_env({**shared_plain, "GENERATOR_URL": gen_url},
                                            shared_secret)
        job = {"location": location, "properties": {
            "environmentId": env_id,
            "configuration": {
                "triggerType": "Schedule", "replicaTimeout": 900, "replicaRetryLimit": 0,
                "scheduleTriggerConfig": {"cronExpression": env["COLLECT_SCHEDULE"],
                                          "parallelism": 1, "replicaCompletionCount": 1},
                "registries": registry,
                "secrets": [{"name": "registry-password", "value": registry_password},
                            *secrets]},
            "template": {"containers": [{
                "name": "collector", "image": f"{acr}.azurecr.io/backend:{tag}",
                "command": ["python", "-m", "app.collector.run"],
                "resources": {"cpu": 0.5, "memory": "1Gi"}, "env": env_vars}]}}}
        action = "update" if exists("az", "containerapp", "job", "show", "-n", JOB,
                                    "-g", rg) else "create"
        az("containerapp", "job", action, "-n", JOB, "-g", rg,
           "--yaml", write_spec(folder, JOB, job), "-o", "none")

    print("\n[6/6] Website")
    if not skip_web:
        deploy_web(env, rg, api_url)
    if not DRY_RUN:
        for _ in range(6):  # first start after a deploy can take a little while
            try:
                with urllib.request.urlopen(f"{api_url}/health", timeout=30) as r:
                    print(f"  API health: {r.status}")
                    break
            except OSError:
                time.sleep(10)
        else:
            print("  API not responding yet: az containerapp logs show -n syncviewer-api "
                  f"-g {rg} --follow")
    print(f"""
Done.
  Website: {web_url}
  API:     {api_url}

Once, in Supabase > Authentication > URL Configuration:
  Site URL:       {web_url}
  Redirect URLs:  {web_url}/**
The collector runs on "{env['COLLECT_SCHEDULE']}" (UTC). "Collect now" on the Accounts page
fetches fresh data at any time.""")


def main() -> None:
    global DRY_RUN
    parser = argparse.ArgumentParser(description="Deploy SyncViewer to Azure.")
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    parser.add_argument("--skip-images", action="store_true", help="reuse the last pushed images")
    parser.add_argument("--skip-web", action="store_true", help="do not rebuild the website")
    args = parser.parse_args()
    DRY_RUN = args.dry_run
    deploy(load_env(), args.skip_images, args.skip_web)


if __name__ == "__main__":
    main()
