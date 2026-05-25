"""Canonical identifiers for regulatory findings."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit


_PUNCT_RE = re.compile(r"[^a-z0-9]+")
_REGULATION_EU_RE = re.compile(r"(?:regulation\s*)?\(?eu\)?\s*(\d{4})/(\d{1,6})", re.I)
_ELI_REG_RE = re.compile(r"/eli/reg/(\d{4})/(\d{1,6})", re.I)
_CASE_RE = re.compile(r"\b(?:case\s*)?c[-\s](\d{1,4})/(\d{2})\b", re.I)
_CELEX_CASE_RE = re.compile(r"\b6(20\d{2}|19\d{2})cj0*(\d{1,4})\b", re.I)
_PRA_SS_RE = re.compile(r"\b(?:pra\s*)?ss\s*(\d+)/(\d{2})\b", re.I)
_PRA_PS_RE = re.compile(r"\b(?:pra\s*)?ps\s*(\d+)/(\d{2})\b", re.I)
_OCC_BULLETIN_RE = re.compile(r"\bocc(?:\s+bulletin)?\s*(20\d{2})[-/](\d+)\b", re.I)
_FED_SR_RE = re.compile(r"\b(?:fed(?:eral reserve)?\s*)?sr\s*(\d{2})[-/](\d+)\b", re.I)
_MAS_NOTICE_RE = re.compile(r"\bmas\s+notice\s+(\d+[a-z]?)\b", re.I)
_FINMA_CIRCULAR_RE = re.compile(r"\bfinma\s+circular\s+(\d{4})/(\d+)\b", re.I)
_FINMA_GUIDANCE_RE = re.compile(r"\bfinma\s+guidance\s+(\d{1,2})/(\d{4})\b", re.I)
_APRA_CPS_RE = re.compile(r"\bapra\s+cps\s+(\d+)\b", re.I)
_APRA_CPG_RE = re.compile(r"\b(?:apra\s+)?cpg\s+(\d+)\b", re.I)
_BRAZIL_RESOLUTION_RE = re.compile(
    r"\b(cmn|bcb)\s+resolution\s+(\d[\d,.]*)/(\d{4})\b",
    re.I,
)
_OSFI_GUIDELINE_RE = re.compile(r"\bosfi\s+guideline\s+([a-z]+)[-\s]?(\d+)\b", re.I)


def normalize_text(value: Any) -> str:
    """Return a lowercase alphanumeric text key."""
    if value is None:
        return ""
    text = str(value).lower().strip()
    text = text.replace("&", " and ")
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def slugify(value: Any, *, max_length: int = 64) -> str:
    """Return a stable slug for fallback identifiers."""
    text = normalize_text(value)
    slug = "-".join(text.split())
    return slug[:max_length].strip("-") or "unknown"


def canonical_url(value: Any) -> str:
    """Normalize source URLs for matching."""
    if not value:
        return ""

    parts = urlsplit(str(value).strip())
    if not parts.scheme or not parts.netloc:
        return str(value).strip().lower()

    query = parse_qs(parts.query)
    celex = query.get("uri", [""])[0]
    if celex.upper().startswith("CELEX:"):
        query_text = f"uri={celex.upper()}"
    else:
        query_text = ""

    path = re.sub(r"/(eng?|en)$", "", parts.path.rstrip("/"), flags=re.I)
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        path.lower(),
        query_text,
        "",
    ))


def _text_blob(data: dict[str, Any]) -> str:
    return " ".join(
        str(data.get(key) or "")
        for key in ("regulation_id", "name", "short_name", "issuing_body", "url")
    )


def _eu_case_id(text: str) -> str | None:
    match = _CASE_RE.search(text)
    if match:
        return f"eu-cjeu-c-{int(match.group(1))}-{match.group(2)}"

    celex = _CELEX_CASE_RE.search(text)
    if celex:
        year = celex.group(1)
        return f"eu-cjeu-c-{int(celex.group(2))}-{year[-2:]}"

    return None


def _match_reference(pattern: re.Pattern[str], raw_text: str, template: str) -> str | None:
    match = pattern.search(raw_text)
    if not match:
        return None
    return template.format(*[slugify(group, max_length=24) for group in match.groups()])


def _known_jurisdiction_id(jurisdiction: str, raw_text: str, text: str) -> str | None:
    """Map known regulatory references to stable jurisdiction-specific IDs."""
    if jurisdiction == "uk":
        if ref := _match_reference(_PRA_SS_RE, raw_text, "uk-pra-ss-{0}-{1}"):
            return ref
        if ref := _match_reference(_PRA_PS_RE, raw_text, "uk-pra-ps-{0}-{1}"):
            return ref
        if "consumer duty" in text:
            return "uk-fca-consumer-duty"
        if "sysc" in text:
            return "uk-fca-sysc"
        if "smcr" in text or "senior managers" in text:
            return "uk-smcr"
        if "fca ai update" in text or ("fca" in text and "artificial intelligence" in text):
            return "uk-fca-ai-update"

    if jurisdiction == "usa":
        if ref := _match_reference(_OCC_BULLETIN_RE, raw_text, "usa-occ-{0}-{1}"):
            return ref
        if ref := _match_reference(_FED_SR_RE, raw_text, "usa-fed-sr-{0}-{1}"):
            return ref
        if "nydfs" in text and "cyber" in text and "ai" in text:
            return "usa-nydfs-ai-cybersecurity-guidance"
        if "treasury" in text and "ai" in text and "risk management" in text:
            return "usa-treasury-ai-risk-management-framework"
        if "colorado ai act" in text:
            return "usa-colorado-ai-act"
        if "nyc ll144" in text or "local law 144" in text:
            return "usa-nyc-ll144"
        if "ecoa" in text or "equal credit opportunity act" in text:
            return "usa-ecoa"
        if "fcra" in text or "fair credit reporting act" in text:
            return "usa-fcra"
        if "cfpb" in text and ("ai" in text or "algorithm" in text):
            return "usa-cfpb-ai-fair-lending"

    if jurisdiction == "singapore":
        if ref := _match_reference(_MAS_NOTICE_RE, raw_text, "singapore-mas-notice-{0}"):
            return ref
        if "mas" in text and "feat" in text:
            return "singapore-mas-feat"
        if "veritas" in text:
            return "singapore-mas-veritas"
        if "technology risk management" in text or "trm guidelines" in text:
            return "singapore-mas-trm-guidelines"
        if "pdpa" in text or "personal data protection act" in text:
            return "singapore-pdpa"
        if "ai model risk management" in text and "mas" in text:
            return "singapore-mas-ai-model-risk-paper"

    if jurisdiction == "switzerland":
        if ref := _match_reference(_FINMA_GUIDANCE_RE, raw_text, "switzerland-finma-guidance-{0}-{1}"):
            return ref
        if ref := _match_reference(_FINMA_CIRCULAR_RE, raw_text, "switzerland-finma-circular-{0}-{1}"):
            return ref
        if "finma" in text and "artificial intelligence" in text:
            return "switzerland-finma-ai-guidance"

    if jurisdiction == "global_standards":
        if "bcbs" in text and "ai" in text:
            return "global-bcbs-ai-newsletter"
        if "fsb" in text and "financial stability" in text and "ai" in text:
            return "global-fsb-ai-financial-stability"
        if "pillar 2" in text or "icaap" in text:
            return "global-bcbs-pillar-2-icaap"

    if jurisdiction == "australia":
        if ref := _match_reference(_APRA_CPS_RE, raw_text, "australia-apra-cps-{0}"):
            return ref
        if ref := _match_reference(_APRA_CPG_RE, raw_text, "australia-apra-cpg-{0}"):
            return ref
        if "apra" in text and "ai" in text:
            return "australia-apra-ai-governance"

    if jurisdiction == "hong_kong":
        if "c raf" in text or "cyber resilience assessment framework" in text:
            return "hong-kong-hkma-c-raf"
        if "virtual bank" in text:
            return "hong-kong-hkma-virtual-bank-guidelines"
        if "hkma" in text and "ai" in text:
            return "hong-kong-hkma-ai-guidance"

    if jurisdiction == "india":
        if "master direction" in text and "it governance" in text:
            return "india-rbi-master-direction-it-governance"
        if "cyber security framework" in text:
            return "india-rbi-cyber-security-framework"
        if "sebi" in text and "ai" in text:
            return "india-sebi-ai-guidance"
        if "rbi" in text and "ai" in text:
            return "india-rbi-ai-guidance"

    if jurisdiction == "brazil":
        match = _BRAZIL_RESOLUTION_RE.search(raw_text)
        if match:
            number = re.sub(r"\D", "", match.group(2))
            return f"brazil-{slugify(match.group(1), max_length=8)}-resolution-{number}-{match.group(3)}"
        if "bcb" in text and "ai" in text:
            return "brazil-bcb-ai-governance"

    if jurisdiction == "uae":
        if "dfsa" in text and "technology rules" in text:
            return "uae-dfsa-technology-rules"
        if "uae ai strategy 2031" in text:
            return "uae-ai-strategy-2031"
        if "cbuae" in text and "ai" in text:
            return "uae-cbuae-ai-guidance"

    if jurisdiction == "japan":
        if "fsa" in text and "ai governance" in text:
            return "japan-fsa-ai-governance-guidelines"

    if jurisdiction == "austria":
        if "fma" in text and "it guideline" in text:
            return "austria-fma-it-guidelines"
        if "dora" in text or "digital operational resilience" in text:
            return "austria-reg-2022-2554"
        if "ai act" in text:
            return "austria-reg-2024-1689"

    if jurisdiction == "luxembourg":
        if "cssf circular 20 750" in text or "circular 20/750" in raw_text.lower():
            return "luxembourg-cssf-circular-20-750"
        if "dora" in text or "digital operational resilience" in text:
            return "luxembourg-reg-2022-2554"
        if "ai act" in text:
            return "luxembourg-reg-2024-1689"

    if jurisdiction == "canada":
        if ref := _match_reference(_OSFI_GUIDELINE_RE, raw_text, "canada-osfi-guideline-{0}-{1}"):
            return ref
        if "artificial intelligence and data act" in text or "aida" in text:
            return "canada-aida"
        if "osfi" in text and "cyber incident" in text:
            return "canada-osfi-cyber-incident-risk"
        if "osfi" in text and "ai" in text:
            return "canada-osfi-ai-guidance"

    if jurisdiction == "korea_south":
        if "fsc" in text and "ai" in text:
            return "korea-south-fsc-ai-utilization-guidelines"

    return None


def stable_regulation_id(data: dict[str, Any]) -> str:
    """Generate a deterministic regulation ID from authoritative identity signals."""
    jurisdiction = slugify(data.get("jurisdiction_id") or "unknown", max_length=24)
    raw_text = _text_blob(data)
    text = normalize_text(raw_text)
    url = canonical_url(data.get("url"))
    combined = f"{raw_text} {url}"

    if jurisdiction == "eu":
        eli_reg = _ELI_REG_RE.search(url)
        if eli_reg:
            return f"eu-reg-{eli_reg.group(1)}-{int(eli_reg.group(2))}"

        regulation = _REGULATION_EU_RE.search(raw_text)
        if regulation:
            return f"eu-reg-{regulation.group(1)}-{int(regulation.group(2))}"

        case_id = _eu_case_id(combined)
        if case_id:
            return case_id

        if "ai act" in text:
            return "eu-reg-2024-1689"
        if "dora" in text or "digital operational resilience" in text:
            return "eu-reg-2022-2554"
        if "gdpr" in text or "general data protection regulation" in text:
            return "eu-reg-2016-679"
        if "ecb guide to internal models" in text or "guide to internal models" in text:
            return "eu-ecb-guide-internal-models"

    if known_id := _known_jurisdiction_id(jurisdiction, raw_text, text):
        return known_id

    name = data.get("name") or data.get("short_name") or data.get("regulation_id")
    return f"{jurisdiction}-{slugify(name)}"


def canonical_match_keys(data: dict[str, Any]) -> set[str]:
    """Return deterministic keys used to match findings to existing rows."""
    keys = {f"id:{stable_regulation_id(data)}"}

    if data.get("regulation_id"):
        keys.add(f"id:{data['regulation_id']}")

    url = canonical_url(data.get("url"))
    if url:
        keys.add(f"url:{url}")

    name = normalize_text(data.get("name"))
    if name:
        keys.add(f"name:{name}")

    short_name = normalize_text(data.get("short_name"))
    if short_name:
        keys.add(f"short:{short_name}")

    return keys
