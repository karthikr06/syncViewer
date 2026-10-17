"""Deploy the SyncViewer backend to Zoho Catalyst AppSail. Run from the repo root:

    backend\\.venv\\Scripts\\python deploy\\catalyst\\deploy.py build    # build both images (Docker)
    backend\\.venv\\Scripts\\python deploy\\catalyst\\deploy.py deploy   # upload them to AppSail
    backend\\.venv\\Scripts\\python deploy\\catalyst\\deploy.py env      # values for the console
    add --dry-run to print the commands without running them

The frontend is deployed separately with Catalyst Slate from GitHub (docs/deployment.md).
"""
import argparse
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SECRETS = HERE / ".secrets"
# AppSail service name -> (local image, folder with its Dockerfile, port the image listens on)
SERVICES = {
    "syncviewerapi": ("syncviewer-api:latest", "backend", 8000),
    "syncviewergen": ("syncviewer-gen:latest", "generator", 8100),
}
DRY_RUN = False


def fail(msg: str) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def run(*cmd: str, cwd: Path = ROOT) -> None:
    print("  $ " + " ".join(cmd))
    if DRY_RUN:
        return
    exe = shutil.which(cmd[0])
    if not exe:
        fail(f"{cmd[0]} not found on PATH")
    if subprocess.run([exe, *cmd[1:]], cwd=cwd, check=False).returncode != 0:
        fail(f"{cmd[0]} {cmd[1]} failed")


def load_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        fail(".env not found in the repo root")
    return {k: (v or "") for k, v in dotenv_values(path).items()}


def build() -> None:
    """Images must be linux/amd64, the only platform AppSail runs."""
    for image, folder, _ in SERVICES.values():
        run("docker", "build", "--platform=linux/amd64", "-t", image, folder)


def deploy() -> None:
    """Standalone AppSail deploys; run `catalyst init` in deploy/catalyst once beforehand."""
    if not DRY_RUN and not (HERE / "catalyst.json").exists():
        fail("deploy/catalyst is not a Catalyst project yet: cd deploy/catalyst and run catalyst init")
    for name, (image, _, port) in SERVICES.items():
        run("catalyst", "deploy", "appsail", "--name", name, "--source", f"docker://{image}",
            "--port", str(port), cwd=HERE)


def console_values(env: dict[str, str]) -> None:
    """Write the environment variables to paste into each AppSail service (git-ignored file)."""
    urls = {k: env.get(k, "").rstrip("/") for k in
            ("CATALYST_API_URL", "CATALYST_GEN_URL", "CATALYST_WEB_URL")}
    missing = [k for k, v in urls.items() if not v]
    if missing:
        fail("add these to .env first (copy them from the Catalyst console): " + ", ".join(missing))
    for key in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_JWKS_URL", "CREDENTIAL_ENCRYPTION_KEY"):
        if not env.get(key):
            fail(f"{key} is empty in .env")
    if env.get("GENERATOR_API_KEY") in (None, "", "change-me"):
        fail("set GENERATOR_API_KEY in .env to a long random value")
    token = env.get("COLLECTOR_TOKEN")
    if not token:
        fail("add COLLECTOR_TOKEN to .env, for example: COLLECTOR_TOKEN=" + secrets.token_urlsafe(32))

    api = {
        "APP_ENV": "production",
        "DATABASE_URL": env["DATABASE_URL"],
        "SUPABASE_URL": env["SUPABASE_URL"],
        "SUPABASE_JWKS_URL": env["SUPABASE_JWKS_URL"],
        "SUPABASE_JWT_SECRET": env.get("SUPABASE_JWT_SECRET", ""),
        "CREDENTIAL_ENCRYPTION_KEY": env["CREDENTIAL_ENCRYPTION_KEY"],
        "CORS_ORIGINS": urls["CATALYST_WEB_URL"],
        "ADMIN_EMAILS": env.get("ADMIN_EMAILS", ""),
        "GENERATOR_URL": urls["CATALYST_GEN_URL"],
        "GENERATOR_API_KEY": env["GENERATOR_API_KEY"],
        "GOOGLE_API_KEY": env.get("GOOGLE_API_KEY", ""),
        "GEMINI_MODEL": env.get("GEMINI_MODEL", ""),
        "RAW_RETENTION_DAYS": env.get("RAW_RETENTION_DAYS") or "14",
        "COLLECTOR_TOKEN": token,
        # AppSail ends requests after 30 s; answer before that
        "AGENT_TIMEOUT_SECONDS": "25",
    }
    gen = {"GENERATOR_API_KEY": env["GENERATOR_API_KEY"]}
    slate = {"VITE_API_URL": urls["CATALYST_API_URL"],
             "VITE_SUPABASE_URL": env.get("VITE_SUPABASE_URL") or env["SUPABASE_URL"],
             "VITE_SUPABASE_ANON_KEY": env.get("VITE_SUPABASE_ANON_KEY", ""),
             "VITE_ENABLE_GOOGLE_AUTH": env.get("VITE_ENABLE_GOOGLE_AUTH") or "false"}

    SECRETS.mkdir(exist_ok=True)
    out = SECRETS / "console-values.txt"
    sections = [("AppSail syncviewerapi > Configuration > Environment Variables", api),
                ("AppSail syncviewergen > Configuration > Environment Variables", gen),
                ("Slate > Configuration > Environment Variables", slate)]
    lines = []
    for title, values in sections:
        lines += [f"## {title}", *(f"{k}={v}" for k, v in values.items() if v), ""]
    job = f"{urls['CATALYST_API_URL']}/api/v1/internal/collect"
    lines += ["## Job Scheduling > webhook job (every 30 minutes)", "Method: POST", f"URL: {job}",
              f"Header: X-Collector-Token: {token}", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} (git-ignored; it contains secrets, never share it).")


def main() -> None:
    global DRY_RUN
    parser = argparse.ArgumentParser(description="Deploy SyncViewer's backend to Catalyst.")
    parser.add_argument("command", choices=["build", "deploy", "env"])
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    args = parser.parse_args()
    DRY_RUN = args.dry_run
    {"build": build, "deploy": deploy, "env": lambda: console_values(load_env())}[args.command]()


if __name__ == "__main__":
    main()
