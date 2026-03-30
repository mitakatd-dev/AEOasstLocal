from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Prompt

router = APIRouter(prefix="/api/seed", tags=["seed"])

SEED_TEMPLATES = [
    # Category
    {"label": "Best tools for [use case]", "text": "What are the best tools for [use case]?", "query_type": "category"},
    {"label": "Platforms teams use for [use case]", "text": "Which platforms do teams use for [use case]?", "query_type": "category"},
    {"label": "Recommended software for [use case]", "text": "What software would you recommend for [use case]?", "query_type": "category"},
    {"label": "Top [use case] tools in [year]", "text": "Top [use case] tools in [year]?", "query_type": "category"},
    {"label": "Most used for [use case]", "text": "What do most companies use for [use case]?", "query_type": "category"},
    # Problem
    {"label": "Tool to [solve problem]", "text": "I need to [solve problem], what tool should I use?", "query_type": "problem"},
    {"label": "Easiest way to [achieve outcome]", "text": "What's the easiest way to [achieve outcome]?", "query_type": "problem"},
    {"label": "[Company type] trying to [goal]", "text": "We're a [company type] trying to [goal], what do you recommend?", "query_type": "problem"},
    {"label": "How to [task] without [pain point]", "text": "How do I [specific task] without [pain point]?", "query_type": "problem"},
    {"label": "What to use for [job to be done]", "text": "What would you use if you needed to [job to be done]?", "query_type": "problem"},
    # Comparison
    {"label": "{{brand}} vs [Competitor A]", "text": "{{brand}} vs [Competitor A] — which is better for [use case]?", "query_type": "comparison"},
    {"label": "Compare {{brand}} and competitors", "text": "Compare {{brand}}, [Competitor A], and [Competitor B]", "query_type": "comparison"},
    {"label": "Pros and cons {{brand}} vs [Competitor A]", "text": "What are the pros and cons of {{brand}} vs [Competitor A]?", "query_type": "comparison"},
    {"label": "{{brand}} or [Competitor A] for [size]", "text": "Is {{brand}} or [Competitor A] better for [company size]?", "query_type": "comparison"},
    {"label": "{{brand}} vs alternatives", "text": "How does {{brand}} compare to alternatives?", "query_type": "comparison"},
    # Brand direct
    {"label": "Tell me about {{brand}}", "text": "Tell me about {{brand}}", "query_type": "brand_direct"},
    {"label": "What does {{brand}} do?", "text": "What does {{brand}} do?", "query_type": "brand_direct"},
    {"label": "Who uses {{brand}}?", "text": "Who uses {{brand}} and why?", "query_type": "brand_direct"},
    {"label": "{{brand}} strengths and weaknesses", "text": "What are the main strengths and weaknesses of {{brand}}?", "query_type": "brand_direct"},
    {"label": "Is {{brand}} good for [use case]?", "text": "Is {{brand}} a good choice for [use case]?", "query_type": "brand_direct"},
]


@router.post("/templates", status_code=201)
def seed_templates(db: Session = Depends(get_db)):
    created = 0
    for t in SEED_TEMPLATES:
        exists = db.query(Prompt).filter(
            Prompt.label == t["label"],
            Prompt.query_type == t["query_type"],
        ).first()
        if not exists:
            db.add(Prompt(**t))
            created += 1
    db.commit()
    return {"seeded": created, "total_templates": len(SEED_TEMPLATES)}
