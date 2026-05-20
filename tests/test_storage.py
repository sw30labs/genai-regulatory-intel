"""Tests for storage layer — database, vector store, embeddings, dedup."""

import json

import pytest

from regitel.storage.database import (
    AIGovernanceRequirementRow,
    AIControlFrameworkRow,
    DatabaseManager,
    JurisdictionRow,
    RegulationRow,
    ResearchRunRow,
)
from regitel.storage.dedup import find_duplicates, merge_and_remove
from regitel.storage.vectorstore import VectorStoreManager


@pytest.fixture
def db_manager(tmp_path):
    db_path = tmp_path / "test.db"
    mgr = DatabaseManager(db_path)
    mgr.init_db()
    return mgr


class TestDatabaseManager:
    def test_init_creates_tables(self, db_manager):
        session = db_manager.get_session()
        try:
            # Verify tables exist
            from sqlalchemy import inspect
            inspector = inspect(db_manager.engine)
            table_names = inspector.get_table_names()
            assert "jurisdictions" in table_names
            assert "regulations" in table_names
            assert "ai_governance_requirements" in table_names
            assert "ai_control_frameworks" in table_names
            assert "change_log" in table_names
        finally:
            session.close()

    def test_research_runs_store_token_usage(self, db_manager):
        session = db_manager.get_session()
        try:
            run = ResearchRunRow(
                id="run-1",
                jurisdictions_scanned='["eu"]',
                status="completed",
                input_tokens=100,
                output_tokens=40,
                total_tokens=140,
                cached_input_tokens=20,
                reasoning_tokens=10,
                llm_calls=3,
                web_search_calls=2,
            )
            session.add(run)
            session.commit()

            found = session.get(ResearchRunRow, "run-1")
            assert found.total_tokens == 140
            assert found.cached_input_tokens == 20
            assert found.reasoning_tokens == 10
            assert found.llm_calls == 3
            assert found.web_search_calls == 2
        finally:
            session.close()

    def test_upsert_jurisdiction(self, db_manager):
        session = db_manager.get_session()
        try:
            db_manager.upsert_jurisdiction(session, id="eu", name="European Union", region="eu", research_priority=1)
            session.commit()
            row = session.query(JurisdictionRow).filter_by(id="eu").first()
            assert row is not None
            assert row.name == "European Union"
            assert row.research_priority == 1
        finally:
            session.close()

    def test_seed_jurisdictions(self, db_manager):
        session = db_manager.get_session()
        try:
            jurisdictions = [
                {"id": "eu", "name": "EU", "region": "eu", "research_priority": 1},
                {"id": "us", "name": "United States", "region": "na", "research_priority": 1},
            ]
            # Use upsert_jurisdiction directly (seed is handled by seeds.py)
            for j in jurisdictions:
                db_manager.upsert_jurisdiction(session, **j)
            session.commit()
            count = session.query(JurisdictionRow).count()
            assert count == 2
        finally:
            session.close()


class TestAIGovernanceRequirementRow:
    def test_create(self, db_manager):
        session = db_manager.get_session()
        try:
            reg = RegulationRow(
                id="eu-001", jurisdiction_id="eu", name="AI Act",
                regulation_type="regulation", status="active", confidence_score=0.95,
                ai_specific=True, governance_themes=json.dumps(["generative_ai"]),
            )
            session.add(reg)
            session.flush()

            req = AIGovernanceRequirementRow(
                id="req-1", regulation_id="eu-001",
                requirement_type="model_risk_management",
                governance_scope='["credit_underwriting"]',
                entity_types='["bank"]',
                risk_tier="high_risk",
                mandatory=True,
                applicable_to_deployers=True,
                key_controls='["model_validation"]',
            )
            session.add(req)
            session.commit()

            found = session.query(AIGovernanceRequirementRow).filter_by(id="req-1").first()
            assert found is not None
            assert found.requirement_type == "model_risk_management"
            assert found.mandatory is True
        finally:
            session.close()


class TestAIControlFrameworkRow:
    def test_create(self, db_manager):
        session = db_manager.get_session()
        try:
            reg = RegulationRow(
                id="eu-002", jurisdiction_id="eu", name="AI Act",
                regulation_type="regulation", status="active", confidence_score=0.95,
                ai_specific=True, governance_themes=json.dumps(["generative_ai"]),
            )
            session.add(reg)
            session.flush()

            fw = AIControlFrameworkRow(
                id="fw-1", regulation_id="eu-002",
                framework_name="EU AI Risk Classification",
                control_categories='["risk_classification", "inventory"]',
                inventory_required=True,
                explainability_required=True,
                human_overview_required=True,
                third_party_assessment=True,
                binding=True,
            )
            session.add(fw)
            session.commit()

            found = session.query(AIControlFrameworkRow).filter_by(id="fw-1").first()
            assert found is not None
            assert found.inventory_required is True
            assert found.binding is True
        finally:
            session.close()


class TestDeduplication:
    def test_find_duplicates_same_name(self, db_manager):
        session = db_manager.get_session()
        try:
            # Create two regulations with same jurisdiction and name
            reg1 = RegulationRow(
                id="eu-001", jurisdiction_id="eu", name="AI Act",
                regulation_type="regulation", status="active", confidence_score=0.95,
                ai_specific=True,
            )
            req1 = AIGovernanceRequirementRow(
                id="req-1", regulation_id="eu-001",
                requirement_type="model_risk_management", mandatory=True,
                governance_scope='[]', entity_types='["all"]',
            )
            reg2 = RegulationRow(
                id="eu-002", jurisdiction_id="eu", name="AI Act",
                regulation_type="regulation", status="active", confidence_score=0.80,
                ai_specific=True,
            )
            session.add_all([reg1, req1, reg2])
            session.commit()

            groups = find_duplicates(session)
            assert len(groups) == 1
            assert groups[0].keep_id == "eu-001"  # higher confidence kept
            assert "eu-002" in groups[0].remove_ids
        finally:
            session.close()

    def test_merge_dry_run(self, db_manager):
        session = db_manager.get_session()
        try:
            reg1 = RegulationRow(
                id="eu-001", jurisdiction_id="eu", name="AI Act",
                regulation_type="regulation", status="active", confidence_score=0.95,
                ai_specific=True, governance_themes=json.dumps(["generative_ai"]),
            )
            req1 = AIGovernanceRequirementRow(
                id="req-1", regulation_id="eu-001",
                requirement_type="model_risk_management", mandatory=True,
                governance_scope='[]', entity_types='["all"]',
                notes="MRM requirement",
            )
            reg2 = RegulationRow(
                id="eu-002", jurisdiction_id="eu", name="AI Act",
                regulation_type="regulation", status="active", confidence_score=0.80,
                ai_specific=True, governance_themes=json.dumps(["generative_ai"]),
            )
            req2 = AIGovernanceRequirementRow(
                id="req-2", regulation_id="eu-002",
                requirement_type="data_residency", mandatory=True,
                governance_scope='[]', entity_types='["bank"]',
                notes="Data residency requirement",
            )
            session.add_all([reg1, req1, reg2, req2])
            session.commit()

            groups = find_duplicates(session)
            assert len(groups) == 1
            actions = merge_and_remove(session, groups[0], dry_run=True)
            assert actions["kept"] == "eu-001"
            assert len(actions["removed"]) == 1
            # Verify the original rows still exist (dry run)
            count = session.query(RegulationRow).count()
            assert count == 2
            session.rollback()
        finally:
            session.close()


class TestVectorStoreManager:
    def test_init_collections(self, tmp_path):
        vs = VectorStoreManager(tmp_path / "vectors")
        vs.init_collections()
        assert vs.client.list_collections()

    def test_add_and_query(self, tmp_path):
        vs = VectorStoreManager(tmp_path / "vectors")
        vs.init_collections()

        from regitel.storage.vectorstore import REGULATION_TEXTS
        col = vs.get_collection(REGULATION_TEXTS)
        col.add(
            ids=["reg-1"],
            documents=["DORA ICT resilience requirements for banks"],
        )

        result = vs.query(
            REGULATION_TEXTS,
            query_texts=["banking IT security"],
            n_results=1,
        )
        assert len(result["ids"][0]) == 1
        assert result["ids"][0][0] == "reg-1"
