"""Deploy SyncViewer to Azure at the lowest cost. Run from the repo root:

    backend\\.venv\\Scripts\\python deploy\\azure\\deploy.py            # build and deploy everything
    backend\\.venv\\Scripts\\python deploy\\azure\\deploy.py --dry-run  # print the commands only
    add --skip-web to leave the website alone, --skip-image to reuse the last pushed image

One container app runs the API with the demo cloud built in (deploy/azure/Dockerfile); it scales
to zero. A free GitHub Actions schedule (.github/workflows/collect.yml) wakes it hourly to collect.
The website is on Static Web Apps (free). Needs the Azure CLI (az login), Docker Desktop and
Node.js; settings come from the repo-root .env, and secrets reach Azure through temporary files.
"""
import argparse
import hashlib
import json
import os
import secrets
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
ENV_NAME, APP, WEB = "syncviewer-env", "syncviewer-api", "syncviewer-web"
OLD = [("containerApps", "syncviewer-gen"), ("jobs", "syncviewer-collector")]  # earlier layout
APPS_API = "2024-03-01"
DRY_RUN = False
TOOLS: dict[str, str] = {}


def fail(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def run(*cmd: str, capture: bool = False, check: bool = True, stdin: str | None = None,
        cwd: Path = ROOT, env: dict | None = None) -> str:
    """Run a command (printed first); returns stdout when `capture`."""
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


def az(*args: str, capture: bool = False, check: bool = True) -> str:
    return run("az", *args, "--only-show-errors", capture=capture, check=check)


def exists(*args: str) -> bool:
    if DRY_RUN:
        return False
    return subprocess.run([TOOLS["az"], *args, "--only-show-errors"], check=False,
                          capture_output=True).returncode == 0


def load_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        fail(".env not found in the repo root")
    env = {k: (v or "") for k, v in dotenv_values(path).items()}
    missing = [k for k in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_JWKS_URL",
                           "VITE_SUPABASE_ANON_KEY", "CREDENTIAL_ENCRYPTION_KEY") if not env.get(k)]
    if missing:
        fail("set these in .env first: " + ", ".join(missing))
    if env.get("GENERATOR_API_KEY") in (None, "", "change-me"):
        fail("set GENERATOR_API_KEY in .env to a long random value")
    if ":6543/" not in env["DATABASE_URL"]:
        print("WARNING: DATABASE_URL is not the Supabase transaction pooler (port 6543)")
    if not env.get("COLLECTOR_TOKEN") and not DRY_RUN:
        env["COLLECTOR_TOKEN"] = secrets.token_urlsafe(32)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n# Secret the hourly collector trigger sends (deploy/azure/deploy.py)\n"
                    f"COLLECTOR_TOKEN={env['COLLECTOR_TOKEN']}\n")
        print("Added a new COLLECTOR_TOKEN to .env")
    env["AZURE_RESOURCE_GROUP"] = env.get("AZURE_RESOURCE_GROUP") or "syncviewer-rg"
    env["AZURE_LOCATION"] = env.get("AZURE_LOCATION") or "centralindia"
    env["AZURE_WEB_LOCATION"] = env.get("AZURE_WEB_LOCATION") or "eastasia"
    return env


def preflight(env: dict[str, str]) -> tuple[str, str]:
    """Tools, login and resource group. Returns (subscription id, registry name)."""
    hints = {"az": "Azure CLI not found: winget install Microsoft.AzureCLI, then az login",
             "docker": "Docker not found: install and start Docker Desktop",
             "npx": "Node.js not found"}
    for tool, hint in hints.items():
        found = shutil.which(tool)
        if not found and not DRY_RUN:
            fail(hint)
        TOOLS[tool] = found or tool
    if env.get("AZURE_SUBSCRIPTION_ID"):
        az("account", "set", "--subscription", env["AZURE_SUBSCRIPTION_ID"])
    sub = az("account", "show", "--query", "id", "-o", "tsv", capture=True)
    if not sub and not DRY_RUN:
        fail("not logged in: run az login")
    sub = sub or "SUBSCRIPTION"
    for ns in ("Microsoft.App", "Microsoft.ContainerRegistry", "Microsoft.Web"):
        az("provider", "register", "--namespace", ns, "--wait")
    az("group", "create", "--name", env["AZURE_RESOURCE_GROUP"],
       "--location", env["AZURE_LOCATION"], "-o", "none")
    acr = env.get("AZURE_REGISTRY") or "syncviewer" + hashlib.sha1(sub.encode()).hexdigest()[:8]
    return sub, acr


def arm_url(sub: str, rg: str, kind: str, name: str) -> str:
    return (f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
            f"/providers/Microsoft.App/{kind}/{name}?api-version={APPS_API}")


def arm_put(folder: Path, url: str, name: str, spec: dict) -> None:
    """PUT our own spec and wait until it is provisioned.

    `az rest` instead of `az containerapp create --yaml`: the extension pads the request with
    null fields that the API rejects.
    """
    body = folder / f"{name}.json"
    body.write_text(json.dumps(spec), encoding="utf-8")
    az("rest", "--method", "put", "--url", url, "--body", f"@{body}",
       "--headers", "Content-Type=application/json", "-o", "none")
    state = ""
    for _ in range(60):
        state = az("rest", "--method", "get", "--url", url, "--query",
                   "properties.provisioningState", "-o", "tsv", capture=True)
        if DRY_RUN or state in ("Succeeded", "Failed", "Canceled"):
            break
        time.sleep(10)
    if state not in ("Succeeded", "") and not DRY_RUN:
        fail(f"{name} ended as {state}; see Container Apps > {name} > Revisions in the portal")


def build_image(acr: str, rg: str, skip: bool) -> str:
    if not exists("acr", "show", "--name", acr, "--resource-group", rg):
        az("acr", "create", "--name", acr, "--resource-group", rg, "--sku", "Basic",
           "--admin-enabled", "true", "-o", "none")
    if skip:
        tag = az("acr", "repository", "show-tags", "--name", acr, "--repository", "syncviewer",
                 "--orderby", "time_desc", "--top", "1", "-o", "tsv", capture=True)
        if not tag and not DRY_RUN:
            fail("no image in the registry yet; run without --skip-image")
        return f"{acr}.azurecr.io/syncviewer:{tag or 'TAG'}"
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=False,
                         capture_output=True, text=True).stdout.strip() or "local"
    ref = f"{acr}.azurecr.io/syncviewer:{datetime.now(UTC):%Y%m%d-%H%M}-{sha}"
    az("acr", "login", "--name", acr)
    run("docker", "build", "--platform=linux/amd64", "-f", "deploy/azure/Dockerfile", "-t",
        ref, ".")
    run("docker", "push", ref)
    return ref


def app_spec(env: dict[str, str], location: str, env_id: str, image: str, acr: str,
             registry_password: str, web_url: str) -> dict:
    plain = {"APP_ENV": "production", "GENERATOR_URL": "http://127.0.0.1:8000/gen",
             "SUPABASE_URL": env["SUPABASE_URL"], "SUPABASE_JWKS_URL": env["SUPABASE_JWKS_URL"],
             "CORS_ORIGINS": web_url, "ADMIN_EMAILS": env.get("ADMIN_EMAILS", ""),
             "GEMINI_MODEL": env.get("GEMINI_MODEL", ""),
             "RAW_RETENTION_DAYS": env.get("RAW_RETENTION_DAYS") or "14"}
    secret = {"DATABASE_URL": env["DATABASE_URL"],
              "CREDENTIAL_ENCRYPTION_KEY": env["CREDENTIAL_ENCRYPTION_KEY"],
              "GENERATOR_API_KEY": env["GENERATOR_API_KEY"],
              "COLLECTOR_TOKEN": env.get("COLLECTOR_TOKEN", ""),
              "GOOGLE_API_KEY": env.get("GOOGLE_API_KEY", ""),
              "SUPABASE_JWT_SECRET": env.get("SUPABASE_JWT_SECRET", "")}

    def ref(key: str) -> str:
        return key.lower().replace("_", "-")

    env_vars = [{"name": k, "value": v} for k, v in plain.items() if v]
    env_vars += [{"name": k, "secretRef": ref(k)} for k, v in secret.items() if v]
    return {"location": location, "properties": {
        "managedEnvironmentId": env_id,
        "configuration": {
            "activeRevisionsMode": "Single",
            "ingress": {"external": True, "targetPort": 8000, "transport": "auto"},
            "registries": [{"server": f"{acr}.azurecr.io", "username": acr,
                            "passwordSecretRef": "registry-password"}],
            "secrets": [{"name": "registry-password", "value": registry_password},
                        *({"name": ref(k), "value": v} for k, v in secret.items() if v)]},
        "template": {
            "containers": [{"name": "api", "image": image, "env": env_vars,
                            "resources": {"cpu": 0.5, "memory": "1Gi"}}],
            # cost guard: nothing runs while idle, never more than one replica
            "scale": {"minReplicas": 0, "maxReplicas": 1}}}}


def deploy_web(env: dict[str, str], rg: str, api_url: str) -> None:
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
    run("npx", "--yes", "@azure/static-web-apps-cli@2", "deploy", "dist", "--env", "production",
        cwd=frontend, env={**os.environ, "SWA_CLI_DEPLOYMENT_TOKEN": token})
    if shutil.which("gh") and not DRY_RUN:  # pushes to main republish the site (web.yml)
        run("gh", "secret", "set", "AZURE_STATIC_WEB_APPS_API_TOKEN", stdin=token, check=False)
        for key in ("VITE_API_URL", "VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY",
                    "VITE_ENABLE_GOOGLE_AUTH"):
            run("gh", "variable", "set", key, "--body", build_env[key], check=False)


def deploy(env: dict[str, str], skip_image: bool, skip_web: bool) -> None:
    rg, location = env["AZURE_RESOURCE_GROUP"], env["AZURE_LOCATION"]
    print("\n[1/5] Checking Azure")
    sub, acr = preflight(env)

    print("\n[2/5] Image")
    image = build_image(acr, rg, skip_image)
    registry_password = az("acr", "credential", "show", "-n", acr, "--query",
                           "passwords[0].value", "-o", "tsv", capture=True)

    print("\n[3/5] Environment and website")
    if not exists("containerapp", "env", "show", "-n", ENV_NAME, "-g", rg):
        # logs off: Log Analytics charges per GB; live log streaming still works
        az("containerapp", "env", "create", "-n", ENV_NAME, "-g", rg, "--location", location,
           "--logs-destination", "none", "-o", "none")
    env_id = (f"/subscriptions/{sub}/resourceGroups/{rg}"
              f"/providers/Microsoft.App/managedEnvironments/{ENV_NAME}")
    if not exists("staticwebapp", "show", "-n", WEB, "-g", rg):
        az("staticwebapp", "create", "-n", WEB, "-g", rg, "--location",
           env["AZURE_WEB_LOCATION"], "--sku", "Free", "-o", "none")
    web_url = "https://" + (az("staticwebapp", "show", "-n", WEB, "-g", rg, "--query",
                               "defaultHostname", "-o", "tsv", capture=True)
                            or "WEB.azurestaticapps.net")

    print("\n[4/5] API with the demo cloud built in")
    url = arm_url(sub, rg, "containerApps", APP)
    with tempfile.TemporaryDirectory() as tmp:
        arm_put(Path(tmp), url, APP,
                app_spec(env, location, env_id, image, acr, registry_password, web_url))
    api_url = "https://" + (az("rest", "--method", "get", "--url", url, "--query",
                               "properties.configuration.ingress.fqdn", "-o", "tsv",
                               capture=True) or "API.azurecontainerapps.io")
    for kind, name in OLD:  # the separate generator app and collector job are no longer used
        old = arm_url(sub, rg, kind, name)
        if exists("rest", "--method", "get", "--url", old):
            az("rest", "--method", "delete", "--url", old, "-o", "none")
    if shutil.which("gh") and not DRY_RUN:  # hourly trigger (.github/workflows/collect.yml)
        run("gh", "secret", "set", "COLLECTOR_TOKEN", stdin=env["COLLECTOR_TOKEN"], check=False)
        run("gh", "variable", "set", "API_URL", "--body", api_url, check=False)

    print("\n[5/5] Website")
    if not skip_web:
        deploy_web(env, rg, api_url)
    if not DRY_RUN:
        for _ in range(9):  # the first start after a deploy can take a little while
            try:
                with urllib.request.urlopen(f"{api_url}/health", timeout=30) as r:
                    print(f"  API health: {r.status}")
                    break
            except OSError:
                time.sleep(10)
        else:
            print(f"  API not responding yet: az containerapp logs show -n {APP} -g {rg} --follow")
    print(f"""
Done.
  Website: {web_url}
  API:     {api_url}

Once, in Supabase > Authentication > URL Configuration:
  Site URL:       {web_url}
  Redirect URLs:  {web_url}/**
Collection runs hourly from GitHub Actions once collect.yml is on main; "Collect now" on the
Accounts page fetches fresh data at any time.""")


def main() -> None:
    global DRY_RUN
    parser = argparse.ArgumentParser(description="Deploy SyncViewer to Azure.")
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    parser.add_argument("--skip-image", action="store_true", help="reuse the last pushed image")
    parser.add_argument("--skip-web", action="store_true", help="do not rebuild the website")
    args = parser.parse_args()
    DRY_RUN = args.dry_run
    deploy(load_env(), args.skip_image, args.skip_web)


if __name__ == "__main__":
    main()
