"""Persister Agent — writes validated findings to the database with change logging."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from regitel.models.state import ResearchState
from regitel.storage.database import (
    AIGovernanceRequirementRow,
    AIControlFrameworkRow,
    ChangeLogRow,
    DatabaseManager,
    RegulationRow,
    ResearchRunRow,
)

logger = logging.getLogger(__name__)


def _gen_id() -> str:
    return str(uuid.uuid4())[:8]


def _detect_changes(existing: RegulationRow, new_data: dict) -> dict:
    """Compare existing regulation row with new data and return a dict of changes.

    Returns dict mapping field_name → {"old": old_value, "new": new_value}
    for fields that meaningfully differ.
    """
    TRACKED_FIELDS = [
        "name", "status", "regulation_type", "version",
        "effective_date", "issuing_body", "url", "confidence_score",
        "ai_specific", "governance_themes",
    ]
    changes = {}
    for field in TRACKED_FIELDS:
        old_val = getattr(existing, field, None)
        new_val = new_data.get(field)
        if new_val is None:
            continue
        # Normalize for comparison
        old_str = str(old_val) if old_val is not None else ""
        new_str = str(new_val) if new_val is not None else ""
        if old_str != new_str:
            changes[field] = {"old": old_str, "new": new_str}
    return changes


def persist_node(state: ResearchState, *, db_manager: DatabaseManager) -> dict:
    """Persist validated findings to the database and log changes."""
    findings = state.get("structured_findings", [])
    validation = state.get("validation_result", {})
    approved_ids = set(validation.get("approved_findings", []))
    run_id = state.get("research_run_id", _gen_id())
    confidence = state.get("confidence_score", 0.0)
    token_usage = state.get("token_usage", {})

    # If no explicit approval list, approve all (full auto-persist mode)
    if not approved_ids:
        approved_ids = {f.get("regulation_id") for f in findings if f.get("regulation_id")}

    session = db_manager.get_session()
    changes = []
    regs_found = 0
    regs_updated = 0

    try:
        for finding in findings:
            rid = finding.get("regulation_id")
            if not rid:
                continue
            if rid not in approved_ids:
                logger.debug(f"Skipping non-approved finding: {rid}")
                continue

            # Check if regulation already exists
            existing = session.get(RegulationRow, rid)
            is_new = existing is None

            # Upsert regulation
            reg_data = {
                "id": rid,
                "jurisdiction_id": finding.get("jurisdiction_id", "unknown"),
                "name": finding.get("name", "Unknown Regulation"),
                "short_name": finding.get("short_name"),
                "issuing_body": finding.get("issuing_body"),
                "regulation_type": finding.get("regulation_type", "guideline"),
                "status": finding.get("status", "active"),
                "effective_date": _parse_date(finding.get("effective_date")),
                "version": finding.get("version"),
                "url": finding.get("url"),
                "last_checked_at": datetime.utcnow(),
                "last_updated_at": datetime.utcnow(),
                "confidence_score": finding.get("confidence_score", confidence),
                "ai_specific": finding.get("ai_specific", False),
                "governance_themes": json.dumps(finding.get("governance_themes", [])),
            }

            if existing:
                # Detect meaningful changes for the changelog
                field_changes = _detect_changes(existing, reg_data)

                for k, v in reg_data.items():
                    if v is not None:
                        setattr(existing, k, v)
                regs_updated += 1
            else:
                reg_data["created_at"] = datetime.utcnow()
                row = RegulationRow(**reg_data)
                session.add(row)
                regs_found += 1

            # Upsert AI governance requirements
            for req in finding.get("ai_governance_requirements", []):
                req_id = f"{rid}-{req.get('requirement_type', 'gen')}-{_gen_id()}"
                req_row = AIGovernanceRequirementRow(
                    id=req_id,
                    regulation_id=rid,
                    requirement_type=req.get("requirement_type", "general"),
                    governance_scope=json.dumps(req.get("governance_scope", [])),
                    entity_types=json.dumps(req.get("entity_types", [])),
                    risk_tier=req.get("risk_tier"),
                    mandatory=req.get("mandatory", True),
                    applicable_to_deployers=req.get("applicable_to_deployers", True),
                    applicable_to_providers=req.get("applicable_to_providers", False),
                    key_controls=json.dumps(req.get("key_controls", [])),
                    penalties=req.get("penalties"),
                    effective_date=_parse_date(req.get("effective_date")),
                    notes=req.get("notes"),
                )
                session.add(req_row)

            # Upsert AI control framework if present
            framework = finding.get("ai_control_framework")
            if framework and isinstance(framework, dict) and framework.get("framework_name"):
                fw_id = f"{rid}-fw-{_gen_id()}"
                fw_row = AIControlFrameworkRow(
                    id=fw_id,
                    regulation_id=rid,
                    framework_name=framework["framework_name"],
                    control_categories=json.dumps(framework.get("control_categories", [])),
                    risk_tiers=json.dumps(framework.get("risk_tiers", [])),
                    inventory_required=framework.get("inventory_required", False),
                    explainability_required=framework.get("explainability_required", False),
                    human_overview_required=framework.get("human_overview_required", False),
                    data_governance_required=framework.get("data_governance_required", False),
                    third_party_assessment=framework.get("third_party_assessment", False),
                    binding=framework.get("binding", True),
                )
                session.add(fw_row)

            # Log the change with diff details
            if is_new:
                change_type = "new"
                summary = f"Discovered: {finding.get('name', rid)}"
                details_dict = {
                    "source": finding.get("url"),
                    "confidence": finding.get("confidence_score"),
                    "ai_specific": finding.get("ai_specific", False),
                    "governance_requirements": len(finding.get("ai_governance_requirements", [])),
                }
            else:
                # Classify the update type based on what changed
                if field_changes:
                    if "status" in field_changes and field_changes["status"]["new"] == "superseded":
                        change_type = "superseded"
                        summary = f"Superseded: {finding.get('name', rid)}"
                    elif "status" in field_changes and field_changes["status"]["new"] == "revoked":
                        change_type = "revoked"
                        summary = f"Revoked: {finding.get('name', rid)}"
                    elif "version" in field_changes:
                        change_type = "updated"
                        old_v = field_changes["version"]["old"] or "unknown"
                        new_v = field_changes["version"]["new"] or "unknown"
                        summary = f"Version change: {finding.get('name', rid)} ({old_v} → {new_v})"
                    else:
                        change_type = "updated"
                        changed_fields = list(field_changes.keys())
                        summary = f"Updated {', '.join(changed_fields[:3])}: {finding.get('name', rid)}"
                    details_dict = {
                        "source": finding.get("url"),
                        "confidence": finding.get("confidence_score"),
                        "field_changes": field_changes,
                    }
                else:
                    change_type = "updated"
                    summary = f"Re-confirmed: {finding.get('name', rid)}"
                    details_dict = {
                        "source": finding.get("url"),
                        "confidence": finding.get("confidence_score"),
                        "no_changes": True,
                    }

            change = ChangeLogRow(
                id=_gen_id(),
                regulation_id=rid,
                change_type=change_type,
                summary=summary,
                details=json.dumps(details_dict),
                source_url=finding.get("url"),
            )
            session.add(change)
            changes.append({
                "regulation_id": rid,
                "change_type": change.change_type,
                "summary": change.summary,
            })

        # Update jurisdiction last_researched_at
        jids = set(f.get("jurisdiction_id") for f in findings if f.get("jurisdiction_id"))
        for jid in jids:
            from regitel.storage.database import JurisdictionRow
            j = session.get(JurisdictionRow, jid)
            if j:
                j.last_researched_at = datetime.utcnow()

        # Record the research run
        run_row = ResearchRunRow(
            id=run_id,
            completed_at=datetime.utcnow(),
            jurisdictions_scanned=json.dumps(list(jids)),
            status="completed",
            regulations_found=regs_found,
            regulations_updated=regs_updated,
            reflection_iterations=state.get("iteration_count", 0),
            confidence_score=validation.get("overall_confidence", 0.0),
            input_tokens=int(token_usage.get("input_tokens", 0) or 0),
            output_tokens=int(token_usage.get("output_tokens", 0) or 0),
            total_tokens=int(token_usage.get("total_tokens", 0) or 0),
            cached_input_tokens=int(token_usage.get("cached_input_tokens", 0) or 0),
            reasoning_tokens=int(token_usage.get("reasoning_tokens", 0) or 0),
            llm_calls=int(token_usage.get("llm_calls", 0) or 0),
            web_search_calls=int(token_usage.get("web_search_calls", 0) or 0),
        )
        session.add(run_row)

        session.commit()
        logger.info(f"Persisted {regs_found} new + {regs_updated} updated regulations, "
                     f"{len(changes)} changelog entries")

    except Exception as e:
        session.rollback()
        logger.error(f"Persist failed: {e}")
        return {
            "changes_detected": changes,
            "error": str(e),
        }
    finally:
        session.close()

    return {
        "changes_detected": changes,
        "confidence_score": validation.get("overall_confidence", 0.0),
    }


def _parse_date(value):
    """Parse a date string to a Python date object, or return None."""
    if not value or value == "null":
        return None
    try:
        from datetime import date
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None
