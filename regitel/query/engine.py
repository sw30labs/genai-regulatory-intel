"""Query engine — structured search + natural-language query over the regulation DB.

Domain: Generative AI / Agentic AI governance for Tier 1 banks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from regitel.storage.database import (
    AIGovernanceRequirementRow,
    AIControlFrameworkRow,
    DatabaseManager,
    JurisdictionRow,
    RegulationRow,
)


# ---------------------------------------------------------------------------
# Query result types
# ---------------------------------------------------------------------------

@dataclass
class RegulationResult:
    """A regulation with its AI governance requirements and control frameworks."""
    id: str
    jurisdiction_id: str
    jurisdiction_name: str
    name: str
    short_name: Optional[str]
    issuing_body: Optional[str]
    regulation_type: str
    status: str
    effective_date: Optional[str]
    version: Optional[str]
    url: Optional[str]
    confidence_score: float
    ai_specific: bool = False
    governance_themes: list[str] = field(default_factory=list)
    ai_governance_requirements: list[dict] = field(default_factory=list)
    ai_control_frameworks: list[dict] = field(default_factory=list)


@dataclass
class QueryResult:
    """Result of a structured or NL query."""
    query: str
    result_count: int
    regulations: list[RegulationResult] = field(default_factory=list)
    summary: Optional[str] = None


# ---------------------------------------------------------------------------
# Row → dict helpers
# ---------------------------------------------------------------------------

def _req_to_dict(r: AIGovernanceRequirementRow) -> dict:
    return {
        "id": r.id,
        "requirement_type": r.requirement_type,
        "governance_scope": json.loads(r.governance_scope) if r.governance_scope else [],
        "entity_types": json.loads(r.entity_types) if r.entity_types else [],
        "risk_tier": r.risk_tier,
        "mandatory": r.mandatory,
        "applicable_to_deployers": r.applicable_to_deployers,
        "applicable_to_providers": r.applicable_to_providers,
        "key_controls": json.loads(r.key_controls) if r.key_controls else [],
        "penalties": r.penalties,
        "effective_date": r.effective_date.isoformat() if r.effective_date else None,
        "notes": r.notes,
    }


def _fw_to_dict(t: AIControlFrameworkRow) -> dict:
    return {
        "id": t.id,
        "framework_name": t.framework_name,
        "control_categories": json.loads(t.control_categories) if t.control_categories else [],
        "risk_tiers": json.loads(t.risk_tiers) if t.risk_tiers else [],
        "inventory_required": t.inventory_required,
        "explainability_required": t.explainability_required,
        "human_overview_required": t.human_overview_required,
        "data_governance_required": t.data_governance_required,
        "third_party_assessment": t.third_party_assessment,
        "binding": t.binding,
    }


def _reg_to_result(reg: RegulationRow, jname: str) -> RegulationResult:
    themes = json.loads(reg.governance_themes) if reg.governance_themes else []
    return RegulationResult(
        id=reg.id,
        jurisdiction_id=reg.jurisdiction_id,
        jurisdiction_name=jname,
        name=reg.name,
        short_name=reg.short_name,
        issuing_body=reg.issuing_body,
        regulation_type=reg.regulation_type,
        status=reg.status,
        effective_date=reg.effective_date.isoformat() if reg.effective_date else None,
        version=reg.version,
        url=reg.url,
        confidence_score=reg.confidence_score or 0.0,
        ai_specific=reg.ai_specific,
        governance_themes=themes,
        ai_governance_requirements=[_req_to_dict(r) for r in reg.ai_governance_requirements],
        ai_control_frameworks=[_fw_to_dict(t) for t in reg.ai_control_frameworks],
    )


# ---------------------------------------------------------------------------
# Query engine
# ---------------------------------------------------------------------------

class QueryEngine:
    """Structured query engine over the RegIntel database."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    # -- cached jurisdiction name map --
    def _jurisdiction_names(self, session: Session) -> dict[str, str]:
        rows = session.query(JurisdictionRow.id, JurisdictionRow.name).all()
        return {r.id: r.name for r in rows}

    # -- Core search --
    def search(
        self,
        session: Session,
        *,
        text: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        region: Optional[str] = None,
        requirement_type: Optional[str] = None,
        governance_theme: Optional[str] = None,
        entity_type: Optional[str] = None,
        ai_specific_only: bool = False,
        applied_only: bool = False,
        mandatory_only: bool = False,
        min_confidence: float = 0.0,
    ) -> QueryResult:
        """Run a structured search across regulations and AI governance requirements."""

        jnames = self._jurisdiction_names(session)
        q = session.query(RegulationRow)

        # -- jurisdiction / region filters --
        if jurisdiction:
            q = q.filter(RegulationRow.jurisdiction_id == jurisdiction)
        if region:
            jids = [
                row[0] for row in
                session.query(JurisdictionRow.id)
                .filter(JurisdictionRow.region == region)
                .all()
            ]
            q = q.filter(RegulationRow.jurisdiction_id.in_(jids))

        # -- text search (name, short_name, issuing_body) --
        if text:
            pattern = f"%{text}%"
            q = q.filter(or_(
                RegulationRow.name.ilike(pattern),
                RegulationRow.short_name.ilike(pattern),
                RegulationRow.issuing_body.ilike(pattern),
                RegulationRow.id.ilike(pattern),
            ))

        # -- ai_specific filter --
        if ai_specific_only:
            q = q.filter(RegulationRow.ai_specific.is_(True))
        if applied_only:
            q = q.filter(RegulationRow.ai_specific.is_(False))

        # -- governance theme filter --
        if governance_theme:
            q = q.filter(RegulationRow.governance_themes.like(f"%{governance_theme}%"))

        # -- confidence floor --
        if min_confidence > 0:
            q = q.filter(RegulationRow.confidence_score >= min_confidence)

        # -- active only by default --
        q = q.filter(RegulationRow.status == "active")
        q = q.order_by(RegulationRow.jurisdiction_id, RegulationRow.name)

        regulations = q.all()

        # -- post-filter on requirement attributes --
        results: list[RegulationResult] = []
        for reg in regulations:
            reqs = reg.ai_governance_requirements
            fws = reg.ai_control_frameworks

            # filter requirements
            if requirement_type:
                reqs = [r for r in reqs if r.requirement_type == requirement_type]
            if entity_type:
                reqs = [
                    r for r in reqs
                    if entity_type in (json.loads(r.entity_types) if r.entity_types else [])
                    or "all" in (json.loads(r.entity_types) if r.entity_types else [])
                ]
            if mandatory_only:
                reqs = [r for r in reqs if r.mandatory]

            if (requirement_type or entity_type or mandatory_only) and not reqs and not fws:
                continue

            rr = _reg_to_result(reg, jnames.get(reg.jurisdiction_id, reg.jurisdiction_id))
            if requirement_type or entity_type or mandatory_only:
                rr.ai_governance_requirements = [_req_to_dict(r) for r in reqs]
            results.append(rr)

        query_desc = self._describe_query(
            text=text, jurisdiction=jurisdiction, region=region,
            requirement_type=requirement_type, entity_type=entity_type,
            ai_specific_only=ai_specific_only, applied_only=applied_only,
            governance_theme=governance_theme, mandatory_only=mandatory_only,
        )
        return QueryResult(
            query=query_desc,
            result_count=len(results),
            regulations=results,
        )

    # -- Convenience: compare jurisdictions --
    def compare_jurisdictions(
        self,
        session: Session,
        jurisdiction_ids: list[str],
    ) -> dict[str, list[RegulationResult]]:
        """Return regulations grouped by jurisdiction for comparison."""
        jnames = self._jurisdiction_names(session)
        result: dict[str, list[RegulationResult]] = {}
        for jid in jurisdiction_ids:
            regs = (
                session.query(RegulationRow)
                .filter(RegulationRow.jurisdiction_id == jid, RegulationRow.status == "active")
                .order_by(RegulationRow.name)
                .all()
            )
            result[jid] = [_reg_to_result(r, jnames.get(jid, jid)) for r in regs]
        return result

    # -- Convenience: governance comparison matrix --
    def governance_matrix(self, session: Session) -> list[dict]:
        """Return a comparison matrix of AI governance attributes across jurisdictions."""
        jnames = self._jurisdiction_names(session)
        rows = (
            session.query(AIGovernanceRequirementRow, RegulationRow)
            .join(RegulationRow, AIGovernanceRequirementRow.regulation_id == RegulationRow.id)
            .filter(RegulationRow.status == "active")
            .order_by(RegulationRow.jurisdiction_id, AIGovernanceRequirementRow.requirement_type)
            .all()
        )
        return [
            {
                "jurisdiction_id": reg.jurisdiction_id,
                "jurisdiction_name": jnames.get(reg.jurisdiction_id, reg.jurisdiction_id),
                "regulation": reg.short_name or reg.name,
                "ai_specific": reg.ai_specific,
                "requirement_type": req.requirement_type,
                "mandatory": req.mandatory,
                "applicable_to_deployers": req.applicable_to_deployers,
                "applicable_to_providers": req.applicable_to_providers,
                "key_controls": json.loads(req.key_controls) if req.key_controls else [],
                "risk_tier": req.risk_tier,
            }
            for req, reg in rows
        ]

    # -- Convenience: framework summary --
    def framework_summary(self, session: Session) -> list[dict]:
        """Return a summary of all AI control frameworks across jurisdictions."""
        jnames = self._jurisdiction_names(session)
        rows = (
            session.query(AIControlFrameworkRow, RegulationRow)
            .join(RegulationRow, AIControlFrameworkRow.regulation_id == RegulationRow.id)
            .filter(RegulationRow.status == "active")
            .order_by(RegulationRow.jurisdiction_id)
            .all()
        )
        results = []
        for fw, reg in rows:
            results.append({
                "jurisdiction_id": reg.jurisdiction_id,
                "jurisdiction_name": jnames.get(reg.jurisdiction_id, reg.jurisdiction_id),
                "regulation": reg.short_name or reg.name,
                "ai_specific": reg.ai_specific,
                **_fw_to_dict(fw),
            })
        return results

    # -- Query description --
    @staticmethod
    def _describe_query(**kwargs) -> str:
        parts = []
        for k, v in kwargs.items():
            if v and v is not False:
                parts.append(f"{k}={v}")
        return ", ".join(parts) if parts else "all regulations"
