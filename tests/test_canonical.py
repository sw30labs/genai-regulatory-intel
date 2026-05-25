"""Tests for canonical regulation identity."""

from regitel.utils.canonical import canonical_url, stable_regulation_id


def test_stable_id_uses_eu_regulation_number_from_url():
    finding = {
        "jurisdiction_id": "eu",
        "regulation_id": "eu-ai-act-art-50",
        "name": "Regulation (EU) 2024/1689 laying down harmonised rules on AI",
        "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng",
    }

    assert stable_regulation_id(finding) == "eu-reg-2024-1689"


def test_stable_id_maps_dora_alias_to_regulation_number():
    finding = {
        "jurisdiction_id": "eu",
        "regulation_id": "eu-dora-ctpp-designation-2025",
        "name": "DORA Article 31(9) List of designated critical ICT third-party providers",
        "short_name": "DORA CTPP designation",
    }

    assert stable_regulation_id(finding) == "eu-reg-2022-2554"


def test_stable_id_uses_cjeu_case_number():
    finding = {
        "jurisdiction_id": "eu",
        "name": "Judgment of the Court, Case C-634/21, SCHUFA Holding",
    }

    assert stable_regulation_id(finding) == "eu-cjeu-c-634-21"


def test_canonical_url_removes_language_suffix_and_fragment():
    assert canonical_url("https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng#top") == (
        "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"
    )


def test_stable_id_maps_uk_pra_supervisory_statement():
    assert stable_regulation_id({
        "jurisdiction_id": "uk",
        "name": "PRA SS1/23 Model Risk Management",
    }) == "uk-pra-ss-1-23"


def test_stable_id_maps_us_official_references():
    assert stable_regulation_id({
        "jurisdiction_id": "usa",
        "name": "OCC Bulletin 2026-13 / Fed SR 26-2 model risk management",
    }) == "usa-occ-2026-13"


def test_stable_id_maps_singapore_mas_notice():
    assert stable_regulation_id({
        "jurisdiction_id": "singapore",
        "name": "MAS Notice 658 Technology Risk Management",
    }) == "singapore-mas-notice-658"


def test_stable_id_maps_switzerland_finma_guidance():
    assert stable_regulation_id({
        "jurisdiction_id": "switzerland",
        "name": "FINMA Guidance 08/2024 AI in financial services",
    }) == "switzerland-finma-guidance-08-2024"


def test_stable_id_maps_australia_apra_standard():
    assert stable_regulation_id({
        "jurisdiction_id": "australia",
        "name": "APRA CPS 234 Information Security",
    }) == "australia-apra-cps-234"


def test_stable_id_maps_brazil_resolution():
    assert stable_regulation_id({
        "jurisdiction_id": "brazil",
        "name": "CMN Resolution 5,274/2025",
    }) == "brazil-cmn-resolution-5274-2025"
