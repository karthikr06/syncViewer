"""Model-in-the-loop eval (local, needs GOOGLE_API_KEY and a populated database).

    python -m app.agent.evals.run_model --owner <user-uuid>

Asks each eval question through the real agent and checks that the expected VM names appear in
the reply. Ground truth comes from the generator, so the owner must have a `mock` account whose
external_ref is passed with --account-ref and scenario with --scenario.
"""
import argparse
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from app.agent.evals.cases import EVAL_CASES, EvalContext
from app.agent.runner import run_chat
from app.core.config import load_settings_or_exit
from app.core.db import get_session_factory
from app.models import Resource


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--account-ref", required=True)
    ap.add_argument("--scenario", default="medium")
    ap.add_argument("--delay", type=float, default=15.0, help="seconds between questions")
    args = ap.parse_args()
    settings = load_settings_or_exit(["DATABASE_URL", "GOOGLE_API_KEY"])
    factory = get_session_factory(settings.database_url)
    owner = uuid.UUID(args.owner)

    now = datetime.now(UTC)
    headers = {"X-API-Key": settings.generator_api_key} if settings.generator_api_key else {}
    truth = httpx.get(
        f"{settings.generator_url}/v1/accounts/{args.account_ref}/ground-truth", headers=headers,
        params={"scenario": args.scenario, "start": (now - timedelta(days=7)).isoformat(),
                "end": now.isoformat()}).json()
    with factory() as s:
        from sqlalchemy import select

        names = {r.external_id: r.name for r in s.scalars(select(Resource))}
        by_role: dict[str, list[str]] = {}
        for r in truth["resources"]:
            by_role.setdefault(r["role"], []).append(names[r["id"]])
        ctx = EvalContext(s, owner, uuid.uuid4(), truth, names, by_role)
        passed = 0
        for i, case in enumerate(EVAL_CASES):
            if i:
                time.sleep(args.delay)  # stay under free-tier requests-per-minute limits
            question = case.ask(ctx)
            reply = run_chat(factory, settings, owner, question, None).reply
            ok = case.passes(ctx, reply)
            passed += ok
            print(f"[{'PASS' if ok else 'FAIL'}] {case.id}: {question}")
            if not ok:
                print(f"    expected {case.expected_in_answer(ctx)}\n    got: {reply[:300]!r}")
    print(f"{passed}/{len(EVAL_CASES)} passed")
    return 0 if passed == len(EVAL_CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
