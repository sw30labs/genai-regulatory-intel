"""LangGraph state definitions for all workflows."""

from __future__ import annotations

from typing import Any, Optional

from typing_extensions import Annotated, TypedDict

from regitel.utils.usage import merge_usage


def _merge_lists(left: list, right: list) -> list:
    """Reducer that concatenates lists (used for accumulating results)."""
    return left + right


def _replace(left: Any, right: Any) -> Any:
    """Reducer that replaces the previous value."""
    return right


# ---------------------------------------------------------------------------
# Research Workflow State
# ---------------------------------------------------------------------------

class ResearchState(TypedDict, total=False):
    """State flowing through the research → validate → reflect graph."""

    # --- Input ---
    jurisdictions: list[str]
    focus_areas: list[str]
    full_scan: bool

    # --- Plan phase ---
    search_queries: Annotated[list[dict], _merge_lists]

    # --- Research phase ---
    raw_findings: Annotated[list[dict], _merge_lists]
    structured_findings: Annotated[list[dict], _merge_lists]

    # --- Validation phase ---
    validation_result: dict
    validation_passed: bool

    # --- Reflection phase ---
    reflection_notes: str
    iteration_count: int
    max_iterations: int  # default 3

    # --- Output ---
    changes_detected: Annotated[list[dict], _merge_lists]
    research_run_id: str
    confidence_score: float
    token_usage: Annotated[dict, merge_usage]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Query Workflow State
# ---------------------------------------------------------------------------

class QueryState(TypedDict, total=False):
    """State for the query-answering graph."""

    question: str
    query_type: str          # "structured" or "semantic"
    sql_query: Optional[str]
    retrieved_chunks: list[dict]
    answer: str
    sources: list[dict]


# ---------------------------------------------------------------------------
# Ingest Workflow State
# ---------------------------------------------------------------------------

class IngestState(TypedDict, total=False):
    """State for the document ingestion graph."""

    file_path: str
    jurisdiction_id: Optional[str]
    extracted_text: str
    extracted_entities: list[dict]
    validation_result: dict
    validation_passed: bool
    persisted: bool
