"""
OpenAI adapter — uses the Responses API with the web_search tool.
Returns grounded responses with inline url_citation annotations.
"""
import os
import time
import asyncio
from openai import OpenAI


def _extract_citations(output) -> list:
    citations = []
    seen_urls: set = set()
    position = 0
    for item in output:
        if getattr(item, "type", None) == "message":
            for content in getattr(item, "content", []):
                if getattr(content, "type", None) == "output_text":
                    for ann in (getattr(content, "annotations", None) or []):
                        if getattr(ann, "type", None) == "url_citation":
                            url = getattr(ann, "url", "") or ""
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                citations.append({
                                    "url":      url,
                                    "title":    getattr(ann, "title", "") or "",
                                    "position": position,
                                })
                                position += 1
    return citations


def _extract_text(output) -> str:
    parts = []
    for item in output:
        if getattr(item, "type", None) == "message":
            for content in getattr(item, "content", []):
                if getattr(content, "type", None) == "output_text":
                    parts.append(content.text or "")
    return "".join(parts)


async def call(prompt_text: str, timeout: int = 90) -> dict:
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        start = time.time()

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.responses.create,
                model="gpt-4o",
                input=prompt_text,
                tools=[{"type": "web_search"}],
            ),
            timeout=timeout,
        )

        latency_ms    = int((time.time() - start) * 1000)
        text          = _extract_text(response.output)
        citations     = _extract_citations(response.output)
        usage         = getattr(response, "usage", None)
        input_tokens  = getattr(usage, "input_tokens",  0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        web_search_calls = sum(
            1 for item in response.output
            if getattr(item, "type", None) == "web_search_call"
        )
        cost_usd = (
            (input_tokens  * 2.50  / 1_000_000)
            + (output_tokens * 10.00 / 1_000_000)
            + (web_search_calls * 0.035)
        )

        return {
            "response":          text,
            "citations":         citations,
            "latency_ms":        latency_ms,
            "error":             None,
            "prompt_tokens":     input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens":      input_tokens + output_tokens,
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
