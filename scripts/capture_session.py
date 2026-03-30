#!/usr/bin/env python3
"""
Capture a browser login session for AEO browser research.

Opens a real Chrome window, you log in to the target platform, then the script
exports the session (cookies + localStorage) and uploads it to the backend.

The saved session is stored in the DB account pool and reused by Cloud Run
runners so they never need an interactive login.

Usage
-----
# Capture and upload directly:
python scripts/capture_session.py --platform chatgpt --label you@example.com --api https://aeo-api-stg-xxx.run.app --upload

# Capture to file first, upload later via Settings > Browser Accounts in the UI:
python scripts/capture_session.py --platform chatgpt --label you@example.com

Supported platforms: chatgpt, gemini, perplexity

Requirements
------------
  pip install playwright requests
  playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLATFORM_URLS = {
    "chatgpt":    "https://chat.openai.com",
    "gemini":     "https://gemini.google.com",
    "perplexity": "https://www.perplexity.ai",
}


def capture(platform: str) -> dict:
    """Open a browser, let the user log in, return the storage_state dict."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright is not installed.")
        print("  pip install playwright && playwright install chromium")
        sys.exit(1)

    url = PLATFORM_URLS[platform]
    print(f"\n  Opening {platform} — {url}")
    print("  Log in to your account in the browser window that opens.")
    print("  When you're fully logged in and see the main interface, press Enter here.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            slow_mo=50,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(url)

        input("  >> Press Enter once you are logged in and see the main chat interface: ")

        state = context.storage_state()
        browser.close()

    return state


def upload(state: dict, platform: str, label: str, api: str) -> None:
    """Upload the captured session to the backend account pool."""
    try:
        import requests
    except ImportError:
        print("ERROR: requests is not installed.  pip install requests")
        sys.exit(1)

    print(f"\n  Uploading session to {api}/api/accounts/ …")
    r = requests.post(
        f"{api}/api/accounts/",
        json={"platform": platform, "label": label, "storage_state": json.dumps(state)},
        timeout=15,
    )
    try:
        r.raise_for_status()
    except Exception:
        print(f"  ERROR: {r.status_code} — {r.text}")
        sys.exit(1)

    data = r.json()
    print(f"  Uploaded! Account ID: {data['id']}")
    print(f"  Platform: {data['platform']}  Label: {data['label']}  Status: {data['status']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a browser login session for AEO research runners.",
    )
    parser.add_argument(
        "--platform", required=True,
        choices=list(PLATFORM_URLS),
        help="Which assistant to capture (chatgpt | gemini | perplexity)",
    )
    parser.add_argument(
        "--label", required=True,
        help="Email or short name to identify this account in the UI",
    )
    parser.add_argument(
        "--output", default=None,
        help="Save state to this JSON file (default: <platform>_session.json)",
    )
    parser.add_argument(
        "--api", default="http://localhost:8000",
        help="Backend API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--upload", action="store_true",
        help="Upload session to the backend account pool after capturing",
    )
    args = parser.parse_args()

    output_file = args.output or f"{args.platform}_session.json"

    print(f"\n{'='*60}")
    print(f"  AEO Session Capture — {args.platform.upper()}")
    print(f"{'='*60}")

    state = capture(args.platform)

    # Always save locally
    Path(output_file).write_text(json.dumps(state, indent=2))
    print(f"\n  Session saved to: {output_file}")
    cookies = len(state.get("cookies", []))
    origins = len(state.get("origins", []))
    print(f"  Contents: {cookies} cookies, {origins} origin(s) of localStorage")

    if args.upload:
        upload(state, args.platform, args.label, args.api)
    else:
        print(f"\n  To upload to the backend now:")
        print(f"    python scripts/capture_session.py --platform {args.platform} --label {args.label} --api <API_URL> --upload")
        print(f"\n  Or upload via Settings → Browser Accounts in the web UI.")

    print()


if __name__ == "__main__":
    main()
