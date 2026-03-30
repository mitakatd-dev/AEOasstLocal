from __future__ import annotations

import json
from typing import Dict, List
from sqlalchemy.orm import Session

from app.models import Prompt, Run, Result

LLM_NAMES = ["openai", "gemini", "perplexity"]
LLM_LABELS = {"openai": "OpenAI GPT-4o", "gemini": "Gemini 1.5 Flash", "perplexity": "Perplexity Sonar"}
QUERY_TYPE_LABELS = {
    "category": "Category",
    "problem": "Problem",
    "comparison": "Comparison",
    "brand_direct": "Brand direct",
}


def generate_insights(target_company: str, db: Session, from_date=None, to_date=None) -> Dict:
    """Generate actionable insights from stored data, optionally filtered by date range."""
    prompts = db.query(Prompt).all()
    run_q = db.query(Run)
    if from_date:
        from_val = from_date if len(from_date) > 10 else f"{from_date} 00:00:00"
        run_q = run_q.filter(Run.triggered_at >= from_val)
    if to_date:
        to_val = to_date if len(to_date) > 10 else f"{to_date} 23:59:59"
        run_q = run_q.filter(Run.triggered_at <= to_val)
    runs = run_q.all()
    run_ids = {r.id for r in runs}
    all_results = db.query(Result).all()
    results = [r for r in all_results if r.run_id in run_ids]

    insights = []
    warnings = []

    # ---- Data sufficiency checks ----
    successful_runs = [r for r in runs if r.status in ("completed", "partial")]
    if len(successful_runs) < 5:
        warnings.append({
            "type": "low_data",
            "message": f"Only {len(successful_runs)} successful runs so far. Run at least 10-20 prompts to get reliable insights.",
        })

    # ---- Per-LLM health ----
    llm_summary = {}
    for llm in LLM_NAMES:
        llm_results = [r for r in results if r.llm == llm]
        valid = [r for r in llm_results if not r.error]
        errored = [r for r in llm_results if r.error]

        if len(llm_results) > 0 and len(errored) == len(llm_results):
            insights.append({
                "type": "critical",
                "icon": "alert",
                "title": f"{LLM_LABELS[llm]} is not returning data",
                "detail": f"All {len(errored)} calls to {LLM_LABELS[llm]} have failed. Check your API key in Settings or .env file.",
                "action": "Configure API key",
            })
            llm_summary[llm] = {"status": "no_data", "mention_rate": None}
            continue

        if not valid:
            llm_summary[llm] = {"status": "no_data", "mention_rate": None}
            continue

        mentioned = [r for r in valid if r.mentioned]
        mention_rate = len(mentioned) / len(valid)
        positions = [r.position_score for r in mentioned if r.position_score is not None]
        avg_position = sum(positions) / len(positions) if positions else None

        sentiments = {"positive": 0, "neutral": 0, "negative": 0}
        for r in valid:
            if r.sentiment in sentiments:
                sentiments[r.sentiment] += 1

        llm_summary[llm] = {
            "status": "active",
            "mention_rate": mention_rate,
            "avg_position": avg_position,
            "sentiments": sentiments,
            "total_valid": len(valid),
        }

    # ---- Brand visibility insights ----
    active_llms = {k: v for k, v in llm_summary.items() if v["status"] == "active"}

    if active_llms:
        # Best and worst LLMs
        sorted_by_rate = sorted(active_llms.items(), key=lambda x: x[1]["mention_rate"], reverse=True)
        best_llm, best_data = sorted_by_rate[0]
        best_rate = round(best_data["mention_rate"] * 100)

        if best_rate >= 80:
            insights.append({
                "type": "positive",
                "icon": "check",
                "title": f"{target_company} has strong visibility on {LLM_LABELS[best_llm]}",
                "detail": f"Mentioned in {best_rate}% of queries. "
                          + (f"Average position in the top {round(best_data['avg_position'] * 100)}% of responses." if best_data["avg_position"] and best_data["avg_position"] < 0.3 else ""),
                "action": None,
            })
        elif best_rate >= 50:
            insights.append({
                "type": "neutral",
                "icon": "info",
                "title": f"{target_company} appears in {best_rate}% of {LLM_LABELS[best_llm]} responses",
                "detail": f"Moderate visibility. There's room to improve. Consider testing different prompt framings via Experiments.",
                "action": "Create experiment",
            })
        else:
            insights.append({
                "type": "warning",
                "icon": "warning",
                "title": f"Low visibility: {target_company} mentioned in only {best_rate}% of queries on best LLM",
                "detail": f"Even on {LLM_LABELS[best_llm]} (your best performing LLM), mention rate is low. This suggests LLMs don't strongly associate {target_company} with the topics you're testing.",
                "action": "Review prompt strategy",
            })

        if len(sorted_by_rate) > 1:
            worst_llm, worst_data = sorted_by_rate[-1]
            worst_rate = round(worst_data["mention_rate"] * 100)
            if best_rate - worst_rate >= 30:
                insights.append({
                    "type": "warning",
                    "icon": "gap",
                    "title": f"Visibility gap: {best_rate}% on {LLM_LABELS[best_llm]} vs {worst_rate}% on {LLM_LABELS[worst_llm]}",
                    "detail": f"Your brand performs significantly better on {LLM_LABELS[best_llm]} than {LLM_LABELS[worst_llm]}. Investigate what content each LLM draws from.",
                    "action": "Investigate sources",
                })

        # Position insight
        for llm, data in active_llms.items():
            if data["avg_position"] is not None:
                if data["avg_position"] < 0.15:
                    insights.append({
                        "type": "positive",
                        "icon": "position",
                        "title": f"{target_company} appears early in {LLM_LABELS[llm]} responses",
                        "detail": f"When mentioned, {target_company} appears in the first 15% of the response on average — this is prime positioning, similar to ranking in the top 3 search results.",
                        "action": None,
                    })
                elif data["avg_position"] > 0.6:
                    insights.append({
                        "type": "warning",
                        "icon": "position",
                        "title": f"{target_company} appears late in {LLM_LABELS[llm]} responses",
                        "detail": f"When mentioned, {target_company} appears in the bottom 40% of the response. Users may not read that far. Work on content that positions {target_company} as a primary recommendation.",
                        "action": "Improve positioning",
                    })

        # Sentiment insight
        for llm, data in active_llms.items():
            s = data.get("sentiments", {})
            total_s = sum(s.values())
            if total_s > 0:
                if s["negative"] > s["positive"] and s["negative"] >= 3:
                    insights.append({
                        "type": "critical",
                        "icon": "sentiment",
                        "title": f"Negative sentiment detected on {LLM_LABELS[llm]}",
                        "detail": f"{s['negative']} negative vs {s['positive']} positive responses. Review the raw responses to understand what negative language is being used about {target_company}.",
                        "action": "Review responses",
                    })
                elif s["positive"] > 0 and s["negative"] == 0 and total_s >= 3:
                    insights.append({
                        "type": "positive",
                        "icon": "sentiment",
                        "title": f"Consistently positive sentiment on {LLM_LABELS[llm]}",
                        "detail": f"All {s['positive']} responses with sentiment carry positive language about {target_company}.",
                        "action": None,
                    })

    # ---- Competitor insights ----
    competitor_counts = {}
    total_valid_results = 0
    for r in results:
        if not r.error and r.competitors_mentioned:
            total_valid_results += 1
            try:
                comps = json.loads(r.competitors_mentioned)
                for c in comps:
                    competitor_counts[c] = competitor_counts.get(c, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

    if competitor_counts and total_valid_results > 0:
        sorted_comps = sorted(competitor_counts.items(), key=lambda x: -x[1])
        top_comp, top_count = sorted_comps[0]
        top_rate = round(top_count / total_valid_results * 100)

        if top_rate >= 70:
            insights.append({
                "type": "neutral",
                "icon": "competitor",
                "title": f"{top_comp} is co-mentioned in {top_rate}% of responses",
                "detail": f"LLMs strongly associate {top_comp} with {target_company}. If {top_comp} is your main competitor, consider comparison-type prompts to understand how you're positioned against them.",
                "action": "Add comparison prompts",
            })

        if len(sorted_comps) >= 3:
            top3 = [c[0] for c in sorted_comps[:3]]
            insights.append({
                "type": "neutral",
                "icon": "landscape",
                "title": f"Competitive landscape: {', '.join(top3)}",
                "detail": f"These are the top 3 brands LLMs mention alongside {target_company}. This is your AI-perceived competitive set — it may differ from your actual market positioning.",
                "action": None,
            })

    # ---- Query type analysis ----
    query_type_stats = {}
    for qt in ["category", "problem", "comparison", "brand_direct"]:
        qt_prompts = [p for p in prompts if p.query_type == qt]
        qt_prompt_ids = {p.id for p in qt_prompts}
        qt_runs = [r for r in runs if r.prompt_id in qt_prompt_ids]
        qt_run_ids = {r.id for r in qt_runs}
        qt_results = [r for r in results if r.run_id in qt_run_ids and not r.error]

        if not qt_results:
            query_type_stats[qt] = {"has_data": False, "mention_rate": 0, "count": len(qt_prompts)}
            continue

        qt_mentioned = sum(1 for r in qt_results if r.mentioned)
        qt_rate = round(qt_mentioned / len(qt_results) * 100)
        query_type_stats[qt] = {
            "has_data": True,
            "mention_rate": qt_rate,
            "count": len(qt_prompts),
            "runs": len(qt_results),
        }

    types_with_data = {k: v for k, v in query_type_stats.items() if v["has_data"]}
    types_without_data = {k: v for k, v in query_type_stats.items() if not v["has_data"] and v["count"] > 0}

    if types_with_data:
        best_qt = max(types_with_data.items(), key=lambda x: x[1]["mention_rate"])
        worst_qt = min(types_with_data.items(), key=lambda x: x[1]["mention_rate"])

        if best_qt[1]["mention_rate"] != worst_qt[1]["mention_rate"]:
            insights.append({
                "type": "neutral",
                "icon": "querytype",
                "title": f"Best visibility in {QUERY_TYPE_LABELS[best_qt[0]]} queries ({best_qt[1]['mention_rate']}%)",
                "detail": f"{target_company} performs best when users ask {QUERY_TYPE_LABELS[best_qt[0]].lower()}-style questions "
                          f"({best_qt[1]['mention_rate']}% mention rate) and worst in {QUERY_TYPE_LABELS[worst_qt[0]].lower()} queries "
                          f"({worst_qt[1]['mention_rate']}%). Focus content strategy on improving the weaker query types.",
                "action": "Create targeted prompts",
            })

    if types_without_data:
        missing = [QUERY_TYPE_LABELS[k] for k in types_without_data]
        insights.append({
            "type": "warning",
            "icon": "coverage",
            "title": f"No run data for: {', '.join(missing)}",
            "detail": f"You have prompts tagged as {', '.join(missing).lower()} but haven't run them yet. Run these to complete your baseline audit.",
            "action": "Run tagged prompts",
        })

    # ---- Research readiness ----
    untagged = [p for p in prompts if not p.query_type]
    if len(untagged) > 0 and len(untagged) == len(prompts):
        insights.append({
            "type": "warning",
            "icon": "setup",
            "title": "No prompts are tagged with query types",
            "detail": "Tag your prompts as category, problem, comparison, or brand_direct to unlock query-type analysis. This is essential for the research framework.",
            "action": "Tag prompts",
        })

    experiments_count = 0
    from app.models import Experiment
    experiments_count = db.query(Experiment).count()
    if experiments_count == 0 and len(successful_runs) >= 5:
        insights.append({
            "type": "neutral",
            "icon": "experiment",
            "title": "Ready for experiments",
            "detail": f"You have {len(successful_runs)} successful runs — enough data for a baseline. Create your first experiment to test whether different prompt framings affect mention rate.",
            "action": "Create experiment",
        })

    return {
        "brand": target_company,
        "insights": insights,
        "warnings": warnings,
        "query_type_breakdown": query_type_stats,
        "llm_summary": llm_summary,
        "data_points": {
            "total_prompts": len(prompts),
            "total_runs": len(runs),
            "successful_runs": len(successful_runs),
            "total_results": len(results),
            "valid_results": len([r for r in results if not r.error]),
        },
    }
