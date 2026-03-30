from __future__ import annotations

import json
import re
from typing import Dict, List, Optional
from collections import Counter
from sqlalchemy.orm import Session

from app.models import Prompt, Run, Result


def extract_mention_context(text: str, brand: str, window: int = 200) -> Optional[str]:
    """Extract text surrounding the brand mention."""
    if not text or not brand:
        return None
    lower = text.lower()
    idx = lower.find(brand.lower())
    if idx == -1:
        return None
    start = max(0, idx - window)
    end = min(len(text), idx + len(brand) + window)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def extract_descriptors(text: str, brand: str) -> List[str]:
    """Extract adjectives/phrases used near the brand mention."""
    if not text or not brand:
        return []
    lower = text.lower()
    idx = lower.find(brand.lower())
    if idx == -1:
        return []
    # Get sentence containing the brand
    start = text.rfind('.', 0, idx)
    start = start + 1 if start != -1 else 0
    end = text.find('.', idx + len(brand))
    end = end + 1 if end != -1 else len(text)
    sentence = text[start:end].strip()

    descriptors = []
    descriptor_words = [
        "largest", "biggest", "leading", "top", "best", "premier", "major",
        "global", "worldwide", "international", "renowned", "well-known",
        "reliable", "trusted", "innovative", "efficient", "comprehensive",
        "dominant", "significant", "prominent", "established", "reputable",
        "first", "pioneering", "strongest", "popular", "preferred",
        "expensive", "costly", "slow", "limited", "struggling", "declining",
        "controversial", "complex", "traditional", "legacy",
    ]
    sentence_lower = sentence.lower()
    for word in descriptor_words:
        if word in sentence_lower:
            descriptors.append(word)
    return descriptors


def build_narrative_report(target_company: str, competitors: List[str], db: Session, from_date=None, to_date=None) -> Dict:
    """Build a comprehensive narrative analysis, optionally filtered by date range."""
    result_q = db.query(Result).join(Run, Run.id == Result.run_id).filter(
        Result.error.is_(None), Result.raw_response.isnot(None)
    )
    if from_date:
        from_val = from_date if len(from_date) > 10 else f"{from_date} 00:00:00"
        result_q = result_q.filter(Run.triggered_at >= from_val)
    if to_date:
        to_val = to_date if len(to_date) > 10 else f"{to_date} 23:59:59"
        result_q = result_q.filter(Run.triggered_at <= to_val)
    results = result_q.all()

    if not results:
        return {"has_data": False}

    # --- Brand narrative ---
    brand_mentions = []
    brand_descriptors = Counter()
    brand_contexts = []

    for r in results:
        text = r.raw_response or ""
        if not r.mentioned:
            continue

        ctx = extract_mention_context(text, target_company)
        if ctx:
            prompt = db.query(Prompt).join(Run).filter(Run.id == r.run_id).first()
            brand_contexts.append({
                "llm": r.llm,
                "context": ctx,
                "prompt_label": prompt.label if prompt else "",
                "sentiment": r.sentiment,
                "position_score": r.position_score,
            })

        descs = extract_descriptors(text, target_company)
        for d in descs:
            brand_descriptors[d] += 1

    # --- Group results by LLM for per-engine breakdown ---
    from collections import defaultdict
    results_by_llm: dict = defaultdict(list)
    for r in results:
        results_by_llm[r.llm].append(r)

    # --- Competitor narratives ---
    competitor_data = {}
    for comp in competitors:
        comp_contexts = []
        comp_descriptors = Counter()
        comp_mention_count = 0

        # Per-LLM mention counts
        by_llm: dict = {}
        for llm, llm_results in results_by_llm.items():
            llm_comp_mentions = 0
            for r in llm_results:
                text = r.raw_response or ""
                if comp.lower() in text.lower():
                    llm_comp_mentions += 1
            by_llm[llm] = {
                "mentions": llm_comp_mentions,
                "mention_rate": round(llm_comp_mentions / len(llm_results) * 100, 1) if llm_results else 0,
            }

        for r in results:
            text = r.raw_response or ""
            if comp.lower() not in text.lower():
                continue
            comp_mention_count += 1

            ctx = extract_mention_context(text, comp, window=150)
            if ctx:
                comp_contexts.append({
                    "llm": r.llm,
                    "context": ctx,
                })

            descs = extract_descriptors(text, comp)
            for d in descs:
                comp_descriptors[d] += 1

        if comp_mention_count > 0:
            competitor_data[comp] = {
                "mentions": comp_mention_count,
                "mention_rate": round(comp_mention_count / len(results) * 100, 1),
                "by_llm": by_llm,
                "descriptors": comp_descriptors.most_common(5),
                "sample_context": comp_contexts[0]["context"] if comp_contexts else None,
            }

    # Sort competitors by mentions
    sorted_competitors = sorted(competitor_data.items(), key=lambda x: -x[1]["mentions"])

    # --- Positioning analysis ---
    # What do top competitors get described as that the brand doesn't?
    top_comp_descriptors = Counter()
    for comp, data in sorted_competitors[:5]:
        for word, count in data["descriptors"]:
            top_comp_descriptors[word] += count

    brand_desc_set = set(brand_descriptors.keys())
    competitor_unique = {w: c for w, c in top_comp_descriptors.most_common(10) if w not in brand_desc_set}

    # --- Non-mention analysis ---
    # When brand is NOT mentioned, what prompts and what competitors appear instead?
    non_mention_results = [r for r in results if not r.mentioned]
    non_mention_competitors = Counter()
    non_mention_prompts = Counter()
    for r in non_mention_results:
        text = (r.raw_response or "").lower()
        for comp in competitors:
            if comp.lower() in text:
                non_mention_competitors[comp] += 1
        prompt = db.query(Prompt).join(Run).filter(Run.id == r.run_id).first()
        if prompt:
            non_mention_prompts[prompt.label] += 1

    # --- Per-LLM brand mention rates ---
    brand_by_llm: dict = {}
    for llm, llm_results in results_by_llm.items():
        llm_mentioned = sum(1 for r in llm_results if r.mentioned)
        brand_by_llm[llm] = {
            "mentions": llm_mentioned,
            "mention_rate": round(llm_mentioned / len(llm_results) * 100, 1) if llm_results else 0,
            "total": len(llm_results),
        }

    # --- Summary stats ---
    total_valid = len(results)
    mentioned_count = len([r for r in results if r.mentioned])
    mention_rate = round(mentioned_count / total_valid * 100, 1) if total_valid > 0 else 0

    positions = [r.position_score for r in results if r.mentioned and r.position_score is not None]
    avg_position = round(sum(positions) / len(positions), 3) if positions else None
    position_label = "N/A"
    if avg_position is not None:
        if avg_position < 0.15:
            position_label = "Top of response (first 15%)"
        elif avg_position < 0.35:
            position_label = "Early (top third)"
        elif avg_position < 0.65:
            position_label = "Middle"
        else:
            position_label = "Late (bottom third)"

    return {
        "has_data": True,
        "summary": {
            "total_results": total_valid,
            "mention_rate": mention_rate,
            "avg_position": avg_position,
            "position_label": position_label,
            "mentioned_count": mentioned_count,
            "not_mentioned_count": total_valid - mentioned_count,
            "by_llm": brand_by_llm,
        },
        "brand_narrative": {
            "descriptors": brand_descriptors.most_common(10),
            "contexts": brand_contexts[:10],  # Top 10 examples
        },
        "competitors": [
            {"name": name, **data} for name, data in sorted_competitors[:10]
        ],
        "positioning_gaps": [
            {"descriptor": w, "competitor_count": c}
            for w, c in list(competitor_unique.items())[:5]
        ],
        "blind_spots": {
            "prompts_where_not_mentioned": non_mention_prompts.most_common(5),
            "competitors_appearing_instead": non_mention_competitors.most_common(5),
        },
    }
