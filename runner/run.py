"""
AEO Insights — Playwright browser runner CLI entry point.

Usage:
    python run.py --platform chatgpt
    python run.py --platform gemini   --name worker-2 --batch-size 50
    python run.py --platform perplexity --api http://192.168.1.10:8000

Options:
    --platform    chatgpt | gemini | perplexity  (required)
    --name        worker name, default: <platform>-1
    --batch-size  prompts to claim, default: 100
    --api         backend URL, default: http://localhost:8000
                  (can also be set via AEO_API env var)
"""
from __future__ import annotations

import argparse
import os
import sys

PLATFORMS = {
    "chatgpt":    "runner.chatgpt",
    "gemini":     "runner.gemini",
    "perplexity": "runner.perplexity",
}


def main():
    parser = argparse.ArgumentParser(
        description="AEO Insights — Playwright browser runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--platform", required=True, choices=list(PLATFORMS),
        help="Which platform to run against"
    )
    parser.add_argument(
        "--name", default=None,
        help="Worker name (used for checkpointing). Default: <platform>-1"
    )
    parser.add_argument(
        "--batch-size", type=int, default=100,
        help="Number of prompts to claim in this run"
    )
    parser.add_argument(
        "--api", default=None,
        help="Backend API base URL. Default: http://localhost:8000"
    )

    args = parser.parse_args()

    # Apply --api before importing base (it reads env at import time)
    if args.api:
        os.environ["AEO_API"] = args.api

    name = args.name or f"{args.platform}-1"

    # Verify backend is reachable before opening a browser
    import requests as req
    api_base = os.getenv("AEO_API", "http://localhost:8000")
    try:
        r = req.get(f"{api_base}/api/health", timeout=5)
        r.raise_for_status()
    except Exception as exc:
        print(f"\n[error] Cannot reach backend at {api_base}/api/health")
        print(f"        {exc}")
        print(f"\n  Make sure the AEO Insights backend is running:")
        print(f"    cd backend && uvicorn app.main:app --reload --port 8000\n")
        sys.exit(1)

    print(f"  Backend reachable at {api_base}")

    # Import platform module and run
    if args.platform == "chatgpt":
        from runner.chatgpt import run_prompt
    elif args.platform == "gemini":
        from runner.gemini import run_prompt
    elif args.platform == "perplexity":
        from runner.perplexity import run_prompt
    else:
        print(f"Unknown platform: {args.platform}")
        sys.exit(1)

    # Optional: specific prompt IDs and session passed via env from runner_manager
    prompt_ids_env = os.getenv("AEO_PROMPT_IDS")
    if prompt_ids_env:
        try:
            prompt_ids = [int(x) for x in prompt_ids_env.split(",") if x.strip()]
        except ValueError as exc:
            print(f"[error] AEO_PROMPT_IDS contains non-integer value: {prompt_ids_env!r} — {exc}")
            sys.exit(1)
    else:
        prompt_ids = None
    session_id = os.getenv("AEO_SESSION_ID") or None

    from runner.base import run_batch
    run_batch(
        platform=args.platform,
        name=name,
        batch_size=args.batch_size,
        run_prompt_fn=run_prompt,
        prompt_ids=prompt_ids,
        session_id=session_id,
    )


if __name__ == "__main__":
    main()
