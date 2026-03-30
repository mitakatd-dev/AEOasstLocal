from __future__ import annotations

import json
from typing import Dict, List

from sqlalchemy.orm import Session

POSITIVE_WORDS = [
    "excellent", "amazing", "outstanding", "great", "fantastic", "superior",
    "innovative", "leading", "best", "top", "reliable", "trusted", "recommended",
    "impressive", "exceptional", "remarkable", "efficient", "powerful", "robust",
    "seamless", "intuitive", "popular", "preferred", "acclaimed", "award-winning",
    "pioneering", "revolutionary", "cutting-edge", "premium", "world-class",
]

NEGATIVE_WORDS = [
    "poor", "bad", "terrible", "worst", "unreliable", "slow", "expensive",
    "complicated", "difficult", "lacking", "inferior", "outdated", "buggy",
    "frustrating", "disappointing", "weak", "limited", "overpriced", "clunky",
    "mediocre", "problematic", "flawed", "broken", "confusing", "risky",
    "controversial", "criticized", "struggling", "declining", "failed",
]


def analyze(response_text: str, target_company: str, competitors: List[str]) -> Dict:
    if not response_text:
        return {
            "mentioned": False,
            "position_score": None,
            "sentiment": "neutral",
            "competitors_mentioned": [],
        }

    lower_response = response_text.lower()
    lower_target = target_company.lower()

    mentioned = lower_target in lower_response

    position_score = None
    if mentioned:
        first_offset = lower_response.index(lower_target)
        position_score = round(first_offset / len(response_text), 4)

    words = lower_response.split()
    pos_count = sum(1 for w in words if w.strip(".,!?;:()\"'") in POSITIVE_WORDS)
    neg_count = sum(1 for w in words if w.strip(".,!?;:()\"'") in NEGATIVE_WORDS)

    if pos_count > neg_count:
        sentiment = "positive"
    elif neg_count > pos_count:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    competitors_mentioned = [
        c for c in competitors if c.lower() in lower_response
    ]

    return {
        "mentioned": mentioned,
        "position_score": position_score,
        "sentiment": sentiment,
        "competitors_mentioned": competitors_mentioned,
    }


LLM_NAMES = ["openai", "gemini", "perplexity"]


def compare_variants(variant_group: str, db: Session) -> Dict:
    from app.models import Prompt, Run, Result

    prompts = (
        db.query(Prompt)
        .filter(Prompt.variant_group == variant_group)
        .all()
    )

    prompt_data = []
    for p in prompts:
        runs = db.query(Run).filter(Run.prompt_id == p.id).all()
        run_ids = [r.id for r in runs]
        results = (
            db.query(Result).filter(Result.run_id.in_(run_ids)).all()
            if run_ids
            else []
        )

        valid = [r for r in results if not r.error]
        mentioned_count = sum(1 for r in valid if r.mentioned)
        mention_rate = round(mentioned_count / len(valid), 4) if valid else 0.0

        positions = [r.position_score for r in valid if r.mentioned and r.position_score is not None]
        avg_position = round(sum(positions) / len(positions), 4) if positions else None

        sentiment_breakdown = {"positive": 0, "neutral": 0, "negative": 0}
        for r in valid:
            if r.sentiment in sentiment_breakdown:
                sentiment_breakdown[r.sentiment] += 1

        per_llm = {}
        for llm in LLM_NAMES:
            llm_results = [r for r in valid if r.llm == llm]
            llm_mentioned = sum(1 for r in llm_results if r.mentioned)
            llm_rate = round(llm_mentioned / len(llm_results), 4) if llm_results else 0.0
            llm_sentiments = {"positive": 0, "neutral": 0, "negative": 0}
            for r in llm_results:
                if r.sentiment in llm_sentiments:
                    llm_sentiments[r.sentiment] += 1
            top_sentiment = max(llm_sentiments, key=llm_sentiments.get) if llm_results else "neutral"
            per_llm[llm] = {"mention_rate": llm_rate, "avg_sentiment": top_sentiment}

        prompt_data.append({
            "prompt_id": p.id,
            "label": p.label,
            "runs": len(runs),
            "mention_rate": mention_rate,
            "avg_position": avg_position,
            "sentiment_breakdown": sentiment_breakdown,
            "per_llm": per_llm,
        })

    return {"variant_group": variant_group, "prompts": prompt_data}
