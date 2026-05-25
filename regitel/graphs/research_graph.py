"""Research Graph — LangGraph StateGraph wiring the research → validate → reflect loop.

Domain: Generative AI / Agentic AI governance for Tier 1 banks.
"""

from __future__ import annotations

import logging
import uuid
from functools import partial
from typing import Optional

from langgraph.graph import END, START, StateGraph

from regitel.agents.persister import persist_node
from regitel.agents.reflection import reflect_node
from regitel.agents.research import plan_node, research_node
from regitel.agents.validator import validate_node
from regitel.config import RegitelConfig
from regitel.models.state import ResearchState
from regitel.seeds import get_jurisdiction_seeds
from regitel.storage.database import DatabaseManager
from regitel.tools.search import MockSearchTool, OpenAIWebSearchTool, TavilySearchTool
from regitel.utils.llm import get_agent_llm

logger = logging.getLogger(__name__)


def _apply_quick_scan_defaults(config: RegitelConfig) -> RegitelConfig:
    """Return a copy tuned for lower-latency local model scans."""
    quick_config = config.model_copy(deep=True)
    quick_config.research.max_queries_per_jurisdiction = min(
        quick_config.research.max_queries_per_jurisdiction,
        3,
    )
    quick_config.research.max_search_results_per_query = min(
        quick_config.research.max_search_results_per_query,
        3,
    )
    quick_config.research.validator_batch_size = min(
        quick_config.research.validator_batch_size,
        3,
    )
    quick_config.research.max_reflection_iterations = min(
        quick_config.research.max_reflection_iterations,
        1,
    )
    quick_config.research.quality_gate_reflection = False
    return quick_config


def _build_seeds_map() -> dict:
    """Build a dict mapping jurisdiction ID → seed profile."""
    return {s["id"]: s for s in get_jurisdiction_seeds()}


def _route_after_validation(state: ResearchState) -> str:
    """Conditional edge: after validation, persist or reflect.

    Policy:
      - Validation failed           → reflect (up to max_iterations)
      - Validation passed, but this
        is the FIRST iteration and
        there ARE new findings       → reflect once (quality gate)
      - Validation passed otherwise  → persist
      - Max iterations reached       → persist regardless
    """
    iteration = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 3)

    # Hard ceiling — always persist after max iterations
    if iteration >= max_iter:
        return "persist"

    # Validation failed — reflect to fix
    if not state.get("validation_passed", False):
        return "reflect"

    # Validation passed — but if this is the first pass and we have
    # findings, force one reflection cycle as a quality gate.
    # The reflection agent will either confirm (no new queries → persist)
    # or suggest improvements (new queries → re-research).
    findings = state.get("structured_findings", [])
    if state.get("quality_gate_reflection", True) and iteration == 0 and len(findings) > 0:
        logger.info(
            "Validation passed on first iteration with %d findings "
            "— routing to reflection for quality gate",
            len(findings),
        )
        return "reflect"

    return "persist"


def _route_after_reflection(state: ResearchState) -> str:
    """After reflection, go back to research (with new queries) or validate again."""
    new_queries = state.get("search_queries", [])
    if new_queries:
        return "research"  # Re-research with new queries
    return "validate"  # Re-validate with cleaned findings


def build_research_graph(
    config: RegitelConfig,
    dry_run: bool = False,
) -> StateGraph:
    """Build and compile the research workflow graph.

    Graph topology:
        START → plan → research → validate → [persist | reflect]
                                                         ↓
                                               reflect → [research | validate]
        persist → END
    """
    db_manager = DatabaseManager(config.storage.database)
    db_manager.init_db()
    seeds_map = _build_seeds_map()

    # LLMs — live runs use OpenAI Responses; dry-run stays fully mocked.
    if dry_run:
        from regitel.utils.mock_llm import MockChatModel
        research_llm = MockChatModel()
        validator_llm = MockChatModel()
        reflection_llm = MockChatModel()
        search_tool = MockSearchTool()
    else:
        research_llm = get_agent_llm(config, "research")
        validator_llm = get_agent_llm(config, "validator")
        reflection_llm = get_agent_llm(config, "reflection")
        search_provider = config.research.search_provider.lower()
        if search_provider == "tavily":
            search_tool = TavilySearchTool(
                max_results=config.research.max_search_results_per_query,
            )
        else:
            if search_provider != "openai":
                logger.warning("Unsupported search provider '%s'; using OpenAI", search_provider)
            search_tool = OpenAIWebSearchTool(
                api_key=config.llm.api_key,
                model=config.llm.model,
                base_url=config.llm.base_url,
                max_results=config.research.max_search_results_per_query,
            )

    # Bind dependencies to node functions via partial
    _plan = partial(plan_node, llm=research_llm, seeds_map=seeds_map,
                    db_manager=db_manager)
    _research = partial(
        research_node,
        llm=research_llm,
        search_tool=search_tool,
        seeds_map=seeds_map,
        max_queries_per_jurisdiction=config.research.max_queries_per_jurisdiction,
    )
    _validate = partial(
        validate_node,
        llm=validator_llm,
        db_manager=db_manager,
        batch_size=config.research.validator_batch_size,
    )
    _reflect = partial(reflect_node, llm=reflection_llm)
    _persist = partial(persist_node, db_manager=db_manager)

    # Build the graph
    graph = StateGraph(ResearchState)

    graph.add_node("plan", _plan)
    graph.add_node("research", _research)
    graph.add_node("validate", _validate)
    graph.add_node("reflect", _reflect)
    graph.add_node("persist", _persist)

    # Edges
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "research")
    graph.add_edge("research", "validate")

    # Conditional: after validation
    graph.add_conditional_edges(
        "validate",
        _route_after_validation,
        {"persist": "persist", "reflect": "reflect"},
    )

    # Conditional: after reflection
    graph.add_conditional_edges(
        "reflect",
        _route_after_reflection,
        {"research": "research", "validate": "validate"},
    )

    graph.add_edge("persist", END)

    return graph.compile()


def run_research(
    config: RegitelConfig,
    jurisdictions: Optional[list[str]] = None,
    full_scan: bool = False,
    dry_run: bool = False,
    quick: bool = False,
) -> ResearchState:
    """Run the research pipeline and return the final state.

    Args:
        config: Application configuration
        jurisdictions: List of jurisdiction IDs to scan (None = priority_1)
        full_scan: If True, scan all jurisdictions
        dry_run: If True, use mock search (no API calls)

    Returns:
        Final ResearchState with results
    """
    if quick:
        config = _apply_quick_scan_defaults(config)

    # Determine which jurisdictions to scan
    if full_scan:
        target_jids = config.all_jurisdictions
    elif jurisdictions:
        target_jids = jurisdictions
    else:
        target_jids = config.jurisdiction_priorities.get("priority_1", [])

    logger.info(
        "Starting research scan — %d jurisdictions (%s, quick=%s, max_queries=%d): %s",
        len(target_jids),
        "dry-run" if dry_run else "live",
        quick,
        config.research.max_queries_per_jurisdiction,
        target_jids,
    )

    graph = build_research_graph(config, dry_run=dry_run)

    initial_state: ResearchState = {
        "jurisdictions": target_jids,
        "focus_areas": ["ai_governance_requirements", "ai_control_frameworks", "data_residency", "model_risk_management", "third_party_risk"],
        "full_scan": full_scan,
        "search_queries": [],
        "raw_findings": [],
        "structured_findings": [],
        "validation_result": {},
        "validation_passed": False,
        "reflection_notes": "",
        "iteration_count": 0,
        "max_iterations": config.research.max_reflection_iterations,
        "quality_gate_reflection": config.research.quality_gate_reflection,
        "changes_detected": [],
        "research_run_id": str(uuid.uuid4())[:8],
        "confidence_score": 0.0,
        "token_usage": {},
        "error": None,
    }

    # Execute the graph
    result = graph.invoke(initial_state)
    return result
