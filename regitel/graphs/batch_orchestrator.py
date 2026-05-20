"""Batch Orchestrator — runs research pipeline per-jurisdiction with isolation.

Uses a LangGraph StateGraph to iterate through jurisdictions one at a time,
capturing results, errors, and timing for each.  Cross-contamination between
jurisdictions is impossible because each jurisdiction gets its own
``run_research()`` invocation with a fresh graph instance.

Topology::

    START → pick_next → run_one ──→ record_result ──→ check_done ──→ [pick_next | summarise → END]
                                      (always)         (conditional)

Usage from CLI::

    regitel scan --all
    regitel scan --priority 1
    regitel scan -j eu,uk,singapore
    regitel scan --all --dry-run
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import Annotated, TypedDict

from regitel.config import RegitelConfig
from regitel.seeds import get_jurisdiction_seeds
from regitel.utils.usage import merge_usage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _replace(left: Any, right: Any) -> Any:
    return right


def _merge_lists(left: list, right: list) -> list:
    return left + right


class JurisdictionResult(TypedDict, total=False):
    """Result of a single jurisdiction scan."""
    jurisdiction_id: str
    jurisdiction_name: str
    status: str                    # "success", "error", "skipped"
    findings_count: int
    new_regulations: int
    updated_regulations: int
    confidence: float
    reflection_iterations: int
    duration_seconds: float
    error_message: Optional[str]
    changes: list[dict]
    token_usage: dict


class BatchState(TypedDict, total=False):
    """State flowing through the batch orchestrator graph."""

    # --- Input ---
    target_jurisdictions: list[str]   # ordered list of jurisdiction IDs
    full_scan: bool
    dry_run: bool
    config: dict                       # serialised RegitelConfig (we pass the object via closure)

    # --- Cursor ---
    current_index: int                 # which jurisdiction are we on?
    current_jurisdiction: str          # ID being processed right now

    # --- Accumulator ---
    results: Annotated[list[dict], _merge_lists]

    # --- Live result from run_one (overwritten each iteration) ---
    last_result: dict

    # --- Summary (filled at end) ---
    batch_run_id: str
    started_at: str
    finished_at: str
    total_duration_seconds: float
    summary: dict


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def pick_next_node(state: BatchState) -> dict:
    """Advance the cursor to the next jurisdiction in the queue."""
    idx = state.get("current_index", -1) + 1
    targets = state["target_jurisdictions"]

    if idx >= len(targets):
        # Shouldn't happen (check_done guards), but be safe
        return {"current_index": idx, "current_jurisdiction": ""}

    jid = targets[idx]
    logger.info("Batch: picking jurisdiction %d/%d — %s", idx + 1, len(targets), jid)
    return {"current_index": idx, "current_jurisdiction": jid}


def run_one_node(state: BatchState, *, config: RegitelConfig) -> dict:
    """Run the research pipeline for a single jurisdiction (isolated).

    Any exception is caught and recorded — never propagated — so the batch
    continues regardless.
    """
    from regitel.graphs.research_graph import run_research

    jid = state["current_jurisdiction"]
    dry_run = state.get("dry_run", False)

    # Look up display name from seeds
    seeds = {s["id"]: s for s in get_jurisdiction_seeds()}
    jname = seeds.get(jid, {}).get("name", jid)

    logger.info("Batch: scanning %s (%s) — dry_run=%s", jid, jname, dry_run)
    t0 = time.monotonic()

    try:
        result = run_research(
            config=config,
            jurisdictions=[jid],
            full_scan=False,          # single-jurisdiction, not full
            dry_run=dry_run,
        )

        elapsed = time.monotonic() - t0
        changes = result.get("changes_detected", [])
        token_usage = result.get("token_usage", {})
        new_count = sum(1 for c in changes if c.get("change_type") == "new")
        updated_count = sum(1 for c in changes if c.get("change_type") == "updated")

        jr: JurisdictionResult = {
            "jurisdiction_id": jid,
            "jurisdiction_name": jname,
            "status": "error" if result.get("error") else "success",
            "findings_count": len(result.get("structured_findings", [])),
            "new_regulations": new_count,
            "updated_regulations": updated_count,
            "confidence": result.get("confidence_score", 0.0),
            "reflection_iterations": result.get("iteration_count", 0),
            "duration_seconds": round(elapsed, 1),
            "error_message": result.get("error"),
            "changes": changes,
            "token_usage": token_usage,
        }

    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error("Batch: %s failed — %s", jid, exc)
        jr: JurisdictionResult = {
            "jurisdiction_id": jid,
            "jurisdiction_name": jname,
            "status": "error",
            "findings_count": 0,
            "new_regulations": 0,
            "updated_regulations": 0,
            "confidence": 0.0,
            "reflection_iterations": 0,
            "duration_seconds": round(elapsed, 1),
            "error_message": f"{type(exc).__name__}: {exc}",
            "changes": [],
            "token_usage": {},
        }

    return {"last_result": jr}


def record_result_node(state: BatchState) -> dict:
    """Append the last result to the accumulated results list."""
    return {"results": [state["last_result"]]}


def check_done_node(state: BatchState) -> str:
    """Conditional: are there more jurisdictions to scan?"""
    idx = state.get("current_index", 0)
    total = len(state["target_jurisdictions"])
    if idx + 1 >= total:
        return "summarise"
    return "pick_next"


def summarise_node(state: BatchState) -> dict:
    """Produce a final summary of the batch run."""
    results = state.get("results", [])
    now = datetime.now(timezone.utc).isoformat()

    successes = [r for r in results if r["status"] == "success"]
    errors = [r for r in results if r["status"] == "error"]
    total_findings = sum(r["findings_count"] for r in results)
    total_new = sum(r["new_regulations"] for r in results)
    total_updated = sum(r["updated_regulations"] for r in results)
    total_time = sum(r["duration_seconds"] for r in results)
    token_usage = {}
    for result in results:
        token_usage = merge_usage(token_usage, result.get("token_usage", {}))
    avg_confidence = (
        sum(r["confidence"] for r in successes) / len(successes)
        if successes else 0.0
    )

    summary = {
        "total_jurisdictions": len(results),
        "successful": len(successes),
        "failed": len(errors),
        "total_findings": total_findings,
        "new_regulations": total_new,
        "updated_regulations": total_updated,
        "average_confidence": round(avg_confidence, 3),
        "total_duration_seconds": round(total_time, 1),
        "failed_jurisdictions": [
            {"id": r["jurisdiction_id"], "error": r["error_message"]}
            for r in errors
        ],
        "token_usage": token_usage,
    }

    return {
        "finished_at": now,
        "total_duration_seconds": round(total_time, 1),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_batch_graph(config: RegitelConfig) -> StateGraph:
    """Build and compile the batch orchestrator graph.

    The ``config`` object is captured in a closure so that ``run_one_node``
    can pass it to the per-jurisdiction research graph.
    """
    from functools import partial

    # Wrap with a lambda so LangGraph doesn't complain about the extra
    # keyword-only parameter type (it expects RunnableConfig, not ours).
    _run_one_fn = partial(run_one_node, config=config)
    _run_one = lambda state: _run_one_fn(state)  # noqa: E731

    graph = StateGraph(BatchState)

    graph.add_node("pick_next", pick_next_node)
    graph.add_node("run_one", _run_one)
    graph.add_node("record_result", record_result_node)
    graph.add_node("summarise", summarise_node)

    # Edges
    graph.add_edge(START, "pick_next")
    graph.add_edge("pick_next", "run_one")
    graph.add_edge("run_one", "record_result")

    # Conditional: loop or finish
    graph.add_conditional_edges(
        "record_result",
        check_done_node,
        {"pick_next": "pick_next", "summarise": "summarise"},
    )

    graph.add_edge("summarise", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_batch_scan(
    config: RegitelConfig,
    jurisdictions: Optional[list[str]] = None,
    priority: Optional[int] = None,
    dry_run: bool = False,
) -> BatchState:
    """Run an isolated per-jurisdiction scan across multiple regions.

    Parameters
    ----------
    config : RegitelConfig
    jurisdictions : list[str], optional
        Explicit list of jurisdiction IDs. Overrides *priority*.
    priority : int, optional
        Scan only jurisdictions at this priority level or higher (lower number).
        ``None`` or ``0`` means all.
    dry_run : bool
        If True, use mock search — no API calls.

    Returns
    -------
    BatchState
        Final state containing per-jurisdiction results and summary.
    """
    # Resolve targets
    if jurisdictions:
        target_jids = jurisdictions
    elif priority:
        seeds = get_jurisdiction_seeds()
        target_jids = [
            s["id"] for s in seeds
            if s.get("research_priority", 99) <= priority
        ]
    else:
        # All jurisdictions, ordered by priority
        seeds = get_jurisdiction_seeds()
        target_jids = [
            s["id"] for s in sorted(seeds, key=lambda s: s.get("research_priority", 99))
        ]

    run_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Batch scan %s — %d jurisdictions, dry_run=%s",
        run_id, len(target_jids), dry_run,
    )

    graph = build_batch_graph(config)

    initial_state: BatchState = {
        "target_jurisdictions": target_jids,
        "full_scan": True,
        "dry_run": dry_run,
        "config": {},
        "current_index": -1,
        "current_jurisdiction": "",
        "results": [],
        "last_result": {},
        "batch_run_id": run_id,
        "started_at": now,
        "finished_at": "",
        "total_duration_seconds": 0.0,
        "summary": {},
    }

    result = graph.invoke(initial_state)
    return result
