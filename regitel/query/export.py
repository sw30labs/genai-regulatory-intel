"""Export module — serialize regulation data to JSON, CSV, and summary formats.

Domain: Generative AI / Agentic AI governance for Tier 1 banks.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from regitel.query.engine import QueryResult, RegulationResult


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(
    result: QueryResult,
    output_path: Optional[Path] = None,
    indent: int = 2,
) -> str:
    """Export query results to JSON. Returns the JSON string."""
    payload = {
        "exported_at": datetime.utcnow().isoformat(),
        "query": result.query,
        "result_count": result.result_count,
        "regulations": [asdict(r) for r in result.regulations],
    }
    text = json.dumps(payload, indent=indent, default=str)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)
    return text


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_csv(
    result: QueryResult,
    output_path: Optional[Path] = None,
) -> str:
    """Export query results to CSV (one row per AI governance requirement). Returns CSV string."""
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header
    writer.writerow([
        "jurisdiction_id",
        "jurisdiction_name",
        "regulation_id",
        "regulation_name",
        "short_name",
        "issuing_body",
        "regulation_type",
        "status",
        "effective_date",
        "url",
        "confidence",
        "ai_specific",
        "governance_themes",
        "requirement_type",
        "governance_scope",
        "entity_types",
        "risk_tier",
        "mandatory",
        "applicable_to_deployers",
        "applicable_to_providers",
        "key_controls",
        "penalties",
        "framework",
        "framework_binding",
    ])

    for reg in result.regulations:
        # Base reg fields
        base = [
            reg.jurisdiction_id,
            reg.jurisdiction_name,
            reg.id,
            reg.name,
            reg.short_name or "",
            reg.issuing_body or "",
            reg.regulation_type,
            reg.status,
            reg.effective_date or "",
            reg.url or "",
            f"{reg.confidence_score:.2f}",
            str(reg.ai_specific),
            "; ".join(reg.governance_themes) if reg.governance_themes else "",
        ]

        if reg.ai_governance_requirements:
            for req in reg.ai_governance_requirements:
                writer.writerow(base + [
                    req.get("requirement_type", ""),
                    "; ".join(req.get("governance_scope", [])),
                    "; ".join(req.get("entity_types", [])),
                    req.get("risk_tier", ""),
                    str(req.get("mandatory", "")),
                    str(req.get("applicable_to_deployers", "")),
                    str(req.get("applicable_to_providers", "")),
                    "; ".join(req.get("key_controls", [])),
                    req.get("penalties", "") or "",
                    "",  # framework
                    "",  # framework_binding
                ])
        elif reg.ai_control_frameworks:
            for fw in reg.ai_control_frameworks:
                writer.writerow(base + [
                    "",  # requirement_type
                    "",  # governance_scope
                    "",  # entity_types
                    "",  # risk_tier
                    "",  # mandatory
                    "",  # deployers
                    "",  # providers
                    "",  # key_controls
                    "",  # penalties
                    fw.get("framework_name", ""),
                    str(fw.get("binding", "")),
                ])
        else:
            # Regulation with no requirements — still include it
            writer.writerow(base + [""] * 11)

    text = buf.getvalue()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)
    return text


# ---------------------------------------------------------------------------
# Summary text export (for terminal / reports)
# ---------------------------------------------------------------------------

def export_summary(result: QueryResult) -> str:
    """Generate a human-readable text summary of query results."""
    lines: list[str] = []
    lines.append(f"Query: {result.query}")
    lines.append(f"Results: {result.result_count} regulations\n")

    # Group by jurisdiction
    by_jur: dict[str, list[RegulationResult]] = {}
    for reg in result.regulations:
        by_jur.setdefault(reg.jurisdiction_name, []).append(reg)

    for jname, regs in sorted(by_jur.items()):
        lines.append(f"=== {jname} ({len(regs)} regulations) ===")
        for reg in regs:
            ai_tag = " [AI-SPECIFIC]" if reg.ai_specific else ""
            lines.append(f"  {reg.short_name or reg.name}{ai_tag}")
            lines.append(f"    Type: {reg.regulation_type} | Status: {reg.status} | Confidence: {reg.confidence_score:.0%}")
            if reg.issuing_body:
                lines.append(f"    Issuer: {reg.issuing_body}")
            if reg.url:
                lines.append(f"    URL: {reg.url}")
            if reg.governance_themes:
                lines.append(f"    Themes: {', '.join(reg.governance_themes)}")

            for req in reg.ai_governance_requirements:
                rtype = req.get("requirement_type", "?")
                mand = "mandatory" if req.get("mandatory") else "recommended"
                deployers = "deployers" if req.get("applicable_to_deployers") else ""
                providers = "providers" if req.get("applicable_to_providers") else ""
                audience = ", ".join(filter(None, [deployers, providers])) or "all"
                lines.append(f"    -> [{rtype}] {mand}, applies to {audience}")
                if req.get("risk_tier"):
                    lines.append(f"       Risk tier: {req['risk_tier']}")
                scope = ", ".join(req.get("governance_scope", []))
                if scope:
                    lines.append(f"       Scope: {scope}")
                entities = ", ".join(req.get("entity_types", []))
                if entities:
                    lines.append(f"       Entities: {entities}")
                controls = ", ".join(req.get("key_controls", []))
                if controls:
                    lines.append(f"       Controls: {controls}")
                if req.get("penalties"):
                    lines.append(f"       Penalties: {req['penalties']}")
                if req.get("notes"):
                    note = req["notes"][:120] + ("..." if len(req["notes"]) > 120 else "")
                    lines.append(f"       Note: {note}")

            for fw in reg.ai_control_frameworks:
                binding = "binding" if fw.get("binding") else "voluntary"
                lines.append(f"    -> [FRAMEWORK] {fw.get('framework_name', '?')} ({binding})")
                if fw.get("inventory_required"):
                    lines.append("       AI inventory: required")
                if fw.get("explainability_required"):
                    lines.append("       Explainability: required")
                if fw.get("human_overview_required"):
                    lines.append("       Human oversight: required")
                if fw.get("third_party_assessment"):
                    lines.append("       Third-party assessment: required")

        lines.append("")

    return "\n".join(lines)
