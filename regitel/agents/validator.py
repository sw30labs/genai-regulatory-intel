"""Validator Agent — quality-checks research findings before persistence."""

from __future__ import annotations

import json
import logging

from regitel.models.state import ResearchState
from regitel.utils.json_parse import parse_model_json
from regitel.utils.llm_errors import LLMProviderError, is_insufficient_quota_error
from regitel.utils.prompts import VALIDATOR_PROMPT, VALIDATOR_SYSTEM
from regitel.utils.usage import merge_usage, usage_from_message

logger = logging.getLogger(__name__)


def _safe_parse_json(text: str):
    parsed = parse_model_json(text, logger=logger, context="Validator")
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        issues = [item for item in parsed if isinstance(item, dict)]
        issues.append({
            "severity": "error",
            "message": "Validator produced incomplete non-object output",
            "suggestion": "Retry validation with a smaller findings batch or larger output budget",
        })
        return {
            "passed": False,
            "overall_confidence": 0.0,
            "issues": issues,
            "approved_findings": [],
            "rejected_findings": [],
        }
    return {"passed": False, "issues": [{"severity": "error",
            "message": "Validator produced unparseable output"}],
            "approved_findings": [], "rejected_findings": []}


def _chunks(items: list[dict], size: int) -> list[list[dict]]:
    """Split findings into non-empty validation batches."""
    size = max(1, size)
    return [items[i:i + size] for i in range(0, len(items), size)]


def _finding_ids(findings: list[dict]) -> list[str]:
    return [f.get("regulation_id", "UNKNOWN") for f in findings]


def _issue_dicts(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_validation_result(result: dict, findings: list[dict]) -> dict:
    """Make validator output complete and internally consistent."""
    ids = set(_finding_ids(findings))
    issues = _issue_dicts(result.get("issues", []))
    errors = [i for i in issues if i.get("severity") == "error"]

    approved = {
        rid for rid in result.get("approved_findings", [])
        if isinstance(rid, str) and rid in ids
    }
    rejected = {
        rid for rid in result.get("rejected_findings", [])
        if isinstance(rid, str) and rid in ids
    }

    for issue in errors:
        rid = issue.get("regulation_id")
        if isinstance(rid, str) and rid in ids:
            rejected.add(rid)

    # A blocking parser/shape error without a specific ID taints the whole batch.
    if any(not issue.get("regulation_id") for issue in errors):
        rejected.update(ids)

    if not approved:
        approved = ids - rejected
    else:
        approved -= rejected

    result["issues"] = issues
    result["approved_findings"] = sorted(approved)
    result["rejected_findings"] = sorted(rejected)
    result["passed"] = not errors
    result["overall_confidence"] = float(result.get("overall_confidence", 0.5) or 0.5)
    return result


def _run_llm_validation_batch(findings: list[dict], *, llm, db_manager, session) -> tuple[dict, dict]:
    """Run one validator call for a bounded set of findings."""
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

    import time
    response = None
    last_error = None
    for attempt in range(3):
        try:
            response = llm.invoke([
                {"role": "system", "content": VALIDATOR_SYSTEM},
                {"role": "user", "content": prompt},
            ])
            break
        except Exception as e:
            last_error = e
            if is_insufficient_quota_error(e):
                logger.error("Validator LLM provider quota exhausted: %s", e)
                raise LLMProviderError(
                    f"Validator LLM provider quota exhausted: {e}",
                    fatal=True,
                ) from e
            logger.warning(f"Validator LLM call failed (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                logger.error("Validator LLM failed after 3 attempts")
                raise LLMProviderError(
                    f"Validator LLM failed after 3 attempts: {last_error}",
                    fatal=False,
                ) from e

    result = _normalize_validation_result(_safe_parse_json(response.content), findings)
    return result, usage_from_message(response)


def _merge_validation_batches(batch_results: list[dict], pre_issues: list[dict]) -> dict:
    issues = list(pre_issues)
    approved: set[str] = set()
    rejected: set[str] = set()
    confidences = []

    for issue in pre_issues:
        if issue.get("severity") == "error" and issue.get("regulation_id"):
            rejected.add(issue["regulation_id"])

    for result in batch_results:
        issues.extend(_issue_dicts(result.get("issues", [])))
        approved.update(result.get("approved_findings", []))
        rejected.update(result.get("rejected_findings", []))
        confidences.append(float(result.get("overall_confidence", 0.5) or 0.5))

    approved -= rejected
    errors = sum(1 for issue in issues if issue.get("severity") == "error")
    confidence = sum(confidences) / len(confidences) if confidences else 1.0

    return {
        "passed": errors == 0,
        "overall_confidence": round(confidence, 3),
        "issues": issues,
        "approved_findings": sorted(approved),
        "rejected_findings": sorted(rejected),
    }


def validate_node(state: ResearchState, *, llm, db_manager, batch_size: int = 4) -> dict:
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

    # ---- LLM-based validation (deeper checks, batched to avoid truncation) ----
    session = db_manager.get_session()
    try:
        batch_results = []
        token_usage = {}
        batches = _chunks(findings, batch_size)
        logger.info(
            "Validating %d findings in %d batch(es) of up to %d",
            len(findings),
            len(batches),
            max(1, batch_size),
        )

        for batch in batches:
            result, usage = _run_llm_validation_batch(
                batch,
                llm=llm,
                db_manager=db_manager,
                session=session,
            )
            batch_results.append(result)
            token_usage = merge_usage(token_usage, usage)

        result = _merge_validation_batches(batch_results, pre_issues)
        errors = sum(1 for i in result["issues"] if i.get("severity") == "error")

        logger.info(f"Validation {'PASSED' if result['passed'] else 'FAILED'} — "
                     f"{len(result['issues'])} issues ({errors} errors)")

        return {
            "validation_result": result,
            "validation_passed": result["passed"],
            "token_usage": token_usage,
        }
    finally:
        session.close()
