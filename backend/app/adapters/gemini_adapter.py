"""
Gemini adapter — uses google-genai SDK with Google Search grounding.
Returns responses with structured citation data from groundingChunks.
"""
import os
import time
import asyncio
from google import genai
from google.genai import types


def _extract_citations(response) -> list:
    citations = []
    try:
        grounding = response.candidates[0].grounding_metadata
        if not grounding or not grounding.grounding_chunks:
            return citations
        for i, chunk in enumerate(grounding.grounding_chunks):
            web = getattr(chunk, "web", None)
            if web:
                url = getattr(web, "uri", "") or ""
                if url:
                    citations.append({
                        "url":      url,
                        "title":    getattr(web, "title", "") or "",
                        "position": i,
                    })
    except Exception:
        pass
    return citations


async def call(prompt_text: str, timeout: int = 90) -> dict:
    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        start  = time.time()

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.0-flash",
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
            ),
            timeout=timeout,
        )

        latency_ms = int((time.time() - start) * 1000)
        text       = response.text or ""
        citations  = _extract_citations(response)

        usage            = getattr(response, "usage_metadata", None)
        prompt_tokens    = getattr(usage, "prompt_token_count",     0) or 0
        completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
        total_tokens     = getattr(usage, "total_token_count", prompt_tokens + completion_tokens) or 0

        # gemini-2.0-flash: $0.10/1M input, $0.40/1M output + $35/1000 grounded prompts
        cost_usd = (
            (prompt_tokens    * 0.10 / 1_000_000)
            + (completion_tokens * 0.40 / 1_000_000)
            + (0.035 if citations else 0.0)   # grounding surcharge per call
        )

        return {
            "response":          text,
            "citations":         citations,
            "latency_ms":        latency_ms,
            "error":             None,
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens":      total_tokens,
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
