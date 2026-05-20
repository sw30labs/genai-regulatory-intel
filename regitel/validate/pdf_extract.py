"""PDF text extraction — uses PyMuPDF to extract text from Knowledge Base PDFs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF


@dataclass
class PDFDocument:
    """Extracted content from a single PDF."""
    file_path: str
    file_name: str
    jurisdiction_id: str
    page_count: int
    text: str
    title: Optional[str] = None
    keywords: list[str] = field(default_factory=list)
    extract_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Folder name → jurisdiction_id mapping
# ---------------------------------------------------------------------------

FOLDER_TO_JURISDICTION = {
    "Australia Knowledge Base": "australia",
    "Austria Knowledge Base": "austria",
    "Bahamas Knowledge Base": "bahamas",
    "Cayman Islands Knowledge Base": "cayman_islands",
    "European Union Knowledge Base": "eu",
    "Hong Kong Knowledge Base": "hong_kong",
    "India Knowledge Base": "india",
    "Jersey Knowledge Base": "jersey",
    "Korea South Knowledge Base": "korea_south",
    "Luxembourg Knowledge Base": "luxembourg",
    "Monaco Knowledge Base": "monaco",
    "PCI DSS": "pci_dss",
    "Singapore Knowledge Base": "singapore",
    "Switzerland Knowledge Base": "switzerland",
    "Taiwan Knowledge Base": "taiwan",
    "UK Knowledge Base": "uk",
    "USA Knowledge Base": "usa",
    "WEF Knowldedge Base": "wef",  # note: original typo preserved
}


def extract_pdf(pdf_path: Path, jurisdiction_id: str) -> PDFDocument:
    """Extract text and metadata from a single PDF."""
    try:
        doc = fitz.open(str(pdf_path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        text = "\n\n".join(pages)

        # Try to get title from metadata
        meta = doc.metadata or {}
        title = meta.get("title") or None

        doc.close()

        return PDFDocument(
            file_path=str(pdf_path),
            file_name=pdf_path.name,
            jurisdiction_id=jurisdiction_id,
            page_count=len(pages),
            text=text,
            title=title if title and title.strip() else None,
        )
    except Exception as e:
        return PDFDocument(
            file_path=str(pdf_path),
            file_name=pdf_path.name,
            jurisdiction_id=jurisdiction_id,
            page_count=0,
            text="",
            extract_error=str(e),
        )


def scan_kb_directory(kb_root: Path) -> list[PDFDocument]:
    """Scan a Knowledge Base root directory and extract all PDFs.

    Expects structure: kb_root/<Jurisdiction Knowledge Base>/*.pdf
    """
    results: list[PDFDocument] = []

    for folder in sorted(kb_root.iterdir()):
        if not folder.is_dir():
            continue

        jurisdiction_id = FOLDER_TO_JURISDICTION.get(folder.name)
        if not jurisdiction_id:
            continue

        pdf_files = sorted(folder.glob("*.pdf"))
        for pdf_path in pdf_files:
            doc = extract_pdf(pdf_path, jurisdiction_id)
            results.append(doc)

    return results


def extract_pentest_keywords(text: str) -> list[str]:
    """Extract penetration testing-related keywords from document text.

    Returns a list of matched keyword phrases found in the text.
    """
    text_lower = text.lower()

    PENTEST_TERMS = [
        "penetration test",
        "penetration testing",
        "pentest",
        "pen test",
        "vulnerability assessment",
        "vulnerability scan",
        "security assessment",
        "security testing",
        "red team",
        "red-team",
        "purple team",
        "threat-led penetration",
        "tlpt",
        "tiber",
        "cbest",
        "icast",
        "aase",
        "cyber resilience test",
        "ethical hacking",
        "intrusion test",
        "attack simulation",
        "vapt",
        "application security test",
        "network security test",
        "source code review",
        "code review",
        "security audit",
    ]

    found = []
    for term in PENTEST_TERMS:
        if term in text_lower:
            found.append(term)

    return found
