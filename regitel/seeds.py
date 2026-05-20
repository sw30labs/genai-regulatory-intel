"""Jurisdiction seed data — loads from jurisdictions.yaml when available.

The system searches for jurisdictions.yaml in this order:
  1. Next to regitel.yaml (project root)
  2. ~/.config/regitel/jurisdictions.yaml
  3. Fallback: built-in JURISDICTION_SEEDS list (backward compatible)

To customize jurisdictions, copy the provided jurisdictions.yaml to one of
the above locations and edit it.  Run ``regitel db init --seed`` to apply.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

_YAML_SEARCH_PATHS = [
    Path("jurisdictions.yaml"),
    Path("jurisdictions.yml"),
    Path.home() / ".config" / "regitel" / "jurisdictions.yaml",
]


def _map_yaml_to_seed(entry: dict) -> dict:
    """Convert a YAML jurisdiction entry to the internal seed format.

    The YAML uses ``priority`` for brevity; internally we use
    ``research_priority`` to match the database column.
    """
    return {
        "id": entry["id"],
        "name": entry["name"],
        "region": entry["region"],
        "research_priority": entry.get("priority", entry.get("research_priority", 5)),
        "regulatory_bodies": entry.get("regulatory_bodies", []),
        "key_regulations": entry.get("key_regulations", []),
        "search_terms": entry.get("search_terms", []),
    }


def load_jurisdictions_yaml(path: Optional[str | Path] = None) -> Optional[list[dict]]:
    """Try to load jurisdictions from a YAML file.

    Parameters
    ----------
    path : str | Path, optional
        Explicit path.  If *None*, the standard search paths are tried.

    Returns
    -------
    list[dict] | None
        Parsed seed list, or *None* if no file was found.
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    else:
        candidates.extend(_YAML_SEARCH_PATHS)

    for candidate in candidates:
        if candidate.exists():
            try:
                raw = yaml.safe_load(candidate.read_text()) or []
                seeds = [_map_yaml_to_seed(entry) for entry in raw]
                logger.info("Loaded %d jurisdictions from %s", len(seeds), candidate)
                return seeds
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", candidate, exc)
                return None

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_jurisdiction_seeds(yaml_path: Optional[str | Path] = None) -> list[dict]:
    """Return jurisdiction seed data, preferring YAML over built-in defaults.

    This is the recommended entry point.  All callers should use this
    function instead of accessing ``JURISDICTION_SEEDS`` directly.
    """
    loaded = load_jurisdictions_yaml(yaml_path)
    if loaded is not None:
        return loaded
    logger.debug("No jurisdictions.yaml found — using built-in defaults")
    return JURISDICTION_SEEDS


# ---------------------------------------------------------------------------
# Built-in fallback (minimal set of key jurisdictions for GenAI governance)
# ---------------------------------------------------------------------------

JURISDICTION_SEEDS: list[dict] = [
    {
        "id": "eu",
        "name": "European Union",
        "region": "eu",
        "research_priority": 1,
        "regulatory_bodies": [
            {"name": "European Banking Authority", "acronym": "EBA",
             "url": "https://www.eba.europa.eu"},
            {"name": "European Commission", "acronym": "EC",
             "url": "https://commission.europa.eu"},
        ],
        "key_regulations": [
            "EU AI Act", "GDPR Art. 22", "DORA",
        ],
        "search_terms": [
            "EU AI Act high-risk financial services",
            "GDPR automated decision-making credit scoring",
            "DORA foundation model providers ICT third party",
        ],
    },
    {
        "id": "uk",
        "name": "United Kingdom",
        "region": "eu",
        "research_priority": 1,
        "regulatory_bodies": [
            {"name": "Prudential Regulation Authority", "acronym": "PRA",
             "url": "https://www.bankofengland.co.uk/prudential-regulation"},
            {"name": "Financial Conduct Authority", "acronym": "FCA",
             "url": "https://www.fca.org.uk"},
        ],
        "key_regulations": [
            "PRA SS1/23 (Model Risk Management)",
            "FCA AI Update",
        ],
        "search_terms": [
            "PRA SS1/23 AI model risk management",
            "FCA AI governance financial services",
        ],
    },
    {
        "id": "usa",
        "name": "United States",
        "region": "americas",
        "research_priority": 1,
        "regulatory_bodies": [
            {"name": "Office of the Comptroller of the Currency", "acronym": "OCC",
             "url": "https://www.occ.treas.gov"},
            {"name": "Federal Reserve", "acronym": "Fed",
             "url": "https://www.federalreserve.gov"},
            {"name": "New York Department of Financial Services", "acronym": "NYDFS",
             "url": "https://www.dfs.ny.gov"},
        ],
        "key_regulations": [
            "OCC Bulletin 2026-13 / Fed SR 26-2 (MRM gap for GenAI)",
            "NYDFS AI Cybersecurity Guidance",
            "Treasury FS AI RMF",
        ],
        "search_terms": [
            "OCC GenAI MRM gap SR 26-2",
            "NYDFS AI third-party risk banking",
            "Treasury AI risk management financial services",
        ],
    },
    {
        "id": "singapore",
        "name": "Singapore",
        "region": "apac",
        "research_priority": 1,
        "regulatory_bodies": [
            {"name": "Monetary Authority of Singapore", "acronym": "MAS",
             "url": "https://www.mas.gov.sg"},
        ],
        "key_regulations": [
            "MAS Information Paper AI MRM",
            "MAS FEAT guidelines",
        ],
        "search_terms": [
            "MAS AI model risk management Singapore",
            "MAS FEAT AI financial services",
        ],
    },
    {
        "id": "switzerland",
        "name": "Switzerland",
        "region": "eu",
        "research_priority": 1,
        "regulatory_bodies": [
            {"name": "Swiss Financial Market Supervisory Authority", "acronym": "FINMA",
             "url": "https://www.finma.ch"},
        ],
        "key_regulations": [
            "FINMA Guidance 08/2024 (AI in financial services)",
        ],
        "search_terms": [
            "FINMA AI inventory requirements",
            "FINMA 08/2024 explainability AI banking",
        ],
    },
    {
        "id": "global_standards",
        "name": "Global Standards (BIS / FSB)",
        "region": "global",
        "research_priority": 1,
        "regulatory_bodies": [
            {"name": "Basel Committee on Banking Supervision", "acronym": "BCBS",
             "url": "https://www.bis.org"},
            {"name": "Financial Stability Board", "acronym": "FSB",
             "url": "https://www.fsb.org"},
        ],
        "key_regulations": [
            "BCBS Newsletter on AI (Dec 2024)",
            "FSB AI Financial Stability Report",
        ],
        "search_terms": [
            "BCBS AI Pillar 2 banking",
            "FSB AI financial stability implications",
        ],
    },
]
