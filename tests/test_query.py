"""Tests for query engine and export."""

import json

import pytest

from regitel.storage.database import (
    AIGovernanceRequirementRow,
    AIControlFrameworkRow,
    DatabaseManager,
    RegulationRow,
)
from regitel.query.engine import QueryEngine
from regitel.query.export import export_json, export_csv, export_summary


@pytest.fixture
def populated_db(tmp_path):
    """Database with regulations and requirements for testing queries."""
    db_path = tmp_path / "test.db"
    mgr = DatabaseManager(db_path)
    mgr.init_db()

    session = mgr.get_session()
    try:
        # Jurisdictions
        mgr.upsert_jurisdiction(session, id="eu", name="European Union", region="eu", research_priority=1)
        mgr.upsert_jurisdiction(session, id="singapore", name="Singapore", region="apac", research_priority=1)
        session.commit()

        # Regulations
        reg1 = RegulationRow(
            id="eu-dora", jurisdiction_id="eu", name="DORA",
            short_name="DORA", issuing_body="EU Parliament",
            regulation_type="law", status="active", confidence_score=0.97,
            ai_specific=False,
            url="https://example.com/dora",
        )
        reg2 = RegulationRow(
            id="sg-trm", jurisdiction_id="singapore", name="TRM Guidelines",
            short_name="TRM", issuing_body="MAS",
            regulation_type="guideline", status="active", confidence_score=0.95,
            ai_specific=True,
            governance_themes=json.dumps(["generative_ai", "model_risk_management"]),
        )
        session.add_all([reg1, reg2])
        session.flush()

        # AI Governance Requirements
        req1 = AIGovernanceRequirementRow(
            id="req-1", regulation_id="eu-dora",
            requirement_type="security_controls",
            governance_scope='["ict_resilience"]',
            entity_types='["bank", "insurer"]',
            risk_tier="high_risk",
            mandatory=True,
            applicable_to_deployers=True,
            key_controls=json.dumps(["encryption", "access_control"]),
        )
        req2 = AIGovernanceRequirementRow(
            id="req-2", regulation_id="sg-trm",
            requirement_type="model_risk_management",
            governance_scope='["credit_underwriting", "risk_modeling"]',
            entity_types='["all"]',
            risk_tier="high_risk",
            mandatory=True,
            applicable_to_deployers=True,
        )
        session.add_all([req1, req2])

        # AI Control Framework
        fw = AIControlFrameworkRow(
            id="fw-1", regulation_id="eu-dora",
            framework_name="ICT Resilience Framework",
            control_categories=json.dumps(["risk_classification", "incident_response"]),
            risk_tiers='[]',
            inventory_required=False,
            binding=True,
        )
        session.add(fw)
        session.commit()
    finally:
        session.close()

    return mgr


class TestQueryEngine:
    def test_search_all(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session)
            assert result.result_count == 2
        finally:
            session.close()

    def test_search_by_jurisdiction(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session, jurisdiction="eu")
            assert result.result_count == 1
            assert result.regulations[0].id == "eu-dora"
        finally:
            session.close()

    def test_search_by_region(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session, region="apac")
            assert result.result_count == 1
            assert result.regulations[0].jurisdiction_id == "singapore"
        finally:
            session.close()

    def test_search_by_text(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session, text="DORA")
            assert result.result_count == 1
        finally:
            session.close()

    def test_search_by_requirement_type(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session, requirement_type="security_controls")
            assert result.result_count == 1
            assert result.regulations[0].id == "eu-dora"
        finally:
            session.close()

    def test_search_ai_specific_only(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session, ai_specific_only=True)
            assert result.result_count == 1
            assert result.regulations[0].id == "sg-trm"
        finally:
            session.close()

    def test_compare_jurisdictions(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.compare_jurisdictions(session, ["eu", "singapore"])
            assert "eu" in result
            assert "singapore" in result
            assert len(result["eu"]) == 1
        finally:
            session.close()

    def test_framework_summary(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.framework_summary(session)
            assert len(result) == 1  # Only eu has a framework
            assert result[0]["ai_specific"] is False
        finally:
            session.close()

    def test_governance_matrix(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.governance_matrix(session)
            assert len(result) == 2
            types = {r["requirement_type"] for r in result}
            assert "security_controls" in types
            assert "model_risk_management" in types
        finally:
            session.close()


class TestExport:
    def test_export_json(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session)
            text = export_json(result)
            data = json.loads(text)
            assert data["result_count"] == 2
            assert len(data["regulations"]) == 2
        finally:
            session.close()

    def test_export_json_to_file(self, populated_db, tmp_path):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session)
            out = tmp_path / "export.json"
            export_json(result, output_path=out)
            assert out.exists()
            data = json.loads(out.read_text())
            assert data["result_count"] == 2
        finally:
            session.close()

    def test_export_csv(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session)
            text = export_csv(result)
            lines = text.strip().split("\n")
            assert len(lines) >= 3  # header + 2 reqs
            assert "jurisdiction_id" in lines[0]
        finally:
            session.close()

    def test_export_summary(self, populated_db):
        engine = QueryEngine(populated_db)
        session = populated_db.get_session()
        try:
            result = engine.search(session)
            text = export_summary(result)
            assert "European Union" in text
            assert "Singapore" in text
            assert "DORA" in text
        finally:
            session.close()
