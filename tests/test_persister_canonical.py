"""Tests for canonical matching before persistence."""

import json

import pytest

from regitel.agents.persister import persist_node
from regitel.storage.database import (
    AIGovernanceRequirementRow,
    ChangeLogRow,
    JurisdictionRow,
    RegulationRow,
    ResearchRunRow,
)


@pytest.fixture
def db_manager(tmp_path):
    from regitel.storage.database import DatabaseManager

    mgr = DatabaseManager(tmp_path / "test.db")
    mgr.init_db()
    return mgr


def _seed_eu(session):
    session.add(JurisdictionRow(id="eu", name="European Union", region="eu"))
    session.commit()


def _finding(regulation_id: str, name: str, url: str | None = None) -> dict:
    return {
        "regulation_id": regulation_id,
        "jurisdiction_id": "eu",
        "name": name,
        "short_name": "EU AI Act",
        "issuing_body": "European Parliament and Council",
        "regulation_type": "law",
        "status": "active",
        "url": url,
        "confidence_score": 0.9,
        "ai_specific": True,
        "governance_themes": ["transparency"],
        "ai_governance_requirements": [{
            "requirement_type": "transparency_disclosure",
            "governance_scope": ["all"],
            "entity_types": ["bank"],
            "mandatory": True,
            "key_controls": [regulation_id],
            "notes": f"requirement from {regulation_id}",
        }],
    }


def test_persist_merges_same_batch_to_stable_id(db_manager):
    session = db_manager.get_session()
    try:
        _seed_eu(session)
    finally:
        session.close()

    state = {
        "research_run_id": "run-1",
        "structured_findings": [
            _finding(
                "eu-ai-act",
                "Regulation (EU) 2024/1689 laying down harmonised rules on artificial intelligence",
                "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
            ),
            _finding(
                "eu-ai-act-art-50",
                "Regulation (EU) 2024/1689",
                "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai",
            ),
        ],
        "validation_result": {"overall_confidence": 0.9},
        "token_usage": {},
    }

    result = persist_node(state, db_manager=db_manager)

    session = db_manager.get_session()
    try:
        regs = session.query(RegulationRow).all()
        assert "error" not in result
        assert [reg.id for reg in regs] == ["eu-reg-2024-1689"]
        assert session.query(AIGovernanceRequirementRow).count() == 2
        assert session.query(ChangeLogRow).count() == 1
        run = session.get(ResearchRunRow, "run-1")
        assert run.regulations_found == 1
        assert json.loads(run.jurisdictions_scanned) == ["eu"]
    finally:
        session.close()


def test_persist_matches_existing_by_canonical_identity(db_manager):
    session = db_manager.get_session()
    try:
        _seed_eu(session)
        session.add(RegulationRow(
            id="eu-dora-ict-third-party",
            jurisdiction_id="eu",
            name="Regulation (EU) 2022/2554 on digital operational resilience",
            short_name="DORA",
            url="https://eur-lex.europa.eu/eli/reg/2022/2554/oj/eng",
            confidence_score=0.95,
            ai_specific=False,
        ))
        session.commit()
    finally:
        session.close()

    state = {
        "research_run_id": "run-2",
        "structured_findings": [{
            "regulation_id": "eu-dora",
            "jurisdiction_id": "eu",
            "name": "Regulation (EU) 2022/2554 on digital operational resilience",
            "short_name": "DORA",
            "url": "https://www.esma.europa.eu/digital-operational-resilience-act-dora",
            "confidence_score": 0.9,
            "ai_specific": False,
            "governance_themes": ["ict_third_party"],
            "ai_governance_requirements": [],
        }],
        "validation_result": {
            "overall_confidence": 0.9,
            "approved_findings": ["eu-dora"],
        },
        "token_usage": {},
    }

    persist_node(state, db_manager=db_manager)

    session = db_manager.get_session()
    try:
        regs = session.query(RegulationRow).all()
        assert [reg.id for reg in regs] == ["eu-dora-ict-third-party"]
        run = session.get(ResearchRunRow, "run-2")
        assert run.regulations_found == 0
        assert run.regulations_updated == 1
    finally:
        session.close()


def test_persist_does_not_count_noop_reconfirmation_as_update(db_manager):
    session = db_manager.get_session()
    try:
        _seed_eu(session)
        session.add(RegulationRow(
            id="eu-reg-2024-1689",
            jurisdiction_id="eu",
            name="Regulation (EU) 2024/1689",
            short_name="EU AI Act",
            issuing_body="European Parliament and Council",
            regulation_type="law",
            status="active",
            url="https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
            confidence_score=0.9,
            ai_specific=True,
            governance_themes=json.dumps(["transparency"]),
        ))
        session.add(AIGovernanceRequirementRow(
            id="req-existing",
            regulation_id="eu-reg-2024-1689",
            requirement_type="transparency_disclosure",
            governance_scope='["all"]',
            entity_types='["bank"]',
            key_controls='["disclosure"]',
            notes="same requirement",
        ))
        session.commit()
    finally:
        session.close()

    state = {
        "research_run_id": "run-3",
        "structured_findings": [{
            "regulation_id": "eu-ai-act",
            "jurisdiction_id": "eu",
            "name": "Regulation (EU) 2024/1689",
            "short_name": "EU AI Act",
            "issuing_body": "European Parliament and Council",
            "regulation_type": "law",
            "status": "active",
            "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
            "confidence_score": 0.9,
            "ai_specific": True,
            "governance_themes": ["transparency"],
            "ai_governance_requirements": [{
                "requirement_type": "transparency_disclosure",
                "governance_scope": ["all"],
                "entity_types": ["bank"],
                "key_controls": ["disclosure"],
                "notes": "same requirement",
            }],
        }],
        "validation_result": {
            "overall_confidence": 0.9,
            "approved_findings": ["eu-ai-act"],
        },
        "token_usage": {},
    }

    result = persist_node(state, db_manager=db_manager)

    session = db_manager.get_session()
    try:
        assert result["changes_detected"] == []
        assert session.query(RegulationRow).count() == 1
        assert session.query(AIGovernanceRequirementRow).count() == 1
        assert session.query(ChangeLogRow).count() == 0
        run = session.get(ResearchRunRow, "run-3")
        assert run.regulations_found == 0
        assert run.regulations_updated == 0
    finally:
        session.close()
