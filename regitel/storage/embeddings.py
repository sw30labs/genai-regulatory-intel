"""Embedding utilities — compute and store document embeddings using local models.

Uses sentence-transformers (all-MiniLM-L6-v2) for fast, on-device embeddings.
No cloud API calls.

Domain: Generative AI / Agentic AI governance for Tier 1 banks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass


from regitel.storage.database import DatabaseManager, RegulationRow
from regitel.storage.vectorstore import (
    AI_GOVERNANCE_GUIDANCE,
    REGULATION_TEXTS,
    VectorStoreManager,
)

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingStats:
    regulations_embedded: int = 0
    requirements_embedded: int = 0
    skipped: int = 0
    errors: int = 0


def _regulation_text(reg: RegulationRow) -> str:
    """Build a comprehensive text representation of a regulation for embedding."""
    parts = [
        f"Jurisdiction: {reg.jurisdiction_id}",
        f"Regulation: {reg.name}",
        reg.short_name or "",
        reg.issuing_body or "",
        f"Type: {reg.regulation_type}",
        f"Status: {reg.status}",
    ]
    if reg.effective_date:
        parts.append(f"Effective: {reg.effective_date.isoformat()}")
    if reg.url:
        parts.append(f"URL: {reg.url}")

    ai_specific = "AI-SPECIFIC" if reg.ai_specific else "Existing rules applied to AI context"
    parts.append(f"AI Classification: {ai_specific}")

    themes = json.loads(reg.governance_themes) if reg.governance_themes else []
    if themes:
        parts.append(f"Governance Themes: {', '.join(themes)}")

    if reg.ai_governance_requirements:
        parts.append("AI Governance Requirements:")
        for req in reg.ai_governance_requirements:
            req_text = (
                f"  - {req.requirement_type} ({req.risk_tier or 'all tiers'}, "
                f"{'mandatory' if req.mandatory else 'recommended'})"
            )
            if req.applicable_to_deployers:
                req_text += " [deployers]"
            if req.applicable_to_providers:
                req_text += " [providers]"
            scope = json.loads(req.governance_scope) if req.governance_scope else []
            if scope:
                req_text += f" scope: {', '.join(scope)}"
            controls = json.loads(req.key_controls) if req.key_controls else []
            if controls:
                req_text += f" controls: {', '.join(controls[:3])}"
            parts.append(req_text)

    if reg.ai_control_frameworks:
        parts.append("AI Control Frameworks:")
        for fw in reg.ai_control_frameworks:
            fw_parts = [f"  - {fw.framework_name}:"]
            if fw.inventory_required:
                fw_parts.append("AI inventory required")
            if fw.explainability_required:
                fw_parts.append("explainability required")
            if fw.human_overview_required:
                fw_parts.append("human oversight required")
            if fw.third_party_assessment:
                fw_parts.append("third-party assessment required")
            parts.append(" ".join(fw_parts))

    return "\n".join(p for p in parts if p)


def populate_embeddings(
    db_manager: DatabaseManager,
    vs_manager: VectorStoreManager,
    force: bool = False,
) -> EmbeddingStats:
    """Populate ChromaDB collections with regulation embeddings.

    Args:
        db_manager: Database manager for reading regulations
        vs_manager: Vector store manager with local embeddings
        force: If True, re-embed everything. Otherwise, skip existing docs.

    Returns:
        Stats about the embedding operation
    """
    vs_manager.init_collections()

    session = db_manager.get_session()
    try:
        # Check what's already in the vector store (if not forcing)
        if not force:
            existing = vs_manager.get_collection(REGULATION_TEXTS)
            existing_ids = set(existing.get()["ids"]) if existing.count() > 0 else set()
        else:
            existing_ids = set()

        stats = EmbeddingStats()

        # Get all active regulations
        regulations = (
            session.query(RegulationRow)
            .filter(RegulationRow.status == "active")
            .all()
        )

        # Embed regulations
        reg_texts_collection = vs_manager.get_collection(REGULATION_TEXTS)
        for reg in regulations:
            try:
                doc_id = reg.id
                if doc_id in existing_ids and not force:
                    stats.skipped += 1
                    continue

                text = _regulation_text(reg)
                if not text.strip():
                    stats.skipped += 1
                    continue

                embeddings = vs_manager.embedding_fn([text])

                reg_texts_collection.add(
                    ids=[doc_id],
                    documents=[text],
                    embeddings=embeddings,
                    metadatas=[{
                        "jurisdiction_id": reg.jurisdiction_id,
                        "regulation_id": reg.id,
                        "name": reg.name,
                        "short_name": reg.short_name or "",
                        "issuing_body": reg.issuing_body or "",
                        "regulation_type": reg.regulation_type,
                        "status": reg.status,
                        "ai_specific": reg.ai_specific,
                        "confidence_score": float(reg.confidence_score) if reg.confidence_score else 0.0,
                    }],
                )
                stats.regulations_embedded += 1

                # Also embed AI governance requirements for finer-grained search
                if reg.ai_governance_requirements:
                    for req in reg.ai_governance_requirements:
                        req_id = f"req-{req.id}"
                        if req_id in existing_ids and not force:
                            continue
                        req_text = (
                            f"Jurisdiction: {reg.jurisdiction_id} | "
                            f"Regulation: {reg.name} | "
                            f"Requirement: {req.requirement_type} | "
                            f"Risk Tier: {req.risk_tier or 'all'} | "
                            f"Mandatory: {req.mandatory}"
                        )
                        if req.penalties:
                            req_text += f" | Penalties: {req.penalties}"
                        scope = json.loads(req.governance_scope) if req.governance_scope else []
                        if scope:
                            req_text += f" | Scope: {', '.join(scope)}"
                        if req.notes:
                            req_text += f" | Notes: {req.notes}"
                        req_embeddings = vs_manager.embedding_fn([req_text])
                        vs_manager.add_documents(
                            AI_GOVERNANCE_GUIDANCE,
                            ids=[req_id],
                            documents=[req_text],
                            embeddings=req_embeddings,
                            metadatas=[{
                                "jurisdiction_id": reg.jurisdiction_id,
                                "regulation_id": reg.id,
                                "requirement_type": req.requirement_type,
                                "risk_tier": req.risk_tier or "",
                                "mandatory": req.mandatory,
                            }],
                        )
                        stats.requirements_embedded += 1

            except Exception as e:
                logger.error("Failed to embed regulation %s: %s", reg.id, e)
                stats.errors += 1

        logger.info(
            "Embedding complete: %d regulations, %d requirements, %d skipped, %d errors",
            stats.regulations_embedded,
            stats.requirements_embedded,
            stats.skipped,
            stats.errors,
        )
        return stats

    finally:
        session.close()


def semantic_search(
    vs_manager: VectorStoreManager,
    query: str,
    collection: str = REGULATION_TEXTS,
    n_results: int = 10,
    jurisdiction: str | None = None,
) -> list[dict]:
    """Run a semantic search query against the vector store.

    Uses local embeddings — no cloud calls.

    Args:
        vs_manager: Vector store manager
        query: Natural language query text
        collection: Which collection to search
        n_results: Max results to return
        jurisdiction: Optional jurisdiction filter

    Returns:
        List of result dicts with document, metadata, and relevance score
    """
    results = vs_manager.query(
        collection_name=collection,
        query_texts=[query],
        n_results=n_results,
        where={"jurisdiction_id": jurisdiction} if jurisdiction else None,
    )

    output = []
    if not results or "distances" not in results:
        return output

    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    dists = results.get("distances", [[]])[0]
    metas = results.get("metadatas", [[]])[0]

    for doc_id, doc_text, distance, meta in zip(ids, docs, dists, metas):
        # Convert cosine distance to similarity score (ChromaDB returns distances)
        relevance = max(0.0, 1.0 - distance)
        output.append({
            "id": doc_id,
            "document": doc_text,
            "metadata": meta or {},
            "relevance_score": round(relevance, 4),
        })

    return output
