"""Research Agent — discovers GenAI governance regulations via web search."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from regitel.models.state import ResearchState
from regitel.utils.json_parse import parse_model_json
from regitel.utils.prompts import (
    RESEARCH_EXTRACT_PROMPT,
    RESEARCH_PLAN_PROMPT,
    RESEARCH_SYSTEM,
)
from regitel.utils.usage import merge_usage, usage_from_message

logger = logging.getLogger(__name__)

# Path to the research baseline document
_BASELINE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "research_baseline.md"


def _load_research_baseline() -> str:
    """Load the research baseline document if it exists."""
    if _BASELINE_PATH.exists():
        return _BASELINE_PATH.read_text()
    return ""


def _invoke_with_retry(llm, system_prompt: str, user_prompt: str, max_retries: int = 3):
    """Invoke LLM with retry and exponential backoff."""
    import time
    for attempt in range(max_retries):
        try:
            response = llm.invoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            metadata = getattr(response, "response_metadata", {}) or {}
            if metadata.get("status") == "incomplete":
                logger.warning("LLM response incomplete: %s", metadata.get("incomplete_details"))
            return response
        except Exception as e:
            logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error(f"LLM call failed after {max_retries} attempts")
                return None
    return None


def _format_jurisdiction_profile(seed: dict) -> str:
    """Format a jurisdiction seed dict into a readable profile string."""
    lines = [
        f"Jurisdiction: {seed['name']} ({seed['id']})",
        f"Region: {seed['region']}",
        "Regulatory Bodies:",
    ]
    for rb in seed.get("regulatory_bodies", []):
        lines.append(f"  - {rb['name']} ({rb.get('acronym', 'N/A')}) — {rb.get('url', 'N/A')}")
    lines.append("Key Regulations:")
    for reg in seed.get("key_regulations", []):
        lines.append(f"  - {reg}")
    lines.append("Suggested Search Terms:")
    for term in seed.get("search_terms", []):
        lines.append(f"  - {term}")
    return "\n".join(lines)


def _safe_parse_json(text: str) -> Any:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    return parse_model_json(text, logger=logger, context="Research agent") or []


# ---------------------------------------------------------------------------
# Plan node — generates search queries
# ---------------------------------------------------------------------------

def plan_node(state: ResearchState, *, llm, seeds_map: dict, db_manager) -> dict:
    """Generate targeted search queries for each jurisdiction."""
    jurisdictions = state.get("jurisdictions", [])
    all_queries = []
    token_usage = {}

    session = db_manager.get_session()
    try:
        for jid in jurisdictions:
            seed = seeds_map.get(jid)
            if not seed:
                logger.warning(f"No seed profile for jurisdiction: {jid}")
                continue

            # Get existing regulations from DB
            existing = db_manager.get_regulations_by_jurisdiction(session, jid)
            existing_str = "\n".join(
                f"  - {r.name} ({r.short_name or 'N/A'}) — status: {r.status}, ai_specific: {r.ai_specific}"
                for r in existing
            ) or "  (none — first scan)"

            prompt = RESEARCH_PLAN_PROMPT.format(
                jurisdiction_profile=_format_jurisdiction_profile(seed),
                existing_regulations=existing_str,
            )

            response = _invoke_with_retry(llm, RESEARCH_SYSTEM, prompt)
            token_usage = merge_usage(token_usage, usage_from_message(response))
            if response is None:
                continue
            queries = _safe_parse_json(response.content)
            if isinstance(queries, list):
                for q in queries:
                    q["jurisdiction_id"] = jid
                all_queries.extend(queries)
            else:
                logger.warning(f"Plan returned non-list for {jid}")

            # Also add the seed search terms as fallback queries
            for term in seed.get("search_terms", []):
                all_queries.append({
                    "query": term,
                    "purpose": "seed search term",
                    "priority": 2,
                    "jurisdiction_id": jid,
                })
    finally:
        session.close()

    logger.info(f"Planned {len(all_queries)} search queries across "
                f"{len(jurisdictions)} jurisdictions")
    return {"search_queries": all_queries, "token_usage": token_usage}


# ---------------------------------------------------------------------------
# Research node — executes searches and extracts structured data
# ---------------------------------------------------------------------------

def research_node(state: ResearchState, *, llm, search_tool, seeds_map: dict) -> dict:
    """Execute search queries and extract structured regulation data."""
    queries = state.get("search_queries", [])
    raw_findings = []
    structured_findings = []
    token_usage = {}

    # Group queries by jurisdiction
    queries_by_jid: dict[str, list[dict]] = {}
    for q in queries:
        jid = q.get("jurisdiction_id", "unknown")
        queries_by_jid.setdefault(jid, []).append(q)

    for jid, jid_queries in queries_by_jid.items():
        seed = seeds_map.get(jid, {})

        # Deduplicate and limit queries (top priority first)
        seen = set()
        unique_queries = []
        for q in sorted(jid_queries, key=lambda x: x.get("priority", 5)):
            if q["query"] not in seen:
                seen.add(q["query"])
                unique_queries.append(q)
        unique_queries = unique_queries[:8]  # Cap at 8 queries per jurisdiction

        for q in unique_queries:
            logger.info(f"Searching [{jid}]: {q['query']}")
            results = search_tool.search(q["query"])
            if hasattr(search_tool, "consume_usage"):
                token_usage = merge_usage(token_usage, search_tool.consume_usage())

            if not results:
                continue

            raw_findings.append({
                "jurisdiction_id": jid,
                "query": q["query"],
                "results": results,
            })

            # LLM extraction
            results_text = "\n\n".join(
                f"**{r['title']}** ({r['url']})\n{r['content']}"
                for r in results[:5]  # Top 5 results per query
            )

            prompt = RESEARCH_EXTRACT_PROMPT.format(
                jurisdiction_name=seed.get("name", jid),
                jurisdiction_id=jid,
                query=q["query"],
                search_results=results_text,
            )

            response = _invoke_with_retry(llm, RESEARCH_SYSTEM, prompt)
            token_usage = merge_usage(token_usage, usage_from_message(response))
            if response is None:
                continue

            extracted = _safe_parse_json(response.content)
            if isinstance(extracted, list):
                structured_findings.extend(extracted)
            elif isinstance(extracted, dict):
                structured_findings.append(extracted)

    # Deduplicate structured findings by regulation_id
    seen_ids = set()
    deduped = []
    for f in structured_findings:
        rid = f.get("regulation_id", "")
        if rid and rid not in seen_ids:
            seen_ids.add(rid)
            deduped.append(f)
        elif not rid:
            deduped.append(f)

    logger.info(f"Research found {len(deduped)} unique regulations from "
                f"{len(raw_findings)} search batches")

    return {
        "raw_findings": raw_findings,
        "structured_findings": deduped,
        "token_usage": token_usage,
    }
