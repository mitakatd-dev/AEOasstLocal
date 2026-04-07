"""
Playwright runner for ChatGPT (chatgpt.com).
Login gate is managed by base.py — this file only handles navigation and capture.
"""
from __future__ import annotations

import time
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

# ChatGPT input is a contenteditable div — id has been stable but tag changed.
# Fallbacks tried in order if primary selector times out.
INPUT_SELS   = ['#prompt-textarea', 'div[contenteditable="true"]', 'textarea']
SEND_SEL     = 'button[data-testid="send-button"]'
STOP_SEL     = 'button[data-testid="stop-button"]'
RESPONSE_SEL = '[data-message-author-role="assistant"]'
LOGIN_URL    = "https://chatgpt.com/"

WAIT_MS   = 60_000
STREAM_MS = 300_000


def _dismiss_modals(page: Page) -> None:
    """Dismiss any overlays that could block the input.

    Called before the first attempt AND before each retry — modals can appear
    mid-session (e.g. the memory onboarding modal shown after stored-session login).
    """
    for sel in [
        # Memory onboarding modal — intercepts all pointer events on the textarea.
        # Catch-all for any button inside the modal before falling through to text.
        '[data-testid="modal-memory-onboarding"] button',
        # Generic close / dismiss buttons
        'button[data-testid="close-button"]',
        'button:has-text("Enable memory")',
        'button:has-text("No thanks")',
        'button:has-text("No, thanks")',
        'button:has-text("Dismiss")',
        'button:has-text("Got it")',
        'button:has-text("OK")',
        'button:has-text("Skip")',
        'button:has-text("Maybe later")',
        'button:has-text("Not now")',
        'button:has-text("Continue")',
        'button:has-text("Done")',
        # Upgrade / upsell prompts that can appear mid-session
        'button:has-text("No, stay on free")',
        'button:has-text("Stay on free plan")',
        '[aria-label="Close"]',
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1_000):
                btn.click()
                time.sleep(0.3)
        except Exception:
            pass


def _find_input(page: Page) -> object:
    """Try each input selector in order; raise with diagnostics if none found."""
    for sel in INPUT_SELS:
        try:
            page.wait_for_selector(sel, timeout=10_000)
            el = page.locator(sel).first
            if el.is_visible():
                return el, sel
        except PlaywrightTimeout:
            continue
    # Log page state for diagnosis before giving up
    url   = page.url
    title = page.title()
    raise RuntimeError(
        f"Input not found after trying {INPUT_SELS}. "
        f"Page URL: {url!r}  Title: {title!r}"
    )


def _type_into(page: Page, el, text: str) -> None:
    """Type text into either a textarea or contenteditable div."""
    el.click()
    time.sleep(0.3)
    # Select-all + delete any existing content
    el.press("Control+a")
    el.press("Delete")
    # Use keyboard.type for contenteditable divs (fill() is unreliable)
    page.keyboard.type(text, delay=20)


def _send_prompt(page: Page) -> None:
    """Click the send button, falling back to Enter key if button is blocked."""
    _dismiss_modals(page)
    try:
        btn = page.locator(SEND_SEL)
        btn.wait_for(state="visible", timeout=5_000)
        btn.click(timeout=5_000)
        return
    except Exception:
        pass
    # Fallback: dismiss once more then submit via keyboard
    _dismiss_modals(page)
    page.keyboard.press("Enter")


def _submit_prompt(page: Page, text: str) -> None:
    # Only navigate if we're not already on chatgpt.com — avoids a redundant
    # full page load (and potential network abort) on every prompt.
    if "chatgpt.com" not in page.url:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(1)
    _dismiss_modals(page)
    input_el, matched_sel = _find_input(page)
    # Dismiss again — modals can appear *after* the input is located but before
    # the click, intercepting pointer events.
    _dismiss_modals(page)
    print(f"    [input] Using selector: {matched_sel}")
    _type_into(page, input_el, text)
    _send_prompt(page)


def _wait_for_response(page: Page) -> str:
    try:
        page.wait_for_selector(STOP_SEL, timeout=WAIT_MS)
    except PlaywrightTimeout:
        pass  # fast responses skip stop-button

    # Dismiss any popup that appeared AFTER the prompt was submitted but BEFORE
    # the response finished — these can absorb focus and prevent the stop button
    # from disappearing, causing a 5-minute timeout.
    _dismiss_modals(page)

    try:
        page.wait_for_selector(STOP_SEL, state="hidden", timeout=STREAM_MS)
    except PlaywrightTimeout:
        raise RuntimeError(f"Response timed out after {STREAM_MS // 60_000} minutes.")

    time.sleep(1)

    messages = page.locator(RESPONSE_SEL).all()
    if not messages:
        raise RuntimeError("No assistant message found after response.")

    text = messages[-1].inner_text()
    if not text.strip():
        raise RuntimeError("Response text was empty.")

    return text.strip()


def run_prompt(page: Page, prompt_text: str, setup: bool = False, worker_id: str = None):
    """
    setup=True  → navigate to login page so user can authenticate.
    setup=False → submit one prompt, return (response_text, citations, latency_ms).
    """
    if setup:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        return None, None, None

    t_start = time.time()
    _submit_prompt(page, prompt_text)
    response_text = _wait_for_response(page)
    latency_ms    = int((time.time() - t_start) * 1000)

    return response_text, [], latency_ms
