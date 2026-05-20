"""Domain models — Pydantic schemas for all RegIntel entities.

Domain: Generative AI / Agentic AI governance for Tier 1 banks.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Region(str, enum.Enum):
    EU = "eu"
    APAC = "apac"
    AMERICAS = "americas"
    MEA = "mea"
    GLOBAL = "global"


class RegulationStatus(str, enum.Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    PROPOSED = "proposed"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


class RegulationType(str, enum.Enum):
    LAW = "law"
    GUIDELINE = "guideline"
    FRAMEWORK = "framework"
    STANDARD = "standard"
    CIRCULAR = "circular"
    NOTICE = "notice"
    DIRECTIVE = "directive"


class RequirementType(str, enum.Enum):
    """GenAI governance requirement categories."""
    MODEL_RISK_MANAGEMENT = "model_risk_management"
    DATA_RESIDENCY = "data_residency"
    AI_INVENTORY = "ai_inventory"
    EXPLAINABILITY = "explainability"
    THIRD_PARTY_RISK = "third_party_risk"
    TRANSPARENCY_DISCLOSURE = "transparency_disclosure"
    HUMAN_OVERVIEW = "human_overview"
    FAIR_LENDING_AI = "fair_lending_ai"
    AUTOMATED_DECISION_MAKING = "automated_decision_making"
    ICT_THIRD_PARTY = "ict_third_party"
    SECURITY_CONTROLS = "security_controls"
    GENERAL = "general"


class AIGovernanceScope(str, enum.Enum):
    """Business domains where GenAI governance applies."""
    CREDIT_UNDERWRITING = "credit_underwriting"
    CUSTOMER_FACING = "customer_facing"
    INTERNAL_PRODUCTIVITY = "internal_productivity"
    RISK_MODELING = "risk_modeling"
    COMPLIANCE_MONITORING = "compliance_monitoring"
    ANTI_MONEY_LAUNDERING = "anti_money_laundering"
    TRADING_INVESTMENT = "trading_investment"
    RECRUITMENT_HIRING = "recruitment_hiring"
    MARKETING_COMMUNICATIONS = "marketing_communications"
    KNOW_YOUR_CUSTOMER = "know_your_customer"
    ALL = "all"


class RiskTier(str, enum.Enum):
    """AI risk classification tiers (aligned with EU AI Act taxonomy)."""
    PROHIBITED = "prohibited"
    HIGH_RISK = "high_risk"
    LIMITED_RISK = "limited_risk"
    MINIMAL_RISK = "minimal_risk"


class EntityType(str, enum.Enum):
    BANK = "bank"
    INSURER = "insurer"
    PAYMENT_PROCESSOR = "payment_processor"
    FMI = "fmi"  # Financial Market Infrastructure
    FINTECH = "fintech"
    INVESTMENT_FIRM = "investment_firm"
    PENSION_FUND = "pension_fund"
    CREDIT_UNION = "credit_union"
    ALL = "all"


class ChangeType(str, enum.Enum):
    NEW = "new"
    UPDATED = "updated"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"
    DEADLINE_APPROACHING = "deadline_approaching"


class DocumentType(str, enum.Enum):
    REGULATION_TEXT = "regulation_text"
    GUIDANCE = "guidance"
    FRAMEWORK = "framework"
    CIRCULAR = "circular"
    REPORT = "report"
    RESEARCH_BASELINE = "research_baseline"


# ---------------------------------------------------------------------------
# Core Domain Models
# ---------------------------------------------------------------------------

class RegulatoryBody(BaseModel):
    """A regulatory authority that issues regulations."""
    name: str
    acronym: Optional[str] = None
    url: Optional[str] = None
    jurisdiction_id: Optional[str] = None


class Jurisdiction(BaseModel):
    """A country or region with its own regulatory framework."""
    id: str = Field(..., description="Lowercase slug, e.g. 'eu', 'singapore'")
    name: str = Field(..., description="Display name, e.g. 'European Union'")
    region: Region
    regulatory_bodies: list[RegulatoryBody] = Field(default_factory=list)
    research_priority: int = Field(default=5, ge=1, le=10, description="1=highest")
    last_researched_at: Optional[datetime] = None


class Regulation(BaseModel):
    """A specific regulation, law, guideline, or framework relevant to GenAI governance."""
    id: str = Field(..., description="Deterministic slug, e.g. 'eu-ai-act'")
    jurisdiction_id: str
    name: str
    short_name: Optional[str] = None
    issuing_body: Optional[str] = None
    regulation_type: RegulationType = RegulationType.GUIDELINE
    status: RegulationStatus = RegulationStatus.ACTIVE
    effective_date: Optional[date] = None
    version: Optional[str] = None
    url: Optional[str] = None
    supersedes_id: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    ai_specific: bool = Field(
        default=False,
        description="True if this regulation is genuinely AI-specific; false if it's existing rules applied to AI by analogy",
    )
    governance_themes: list[str] = Field(
        default_factory=list,
        description="Tags for governance themes: model_risk, data_residency, third_party_risk, explainability, etc.",
    )


class AIGovernanceRequirement(BaseModel):
    """A specific GenAI governance requirement extracted from a regulation."""
    id: str
    regulation_id: str
    requirement_type: RequirementType
    governance_scope: list[AIGovernanceScope] = Field(default_factory=list)
    entity_types: list[EntityType] = Field(default_factory=list)
    risk_tier: Optional[RiskTier] = None
    mandatory: bool = True
    applicable_to_deployers: bool = Field(
        default=True,
        description="Does this requirement apply to banks deploying AI?",
    )
    applicable_to_providers: bool = Field(
        default=False,
        description="Does this requirement apply to foundation model providers?",
    )
    key_controls: list[str] = Field(
        default_factory=list,
        description="Specific controls, e.g. 'geolocation guarantee', 'AI inventory', 'human review'",
    )
    penalties: Optional[str] = None
    effective_date: Optional[date] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIControlFramework(BaseModel):
    """A governance framework or control structure for AI systems (e.g., EU AI Act, MRM, FINMA inventory)."""
    id: str
    regulation_id: str
    framework_name: str
    control_categories: list[str] = Field(
        default_factory=list,
        description="Categories of controls: governance, technical, operational, contractual",
    )
    risk_tiers: list[str] = Field(
        default_factory=list,
        description="Risk tiers defined by the framework: prohibited, high_risk, limited_risk, minimal",
    )
    inventory_required: bool = False
    explainability_required: bool = False
    human_overview_required: bool = False
    data_governance_required: bool = False
    third_party_assessment: bool = False
    binding: bool = Field(
        default=True,
        description="Is this legally binding vs. supervisory guidance/expectation?",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SourceDocument(BaseModel):
    """A source document (PDF, web page) associated with a regulation."""
    id: str
    regulation_id: str
    file_path: Optional[str] = None
    url: Optional[str] = None
    document_type: DocumentType = DocumentType.REGULATION_TEXT
    ingested_at: Optional[datetime] = None
    file_hash: Optional[str] = None
    page_count: Optional[int] = None
    vector_collection: Optional[str] = None


class ChangeLogEntry(BaseModel):
    """A detected change to a regulation."""
    id: str
    regulation_id: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    change_type: ChangeType
    summary: str
    details: Optional[str] = None
    source_url: Optional[str] = None
    reviewed: bool = False
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None


class ResearchRun(BaseModel):
    """Metadata for a research workflow execution."""
    id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    jurisdictions_scanned: list[str] = Field(default_factory=list)
    status: str = "running"
    regulations_found: int = 0
    regulations_updated: int = 0
    reflection_iterations: int = 0
    confidence_score: Optional[float] = None
    error_log: Optional[str] = None
