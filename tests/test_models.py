"""Tests for domain models."""

from datetime import date

from regitel.models.domain import (
    AIControlFramework,
    AIGovernanceRequirement,
    AIGovernanceScope,
    EntityType,
    RequirementType,
    RiskTier,
)


class TestAIGovernanceRequirement:
    def test_create(self):
        req = AIGovernanceRequirement(
            id="req-001",
            regulation_id="eu-2026-001",
            requirement_type=RequirementType.MODEL_RISK_MANAGEMENT,
            governance_scope=[AIGovernanceScope.CREDIT_UNDERWRITING, AIGovernanceScope.RISK_MODELING],
            entity_types=[EntityType.BANK, EntityType.CREDIT_UNION],
            risk_tier=RiskTier.HIGH_RISK,
            mandatory=True,
            applicable_to_deployers=True,
            applicable_to_providers=False,
            key_controls=["model_validation", "second_line_review", "bias_testing"],
            penalties="Fines up to 5% of annual revenue",
            effective_date=date(2026, 6, 1),
            notes="Gen AI must be included in existing MRM frameworks",
        )
        assert req.requirement_type == RequirementType.MODEL_RISK_MANAGEMENT
        assert req.entity_types == [EntityType.BANK, EntityType.CREDIT_UNION]
        assert req.risk_tier == RiskTier.HIGH_RISK
        assert req.mandatory is True

    def test_defaults(self):
        req = AIGovernanceRequirement(
            id="req-002",
            regulation_id="eu-2026-002",
            requirement_type=RequirementType.GENERAL,
            governance_scope=[],
            entity_types=[EntityType.ALL],
        )
        assert req.risk_tier is None
        assert req.mandatory is True
        assert req.applicable_to_deployers is True
        assert req.applicable_to_providers is False


class TestAIControlFramework:
    def test_create(self):
        fw = AIControlFramework(
            id="fw-001",
            regulation_id="eu-2026-001",
            framework_name="Gen AI Control Framework",
            control_categories=["risk_classification", "inventory_management"],
            risk_tiers=["high_risk", "limited_risk"],
            inventory_required=True,
            explainability_required=True,
            human_overview_required=True,
            data_governance_required=True,
            third_party_assessment=True,
            binding=True,
        )
        assert fw.inventory_required is True
        assert fw.explainability_required is True
        assert fw.binding is True


class TestRiskTier:
    def test_values(self):
        assert RiskTier.PROHIBITED == "prohibited"
        assert RiskTier.HIGH_RISK == "high_risk"
        assert RiskTier.LIMITED_RISK == "limited_risk"
        assert RiskTier.MINIMAL_RISK == "minimal_risk"


class TestRequirementType:
    def test_values(self):
        assert RequirementType.MODEL_RISK_MANAGEMENT == "model_risk_management"
        assert RequirementType.DATA_RESIDENCY == "data_residency"
        assert RequirementType.AI_INVENTORY == "ai_inventory"
        assert RequirementType.EXPLAINABILITY == "explainability"
        assert RequirementType.THIRD_PARTY_RISK == "third_party_risk"
        assert RequirementType.TRANSPARENCY_DISCLOSURE == "transparency_disclosure"
        assert RequirementType.HUMAN_OVERVIEW == "human_overview"
        assert RequirementType.FAIR_LENDING_AI == "fair_lending_ai"
        assert RequirementType.AUTOMATED_DECISION_MAKING == "automated_decision_making"
        assert RequirementType.ICT_THIRD_PARTY == "ict_third_party"
        assert RequirementType.SECURITY_CONTROLS == "security_controls"
        assert RequirementType.GENERAL == "general"
