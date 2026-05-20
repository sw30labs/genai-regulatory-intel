"""Reflection Agent — analyzes validation failures and guides re-research."""

from __future__ import annotations

import json
import logging

from regitel.agents.research import _load_research_baseline
from regitel.models.state import ResearchState
from regitel.utils.json_parse import parse_model_json
from regitel.utils.prompts import REFLECTION_PROMPT, REFLECTION_SYSTEM
from regitel.utils.usage import usage_from_message

logger = logging.getLogger(__name__)


def _safe_parse_json(text: str):
    parsed = parse_model_json(text, logger=logger, context="Reflection")
    if parsed is not None:
        return parsed
    return {"analysis": "Parse error", "actions": [], "drop_regulation_ids": [],
            "keep_regulation_ids": []}


def reflect_node(state: ResearchState, *, llm) -> dict:
    """Analyze validation failures and produce targeted feedback."""
    validation_result = state.get("validation_result", {})
    findings = state.get("structured_findings", [])
    iteration = state.get("iteration_count", 0) + 1
    max_iter = state.get("max_iterations", 3)

    if iteration > max_iter:
        logger.warning(f"Max reflection iterations ({max_iter}) reached — "
                       "flagging for human review")
        return {
            "iteration_count": iteration,
            "reflection_notes": f"MAX ITERATIONS REACHED ({max_iter}). "
                                "Findings persisted with low confidence.",
            "validation_passed": True,  # Force exit the loop
        }

    # Build jurisdiction list from findings
    jids = list(set(f.get("jurisdiction_id", "unknown") for f in findings))

    remaining = max_iter - iteration
    validation_passed = validation_result.get("passed", False)

    # Contextualise why reflection was triggered
    if validation_passed:
        reason = (
            "Validation PASSED, but this is a quality-gate review of NEW findings. "
            "Verify the findings are grounded, complete, and not hallucinated. "
            "Check ai_specific classifications carefully. "
            "If everything looks solid, return an empty actions list and keep all findings."
        )
    else:
        reason = "Validation FAILED. Analyse the issues below and recommend fixes."

    final_warning = (
        "FINAL ITERATION — prioritize salvaging existing findings over new research."
        if remaining == 0 else ""
    )

    # Load research baseline for cross-referencing
    baseline = _load_research_baseline()
    # Summarize the baseline (first 3000 chars is enough for context)
    baseline_summary = baseline[:3000] if baseline else "(No research baseline found)"

    prompt = REFLECTION_PROMPT.format(
        jurisdiction_id=", ".join(jids),
        reflection_reason=reason,
        iteration=iteration,
        max_iterations=max_iter,
        final_iteration_warning=final_warning,
        remaining_iterations=remaining,
        validation_result=json.dumps(validation_result, indent=2, default=str),
        findings_json=json.dumps(findings, indent=2, default=str),
        research_baseline_summary=baseline_summary,
    )

    # Retry with backoff — reflection calls are prone to transient connection errors
    import time
    response = None
    for attempt in range(3):
        try:
            response = llm.invoke([
                {"role": "system", "content": REFLECTION_SYSTEM},
                {"role": "user", "content": prompt},
            ])
            break
        except Exception as e:
            logger.warning(f"Reflection LLM call failed (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)  # 1s, 2s backoff
            else:
                logger.error("Reflection LLM call failed after 3 attempts — "
                             "forcing pass-through")
                return {
                    "iteration_count": iteration,
                    "reflection_notes": f"LLM connection failed after 3 retries: {e}",
                    "validation_passed": True,  # Force exit — persist what we have
                }

    reflection = _safe_parse_json(response.content)

    # Apply reflection: drop rejected findings, keep good ones
    drop_ids = set(reflection.get("drop_regulation_ids", []))
    if drop_ids:
        findings = [f for f in findings if f.get("regulation_id") not in drop_ids]
        logger.info(f"Reflection dropped {len(drop_ids)} findings: {drop_ids}")

    # Generate additional search queries from reflection actions
    new_queries = []
    for action in reflection.get("actions", []):
        if action.get("search_query"):
            new_queries.append({
                "query": action["search_query"],
                "purpose": action.get("instruction", "reflection-driven re-research"),
                "priority": 1,
                "jurisdiction_id": action.get("regulation_id", "").split("-")[0]
                                   if action.get("regulation_id") else jids[0],
            })

    notes = reflection.get("analysis", "No analysis provided")
    logger.info(f"Reflection iteration {iteration}: {notes[:100]}... "
                f"({len(new_queries)} new queries, {len(drop_ids)} dropped)")

    return {
        "iteration_count": iteration,
        "reflection_notes": notes,
        "structured_findings": findings,  # Updated (with drops applied)
        "search_queries": new_queries,    # Feeds back into research if needed
        "token_usage": usage_from_message(response),
    }
