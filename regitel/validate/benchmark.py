"""Benchmark comparator — compare RegIntel DB findings against the existing KB PDFs.

Measures:
  - Coverage: what % of KB documents did regitel discover a matching regulation for?
  - Precision: are regitel's findings grounded in real regulations (that exist in the KB)?
  - AI relevance: of the KB docs that mention AI governance, how many did regitel capture?
  - Gap analysis: which KB documents have NO match in the DB?

Domain: Generative AI / Agentic AI governance for Tier 1 banks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from regitel.storage.database import (
    DatabaseManager,
    RegulationRow,
)
from regitel.validate.pdf_extract import (
    PDFDocument,
    extract_pentest_keywords,
    scan_kb_directory,
)


# ---------------------------------------------------------------------------
# Benchmark result types
# ---------------------------------------------------------------------------

@dataclass
class DocumentMatch:
    """A match between a KB PDF and a DB regulation."""
    pdf_file: str
    jurisdiction_id: str
    regulation_id: Optional[str] = None
    regulation_name: Optional[str] = None
    match_score: float = 0.0  # 0.0 to 1.0
    match_method: str = ""  # "title", "filename", "content_keyword"
    pentest_relevant: bool = False  # AI/relevance keywords detected (kept for backward compat)
    pentest_keywords: list[str] = field(default_factory=list)


@dataclass
class JurisdictionBenchmark:
    """Benchmark results for a single jurisdiction."""
    jurisdiction_id: str
    kb_doc_count: int = 0
    db_reg_count: int = 0
    matched_count: int = 0
    pentest_relevant_in_kb: int = 0
    pentest_relevant_matched: int = 0
    coverage_score: float = 0.0  # matched / kb_doc_count
    pentest_coverage: float = 0.0  # pentest_relevant_matched / pentest_relevant_in_kb
    matches: list[DocumentMatch] = field(default_factory=list)
    gaps: list[DocumentMatch] = field(default_factory=list)  # KB docs with no match
    extras: list[str] = field(default_factory=list)  # DB regs with no KB match


@dataclass
class BenchmarkResult:
    """Full benchmark result across all jurisdictions."""
    kb_root: str
    total_kb_docs: int = 0
    total_db_regs: int = 0
    total_matched: int = 0
    total_pentest_relevant: int = 0
    total_pentest_matched: int = 0
    overall_coverage: float = 0.0
    overall_pentest_coverage: float = 0.0
    jurisdictions: list[JurisdictionBenchmark] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normalize a string for fuzzy comparison."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _similarity(a: str, b: str) -> float:
    """Fuzzy string similarity (0.0 to 1.0)."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _match_pdf_to_regulations(
    pdf_doc: PDFDocument,
    regulations: list[RegulationRow],
) -> Optional[DocumentMatch]:
    """Try to match a KB PDF to a database regulation.

    Matching strategy (highest score wins):
    1. Title match: PDF metadata title vs regulation name/short_name
    2. Filename match: PDF filename vs regulation name/short_name
    3. Content keyword match: regulation name appears in PDF text (first 5000 chars)
    """
    best_match: Optional[DocumentMatch] = None
    best_score = 0.0
    pentest_kw = extract_pentest_keywords(pdf_doc.text)

    pdf_name_clean = pdf_doc.file_name.replace(".pdf", "").replace("_", " ").replace("-", " ")

    for reg in regulations:
        reg_names = [reg.name]
        if reg.short_name:
            reg_names.append(reg.short_name)
        if reg.issuing_body:
            reg_names.append(f"{reg.issuing_body} {reg.short_name or reg.name}")

        score = 0.0
        method = ""

        # Strategy 1: Title match
        if pdf_doc.title:
            for rn in reg_names:
                s = _similarity(pdf_doc.title, rn)
                if s > score:
                    score = s
                    method = "title"

        # Strategy 2: Filename match
        for rn in reg_names:
            s = _similarity(pdf_name_clean, rn)
            if s > score:
                score = s
                method = "filename"

        # Strategy 3: Content keyword match (check if reg name appears in text)
        text_head = pdf_doc.text[:5000].lower() if pdf_doc.text else ""
        for rn in reg_names:
            rn_lower = rn.lower()
            # Check if significant portion of the name appears in the text
            if len(rn_lower) > 5 and rn_lower in text_head:
                content_score = 0.7  # base score for content match
                if score < content_score:
                    score = content_score
                    method = "content_keyword"
            # Also check short abbreviations (e.g., "AI Act", "DORA", "CPS 234")
            if reg.short_name and len(reg.short_name) >= 3:
                sn = reg.short_name.lower()
                if sn in text_head:
                    content_score = 0.65
                    if score < content_score:
                        score = content_score
                        method = "content_keyword"

        if score > best_score and score >= 0.3:  # min threshold
            best_score = score
            best_match = DocumentMatch(
                pdf_file=pdf_doc.file_name,
                jurisdiction_id=pdf_doc.jurisdiction_id,
                regulation_id=reg.id,
                regulation_name=reg.name,
                match_score=score,
                match_method=method,
                pentest_relevant=len(pentest_kw) > 0,
                pentest_keywords=pentest_kw,
            )

    if best_match is None:
        # No match — return a gap entry
        return DocumentMatch(
            pdf_file=pdf_doc.file_name,
            jurisdiction_id=pdf_doc.jurisdiction_id,
            match_score=0.0,
            match_method="none",
            pentest_relevant=len(pentest_kw) > 0,
            pentest_keywords=pentest_kw,
        )

    return best_match


# ---------------------------------------------------------------------------
# Main benchmark function
# ---------------------------------------------------------------------------

def run_benchmark(
    db_manager: DatabaseManager,
    kb_root: Path,
    jurisdictions: Optional[list[str]] = None,
    verbose: bool = False,
) -> BenchmarkResult:
    """Run the full benchmark: scan KB, compare against DB, produce metrics.

    Args:
        db_manager: Database manager instance
        kb_root: Path to the Knowledge Base root directory
        jurisdictions: Optional list of jurisdiction IDs to benchmark (default: all)
        verbose: Print progress to console
    """
    from regitel.utils.logging import console

    if verbose:
        console.print(f"[info]Scanning Knowledge Base at {kb_root}...[/info]")

    # 1. Extract all PDFs
    all_docs = scan_kb_directory(kb_root)
    if verbose:
        console.print(f"  Extracted {len(all_docs)} PDFs")

    # 2. Group by jurisdiction
    docs_by_jur: dict[str, list[PDFDocument]] = {}
    for doc in all_docs:
        docs_by_jur.setdefault(doc.jurisdiction_id, []).append(doc)

    if jurisdictions:
        docs_by_jur = {k: v for k, v in docs_by_jur.items() if k in jurisdictions}

    # 3. Compare against DB
    session = db_manager.get_session()
    result = BenchmarkResult(kb_root=str(kb_root))

    try:
        for jid, docs in sorted(docs_by_jur.items()):
            regulations = (
                session.query(RegulationRow)
                .filter(RegulationRow.jurisdiction_id == jid)
                .all()
            )

            jbench = JurisdictionBenchmark(
                jurisdiction_id=jid,
                kb_doc_count=len(docs),
                db_reg_count=len(regulations),
            )

            if verbose:
                console.print(
                    f"\n[info]{jid}[/info]: {len(docs)} KB docs, "
                    f"{len(regulations)} DB regulations"
                )

            # Match each PDF to a regulation
            matched_reg_ids: set[str] = set()
            for doc in docs:
                match = _match_pdf_to_regulations(doc, regulations)
                if match and match.match_score >= 0.3 and match.regulation_id:
                    jbench.matches.append(match)
                    jbench.matched_count += 1
                    matched_reg_ids.add(match.regulation_id)
                    if match.pentest_relevant:
                        jbench.pentest_relevant_matched += 1
                else:
                    jbench.gaps.append(match)

                if match and match.pentest_relevant:
                    jbench.pentest_relevant_in_kb += 1

                if verbose and match:
                    status = (
                        f"[success]\u2713 {match.match_score:.0%}[/success] \u2192 {match.regulation_name}"
                        if match.regulation_id
                        else "[warning]\u2717 no match[/warning]"
                    )
                    pentest_tag = " [highlight][pentest][/highlight]" if match.pentest_relevant else ""
                    console.print(f"  {doc.file_name}{pentest_tag}: {status}")

            # Find DB regulations with no KB match
            for reg in regulations:
                if reg.id not in matched_reg_ids:
                    jbench.extras.append(reg.id)

            # Compute scores
            if jbench.kb_doc_count > 0:
                jbench.coverage_score = jbench.matched_count / jbench.kb_doc_count
            if jbench.pentest_relevant_in_kb > 0:
                jbench.pentest_coverage = (
                    jbench.pentest_relevant_matched / jbench.pentest_relevant_in_kb
                )

            result.jurisdictions.append(jbench)

        # Aggregate
        result.total_kb_docs = sum(j.kb_doc_count for j in result.jurisdictions)
        result.total_db_regs = sum(j.db_reg_count for j in result.jurisdictions)
        result.total_matched = sum(j.matched_count for j in result.jurisdictions)
        result.total_pentest_relevant = sum(j.pentest_relevant_in_kb for j in result.jurisdictions)
        result.total_pentest_matched = sum(j.pentest_relevant_matched for j in result.jurisdictions)

        if result.total_kb_docs > 0:
            result.overall_coverage = result.total_matched / result.total_kb_docs
        if result.total_pentest_relevant > 0:
            result.overall_pentest_coverage = (
                result.total_pentest_matched / result.total_pentest_relevant
            )

    finally:
        session.close()

    return result
