"""Tests for agent-specific JSON shape guards."""

from regitel.agents.reflection import _safe_parse_json as parse_reflection_json
from regitel.agents.validator import _safe_parse_json as parse_validator_json


def test_validator_parse_wraps_salvaged_issue_list():
    result = parse_validator_json('[{"severity": "warning", "message": "check this"}')

    assert result["passed"] is False
    assert result["issues"][0]["message"] == "check this"
    assert result["issues"][-1]["severity"] == "error"
    assert result["approved_findings"] == []
    assert result["rejected_findings"] == []


def test_reflection_parse_handles_salvaged_list_as_empty_actions():
    result = parse_reflection_json('[{"type": "drop", "regulation_id": "eu-test"}')

    assert result["analysis"] == "Reflection produced incomplete non-object output"
    assert result["actions"] == []
    assert result["drop_regulation_ids"] == []
    assert result["keep_regulation_ids"] == []
