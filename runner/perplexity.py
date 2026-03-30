"""
Playwright runner for Perplexity (perplexity.ai).
"""
from __future__ import annotations

import time
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

INPUT_SEL    = 'textarea[placeholder*="Ask"], textarea[placeholder*="Search"]'
INPUT_FALL   = 'textarea'
SEND_SEL     = 'button[aria-label="Submit"], button[type="submit"]'
STOP_SEL     = 'button[aria-label="Stop"], button[title="Stop"]'
RESPONSE_SEL = '.prose, .answer-text, [class*="AnswerBody"]'
CITATION_SEL = 'a[href].citation, .source-item a, [class*="Source"] a'
LOGIN_URL    = "https://www.perplexity.ai/"

WAIT_MS   = 60_000
STREAM_MS = 300_000


def _get_input(page: Page):
    for sel in [INPUT_SEL, INPUT_FALL]:
        el = page.locator(sel)
        if el.count() > 0:
            return el.first
    raise RuntimeError("Perplexity input not found.")


def _submit_prompt(page: Page, text: str) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    time.sleep(2)
    input_el = _get_input(page)
    input_el.click()
    input_el.fill(text)
    time.sleep(0.5)
    page.keyboard.press("Enter")


def _wait_for_response(page: Page) -> tuple[str, list]:
    try:
        page.wait_for_selector(RESPONSE_SEL, timeout=WAIT_MS)
    except PlaywrightTimeout:
        raise RuntimeError("Perplexity answer never appeared (60s).")

    # Try stop-button approach first
    stop_appeared = False
    try:
        page.wait_for_selector(STOP_SEL, timeout=15_000)
        stop_appeared = True
    except PlaywrightTimeout:
        pass

    if stop_appeared:
        try:
            page.wait_for_selector(STOP_SEL, state="hidden", timeout=STREAM_MS)
        except PlaywrightTimeout:
            raise RuntimeError("Perplexity response timed out (still generating).")
        time.sleep(1)
    else:
        # Fall back: poll until stable
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
                if stable >= 3:
                    break
            else:
                stable, prev = 0, cur

    # Extract largest prose block
    response_text = ""
    try:
        texts = [el.inner_text() for el in page.locator(RESPONSE_SEL).all()]
        if texts:
            response_text = max(texts, key=len).strip()
    except Exception:
        pass

    # Citations
    citations = []
    try:
        for el in page.locator(CITATION_SEL).all()[:10]:
            href  = el.get_attribute("href")
            label = el.inner_text().strip()
            if href:
                citations.append({"url": href, "label": label})
    except Exception:
        pass

    if not response_text:
        raise RuntimeError("Perplexity response was empty after wait.")

    return response_text, citations


def run_prompt(page: Page, prompt_text: str, setup: bool = False, worker_id: str = None):
    if setup:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        return None, None, None

    t_start = time.time()
    _submit_prompt(page, prompt_text)
    response_text, citations = _wait_for_response(page)
    latency_ms = int((time.time() - t_start) * 1000)

    return response_text, citations, latency_ms
