"""
Perplexity adapter — sonar-pro via OpenAI-compatible client.
Web search is built-in; extracts structured citations and search_results.
"""
import os
import time
import asyncio
from openai import OpenAI


def _extract_citations(data: dict) -> list:
    """
    Build citation list from Perplexity response extras.
    Prefers search_results (has title + date) and falls back to citations URL list.
    """
    citations = []
    seen: set = set()

    # search_results is the richest source: {title, url, date, last_updated}
    for i, src in enumerate((data.get("search_results") or [])):
        url = src.get("url", "") or ""
        if url and url not in seen:
            seen.add(url)
            citations.append({
                "url":      url,
                "title":    src.get("title", "") or "",
                "position": i,
            })

    # Fallback: top-level citations[] is a plain URL list
    if not citations:
        for i, url in enumerate((data.get("citations") or [])):
            if url and url not in seen:
                seen.add(url)
                citations.append({"url": url, "title": "", "position": i})

    return citations


async def call(prompt_text: str, timeout: int = 90) -> dict:
    try:
        client = OpenAI(
            api_key=os.getenv("PERPLEXITY_API_KEY"),
            base_url="https://api.perplexity.ai",
        )
        start = time.time()

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model="sonar-pro",
                messages=[{"role": "user", "content": prompt_text}],
            ),
            timeout=timeout,
        )

        latency_ms = int((time.time() - start) * 1000)

        # Perplexity extras live in model_extra on the response object
        extra     = getattr(response, "model_extra", {}) or {}
        citations = _extract_citations(extra)

        text = response.choices[0].message.content or ""

        usage             = response.usage
        prompt_tokens     = getattr(usage, "prompt_tokens",     0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0

        # sonar-pro: $3/1M input, $15/1M output + $10/1000 requests (medium context)
        cost_usd = (
            (prompt_tokens    * 3.00  / 1_000_000)
            + (completion_tokens * 15.00 / 1_000_000)
            + 0.010   # per-request fee (medium context)
        )

        return {
            "response":          text,
            "citations":         citations,
            "latency_ms":        latency_ms,
            "error":             None,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens":      prompt_tokens + completion_tokens,
            "cost_usd":          round(cost_usd, 6),
        }

    except asyncio.TimeoutError:
        return {
            "response": None, "citations": [], "latency_ms": timeout * 1000,
            "error": f"Timeout after {timeout}s",
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
        }
    except Exception as e:
        return {
            "response": None, "citations": [], "latency_ms": 0, "error": str(e),
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
        }
