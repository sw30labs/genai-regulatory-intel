"""Deduplication — detect and merge duplicate regulations in the database."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from regitel.storage.database import (
    DatabaseManager,
    RegulationRow,
)
from regitel.utils.canonical import stable_regulation_id

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroup:
    """A group of regulations that appear to be duplicates."""
    jurisdiction_id: str
    canonical_name: str
    keep_id: str  # highest confidence, most complete
    remove_ids: list[str] = field(default_factory=list)
    reason: str = ""


def find_duplicates(session: Session) -> list[DuplicateGroup]:
    """Detect duplicate regulations by stable canonical identity."""
    regs = (
        session.query(RegulationRow)
        .order_by(RegulationRow.jurisdiction_id, RegulationRow.name)
        .all()
    )

    # Group by deterministic regulation identity rather than LLM-generated IDs.
    groups: dict[tuple[str, str], list[RegulationRow]] = defaultdict(list)
    for r in regs:
        key = (
            r.jurisdiction_id,
            stable_regulation_id({
                "regulation_id": r.id,
                "jurisdiction_id": r.jurisdiction_id,
                "name": r.name,
                "short_name": r.short_name,
                "issuing_body": r.issuing_body,
                "url": r.url,
            }),
        )
        groups[key].append(r)

    duplicates: list[DuplicateGroup] = []
    for (jid, _), group in groups.items():
        if len(group) < 2:
            continue

        # Pick the best: highest confidence, then most governance requirements
        ranked = sorted(
            group,
            key=lambda r: (
                r.confidence_score or 0,
                len(r.ai_governance_requirements),
                len(r.ai_control_frameworks),
            ),
            reverse=True,
        )

        keep = ranked[0]
        remove = [r.id for r in ranked[1:]]

        duplicates.append(DuplicateGroup(
            jurisdiction_id=jid,
            canonical_name=keep.name,
            keep_id=keep.id,
            remove_ids=remove,
            reason=f"Same canonical identity in {jid}, keeping highest confidence ({keep.confidence_score:.2f})",
        ))

    return duplicates


def merge_and_remove(
    session: Session,
    group: DuplicateGroup,
    dry_run: bool = False,
) -> dict:
    """Merge AI governance requirements from duplicates into the keeper, then delete duplicates.

    Returns a summary dict of actions taken.
    """
    keep = session.get(RegulationRow, group.keep_id)
    if not keep:
        return {"error": f"Keeper {group.keep_id} not found"}

    actions = {
        "kept": group.keep_id,
        "removed": [],
        "reqs_merged": 0,
        "frameworks_merged": 0,
    }

    existing_req_notes = {
        r.notes for r in keep.ai_governance_requirements if r.notes
    }

    for remove_id in group.remove_ids:
        dup = session.get(RegulationRow, remove_id)
        if not dup:
            continue

        # Count what will be merged (for both dry_run and real runs)
        for req in dup.ai_governance_requirements:
            if req.notes and req.notes in existing_req_notes:
                continue
            actions["reqs_merged"] += 1
            if not dry_run:
                existing_req_notes.add(req.notes)

        existing_fw_names = {t.framework_name for t in keep.ai_control_frameworks}
        for fw in dup.ai_control_frameworks:
            if fw.framework_name not in existing_fw_names:
                actions["frameworks_merged"] += 1
                if not dry_run:
                    existing_fw_names.add(fw.framework_name)

        if not dry_run:
            # Use raw SQL to re-parent ALL child tables, avoiding ORM cascade issues
            keep_id = group.keep_id

            session.execute(
                text("UPDATE ai_governance_requirements SET regulation_id = :keep WHERE regulation_id = :remove"),
                {"keep": keep_id, "remove": remove_id},
            )
            session.execute(
                text("UPDATE ai_control_frameworks SET regulation_id = :keep WHERE regulation_id = :remove"),
                {"keep": keep_id, "remove": remove_id},
            )
            session.execute(
                text("UPDATE change_log SET regulation_id = :keep WHERE regulation_id = :remove"),
                {"keep": keep_id, "remove": remove_id},
            )
            session.execute(
                text("UPDATE source_documents SET regulation_id = :keep WHERE regulation_id = :remove"),
                {"keep": keep_id, "remove": remove_id},
            )
            # Delete the duplicate regulation
            session.execute(
                text("DELETE FROM regulations WHERE id = :remove"),
                {"remove": remove_id},
            )

        actions["removed"].append(remove_id)

    if not dry_run:
        session.flush()

    return actions


def run_dedup(
    db_manager: DatabaseManager,
    dry_run: bool = True,
) -> list[dict]:
    """Run full deduplication. Returns list of action summaries."""
    session = db_manager.get_session()
    results = []

    try:
        groups = find_duplicates(session)
        logger.info(f"Found {len(groups)} duplicate groups")

        for group in groups:
            result = merge_and_remove(session, group, dry_run=dry_run)
            result["jurisdiction"] = group.jurisdiction_id
            result["name"] = group.canonical_name
            result["reason"] = group.reason
            results.append(result)

        if not dry_run:
            session.commit()
            logger.info(f"Dedup committed: removed {sum(len(r['removed']) for r in results)} duplicates")
        else:
            session.rollback()
            logger.info(f"Dedup dry-run: would remove {sum(len(r['removed']) for r in results)} duplicates")

    except Exception as e:
        session.rollback()
        logger.error(f"Dedup failed: {e}")
        raise
    finally:
        session.close()

    return results
