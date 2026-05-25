"""Tests for batched validator calls."""

import json
import re
from types import SimpleNamespace

import pytest

from regitel.agents.validator import validate_node
from regitel.storage.database import JurisdictionRow
from regitel.utils.llm_errors import LLMProviderError


@pytest.fixture
def db_manager(tmp_path):
    from regitel.storage.database import DatabaseManager

    mgr = DatabaseManager(tmp_path / "test.db")
    mgr.init_db()
    return mgr


class BatchValidatorLLM:
    def __init__(self):
        self.calls = []

    def invoke(self, messages):
        prompt = messages[1]["content"]
        self.calls.append(prompt)
        ids = re.findall(r'"regulation_id": "([^"]+)"', prompt)
        return SimpleNamespace(
            content=json.dumps({
                "passed": True,
                "overall_confidence": 0.8,
                "issues": [],
                "approved_findings": ids,
                "rejected_findings": [],
            }),
            response_metadata={"usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "llm_calls": 1}},
        )


def test_validate_node_batches_large_finding_sets(db_manager):
    session = db_manager.get_session()
    try:
        session.add(JurisdictionRow(id="eu", name="European Union", region="eu"))
        session.commit()
    finally:
        session.close()

    findings = [
        {
            "regulation_id": f"eu-test-{idx}",
            "jurisdiction_id": "eu",
            "name": f"EU Test {idx}",
            "url": f"https://example.com/{idx}",
            "ai_specific": False,
            "ai_governance_requirements": [{"requirement_type": "general"}],
        }
        for idx in range(5)
    ]
    llm = BatchValidatorLLM()

    result = validate_node(
        {"structured_findings": findings},
        llm=llm,
        db_manager=db_manager,
        batch_size=2,
    )

    assert len(llm.calls) == 3
    assert result["validation_passed"] is True
    assert result["validation_result"]["approved_findings"] == [
        "eu-test-0",
        "eu-test-1",
        "eu-test-2",
        "eu-test-3",
        "eu-test-4",
    ]
    assert result["token_usage"] == {
        "input_tokens": 30,
        "output_tokens": 6,
        "total_tokens": 36,
        "llm_calls": 3,
    }


def test_validate_node_does_not_approve_when_llm_fails(db_manager):
    class FailingLLM:
        def invoke(self, messages):
            raise RuntimeError("insufficient_quota")

    session = db_manager.get_session()
    try:
        session.add(JurisdictionRow(id="eu", name="European Union", region="eu"))
        session.commit()
    finally:
        session.close()

    findings = [{
        "regulation_id": "eu-test",
        "jurisdiction_id": "eu",
        "name": "EU Test",
        "url": "https://example.com/eu-test",
        "ai_specific": False,
        "ai_governance_requirements": [{"requirement_type": "general"}],
    }]

    with pytest.raises(LLMProviderError):
        validate_node(
            {"structured_findings": findings},
            llm=FailingLLM(),
            db_manager=db_manager,
            batch_size=4,
        )
