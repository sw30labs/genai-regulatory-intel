"""Validator Agent — quality-checks research findings before persistence."""

from __future__ import annotations

import json
import logging

from regitel.models.state import ResearchState
from regitel.utils.json_parse import parse_model_json
from regitel.utils.prompts import VALIDATOR_PROMPT, VALIDATOR_SYSTEM
from regitel.utils.usage import usage_from_message

logger = logging.getLogger(__name__)


def _safe_parse_json(text: str):
    parsed = parse_model_json(text, logger=logger, context="Validator")
    if parsed is not None:
        return parsed
    return {"passed": False, "issues": [{"severity": "error",
            "message": "Validator produced unparseable output"}],
            "approved_findings": [], "rejected_findings": []}


def validate_node(state: ResearchState, *, llm, db_manager) -> dict:
    """Validate structured findings for quality, grounding, and consistency."""
    findings = state.get("structured_findings", [])

    if not findings:
        logger.info("No findings to validate — passing trivially")
        return {
            "validation_result": {
                "passed": True,
                "overall_confidence": 1.0,
                "issues": [],
                "approved_findings": [],
                "rejected_findings": [],
            },
            "validation_passed": True,
        }

    # ---- Rule-based pre-checks (fast, no LLM) ----
    pre_issues = []
    for f in findings:
        rid = f.get("regulation_id", "UNKNOWN")

        if not f.get("url"):
            pre_issues.append({
                "regulation_id": rid,
                "severity": "error",
                "field": "url",
                "message": "Missing source URL — every finding must be grounded",
                "suggestion": "Re-search to find the official URL",
            })

        if not f.get("name"):
            pre_issues.append({
                "regulation_id": rid,
                "severity": "error",
                "field": "name",
                "message": "Missing regulation name",
                "suggestion": "Extract the official name from the source",
            })

        if not f.get("jurisdiction_id"):
            pre_issues.append({
                "regulation_id": rid,
                "severity": "error",
                "field": "jurisdiction_id",
                "message": "Missing jurisdiction_id",
                "suggestion": "Set jurisdiction_id to match the research target",
            })

        # Check ai_governance_requirements exist and have valid types
        reqs = f.get("ai_governance_requirements", [])
        for i, req in enumerate(reqs):
            if not req.get("requirement_type"):
                pre_issues.append({
                    "regulation_id": rid,
                    "severity": "error",
                    "field": f"ai_governance_requirements[{i}].requirement_type",
                    "message": "Missing requirement_type",
                    "suggestion": "Classify as model_risk_management, data_residency, ai_inventory, explainability, third_party_risk, etc.",
                })

        # Check ai_specific is set (critical distinction)
        if "ai_specific" not in f:
            pre_issues.append({
                "regulation_id": rid,
                "severity": "warning",
                "field": "ai_specific",
                "message": "Missing ai_specific flag — is this genuinely AI-specific or existing rules applied to AI?",
                "suggestion": "Set ai_specific=true only for regulations created specifically for AI (e.g., EU AI Act, FINMA 08/2024). Most should be false.",
            })

    # If there are critical pre-check failures, fail fast
    error_count = sum(1 for i in pre_issues if i["severity"] == "error")
    if error_count > len(findings) * 0.5:
        logger.warning(f"Pre-check found {error_count} errors — failing fast")
        all_ids = [f.get("regulation_id", "UNKNOWN") for f in findings]
        return {
            "validation_result": {
                "passed": False,
                "overall_confidence": 0.3,
                "issues": pre_issues,
                "approved_findings": [],
                "rejected_findings": all_ids,
            },
            "validation_passed": False,
        }

    # ---- LLM-based validation (deeper checks) ----
    session = db_manager.get_session()
    try:
        # Get existing regulations for consistency check
        all_jids = set(f.get("jurisdiction_id", "") for f in findings)
        existing_by_jid = {}
        for jid in all_jids:
            regs = db_manager.get_regulations_by_jurisdiction(session, jid)
            existing_by_jid[jid] = "\n".join(
                f"  - {r.name} ({r.short_name or 'N/A'}) [id={r.id}, ai_specific={r.ai_specific}]"
                for r in regs
            ) or "  (none)"

        existing_str = "\n".join(
            f"{jid}:\n{regs}" for jid, regs in existing_by_jid.items()
        )

        prompt = VALIDATOR_PROMPT.format(
            jurisdiction_id=", ".join(all_jids),
            findings_count=len(findings),
            findings_json=json.dumps(findings, indent=2, default=str),
            existing_regulations=existing_str,
        )

        # Retry with backoff for transient connection errors
        import time
        response = None
        for attempt in range(3):
            try:
                response = llm.invoke([
                    {"role": "system", "content": VALIDATOR_SYSTEM},
                    {"role": "user", "content": prompt},
                ])
                break
            except Exception as e:
                logger.warning(f"Validator LLM call failed (attempt {attempt+1}/3): {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    logger.error("Validator LLM failed after 3 attempts — approving with pre-check only")
                    all_ids = [f.get("regulation_id", "UNKNOWN") for f in findings]
                    return {
                        "validation_result": {
                            "passed": len(pre_issues) == 0 or all(i["severity"] != "error" for i in pre_issues),
                            "overall_confidence": 0.5,
                            "issues": pre_issues,
                            "approved_findings": all_ids,
                            "rejected_findings": [],
                        },
                        "validation_passed": True,
                    }

        result = _safe_parse_json(response.content)

        # Merge pre-check issues with LLM issues
        all_issues = pre_issues + result.get("issues", [])
        result["issues"] = all_issues

        # Recalculate pass/fail with merged issues
        errors = sum(1 for i in all_issues if i.get("severity") == "error")
        result["passed"] = errors == 0

        logger.info(f"Validation {'PASSED' if result['passed'] else 'FAILED'} — "
                     f"{len(all_issues)} issues ({errors} errors)")

        return {
            "validation_result": result,
            "validation_passed": result["passed"],
            "token_usage": usage_from_message(response),
        }
    finally:
        session.close()
