"""
Playwright runner for Google Gemini (gemini.google.com).
"""
from __future__ import annotations

import time
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

INPUT_SEL      = 'div.ql-editor[contenteditable="true"]'
INPUT_FALLBACK = 'rich-textarea .ql-editor'
SEND_SEL       = 'button.send-button, button[aria-label="Send message"]'
RESPONSE_SEL   = '.model-response-text, .response-content .markdown, .response-text'
CITATION_SEL   = 'a[data-source], .citation a, .source-chip a, [aria-label*="source"] a'
LOGIN_URL      = "https://gemini.google.com/app"

WAIT_MS   = 60_000
STREAM_MS = 300_000


def _get_input(page: Page):
    for sel in [INPUT_SEL, INPUT_FALLBACK]:
        el = page.locator(sel)
        if el.count() > 0:
            return el.first
    raise RuntimeError("Gemini input not found. Is the page fully loaded?")


def _submit_prompt(page: Page, text: str) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    time.sleep(2)
    input_el = _get_input(page)
    input_el.click()
    page.keyboard.type(text, delay=20)
    time.sleep(0.5)
    page.locator(SEND_SEL).first.click()


def _wait_for_response(page: Page) -> str:
    try:
        page.wait_for_selector(RESPONSE_SEL, timeout=WAIT_MS)
    except PlaywrightTimeout:
        raise RuntimeError("Gemini response never appeared (60s timeout).")

    # Poll until text stabilises (Gemini streams without a clear stop indicator)
    prev, stable, deadline = "", 0, time.time() + (STREAM_MS / 1000)
    while time.time() < deadline:
        time.sleep(2)
        try:
            els = page.locator(RESPONSE_SEL).all()
            cur = els[-1].inner_text() if els else ""
        except Exception:
            continue
        if cur and cur == prev:
            stable += 1
            if stable >= 3:  # 3 × 2 s = 6 s of unchanged text → stream has finished
                return cur.strip()
        else:
            stable, prev = 0, cur

    raise RuntimeError("Gemini response did not stabilise within 5 minutes.")


def run_prompt(page: Page, prompt_text: str, setup: bool = False, worker_id: str = None):
    if setup:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        return None, None, None

    t_start = time.time()
    _submit_prompt(page, prompt_text)
    response_text = _wait_for_response(page)
    latency_ms    = int((time.time() - t_start) * 1000)

    # Extract source citations from Gemini Sources panel
    citations = []
    try:
        for el in page.locator(CITATION_SEL).all()[:10]:
            href  = el.get_attribute('href')
            label = el.inner_text().strip()
            if href and href.startswith('http'):
                citations.append({'url': href, 'label': label})
    except Exception:
        pass

    return response_text, citations, latency_ms
