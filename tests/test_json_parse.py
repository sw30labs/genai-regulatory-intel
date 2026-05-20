"""Tests for robust model JSON parsing."""

import logging

from regitel.utils.json_parse import parse_model_json


def test_parse_model_json_strips_markdown_fences():
    text = """```json
    {"results": [{"title": "A"}]}
    ```"""

    assert parse_model_json(text, logger=logging.getLogger(__name__), context="test") == {
        "results": [{"title": "A"}],
    }


def test_parse_model_json_extracts_balanced_payload_from_prose():
    text = 'Here is the JSON:\n[{"query": "EU AI Act"}]\nDone.'

    assert parse_model_json(text, logger=logging.getLogger(__name__), context="test") == [
        {"query": "EU AI Act"},
    ]


def test_parse_model_json_returns_none_for_truncated_payload(caplog):
    text = '{"results":[{"title":"Regulation","content":"unterminated'

    with caplog.at_level(logging.ERROR):
        result = parse_model_json(text, logger=logging.getLogger(__name__), context="test")

    assert result is None
    assert "JSON parse failed" in caplog.text
    assert "tail=" in caplog.text


def test_parse_model_json_salvages_complete_items_from_truncated_array(caplog):
    text = '[{"regulation_id": "one"}, {"regulation_id": "two", "name": "unterminated'

    with caplog.at_level(logging.WARNING):
        result = parse_model_json(text, logger=logging.getLogger(__name__), context="test")

    assert result == [{"regulation_id": "one"}]
    assert "salvaged 1 complete array item" in caplog.text
