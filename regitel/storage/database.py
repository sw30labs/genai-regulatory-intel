"""SQLite database layer — SQLAlchemy ORM models and session management.

Schema v2: GenAI governance domain (replaces pentest-focused v1).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class JurisdictionRow(Base):
    __tablename__ = "jurisdictions"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    region = Column(String, nullable=False)
    regulatory_bodies = Column(Text, default="[]")  # JSON
    research_priority = Column(Integer, default=5)
    last_researched_at = Column(DateTime, nullable=True)

    regulations = relationship("RegulationRow", back_populates="jurisdiction")


class RegulationRow(Base):
    __tablename__ = "regulations"

    id = Column(String, primary_key=True)
    jurisdiction_id = Column(String, ForeignKey("jurisdictions.id"), nullable=False)
    name = Column(String, nullable=False)
    short_name = Column(String, nullable=True)
    issuing_body = Column(String, nullable=True)
    regulation_type = Column(String, default="guideline")
    status = Column(String, default="active")
    effective_date = Column(Date, nullable=True)
    version = Column(String, nullable=True)
    url = Column(String, nullable=True)
    supersedes_id = Column(String, ForeignKey("regulations.id"), nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    confidence_score = Column(Float, default=0.0)
    ai_specific = Column(Boolean, default=False)
    governance_themes = Column(Text, default="[]")  # JSON list of theme tags

    jurisdiction = relationship("JurisdictionRow", back_populates="regulations")
    ai_governance_requirements = relationship("AIGovernanceRequirementRow", back_populates="regulation")
    ai_control_frameworks = relationship("AIControlFrameworkRow", back_populates="regulation")
    source_documents = relationship("SourceDocumentRow", back_populates="regulation")
    change_log_entries = relationship("ChangeLogRow", back_populates="regulation")


class AIGovernanceRequirementRow(Base):
    __tablename__ = "ai_governance_requirements"

    id = Column(String, primary_key=True)
    regulation_id = Column(String, ForeignKey("regulations.id"), nullable=False)
    requirement_type = Column(String, nullable=False)
    governance_scope = Column(Text, default="[]")  # JSON list
    entity_types = Column(Text, default="[]")  # JSON list
    risk_tier = Column(String, nullable=True)
    mandatory = Column(Boolean, default=True)
    applicable_to_deployers = Column(Boolean, default=True)
    applicable_to_providers = Column(Boolean, default=False)
    key_controls = Column(Text, default="[]")  # JSON list
    penalties = Column(String, nullable=True)
    effective_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())

    regulation = relationship("RegulationRow", back_populates="ai_governance_requirements")


class AIControlFrameworkRow(Base):
    __tablename__ = "ai_control_frameworks"

    id = Column(String, primary_key=True)
    regulation_id = Column(String, ForeignKey("regulations.id"), nullable=False)
    framework_name = Column(String, nullable=False)
    control_categories = Column(Text, default="[]")  # JSON list
    risk_tiers = Column(Text, default="[]")  # JSON list
    inventory_required = Column(Boolean, default=False)
    explainability_required = Column(Boolean, default=False)
    human_overview_required = Column(Boolean, default=False)
    data_governance_required = Column(Boolean, default=False)
    third_party_assessment = Column(Boolean, default=False)
    binding = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    regulation = relationship("RegulationRow", back_populates="ai_control_frameworks")


class SourceDocumentRow(Base):
    __tablename__ = "source_documents"

    id = Column(String, primary_key=True)
    regulation_id = Column(String, ForeignKey("regulations.id"), nullable=False)
    file_path = Column(String, nullable=True)
    url = Column(String, nullable=True)
    document_type = Column(String, default="regulation_text")
    ingested_at = Column(DateTime, nullable=True)
    file_hash = Column(String, nullable=True)
    page_count = Column(Integer, nullable=True)
    vector_collection = Column(String, nullable=True)

    regulation = relationship("RegulationRow", back_populates="source_documents")


class ChangeLogRow(Base):
    __tablename__ = "change_log"

    id = Column(String, primary_key=True)
    regulation_id = Column(String, ForeignKey("regulations.id"), nullable=False)
    detected_at = Column(DateTime, default=func.now())
    change_type = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    details = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)
    reviewed = Column(Boolean, default=False)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    regulation = relationship("RegulationRow", back_populates="change_log_entries")


class ResearchRunRow(Base):
    __tablename__ = "research_runs"

    id = Column(String, primary_key=True)
    started_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    jurisdictions_scanned = Column(Text, default="[]")  # JSON
    status = Column(String, default="running")
    regulations_found = Column(Integer, default=0)
    regulations_updated = Column(Integer, default=0)
    reflection_iterations = Column(Integer, default=0)
    confidence_score = Column(Float, nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cached_input_tokens = Column(Integer, default=0)
    reasoning_tokens = Column(Integer, default=0)
    llm_calls = Column(Integer, default=0)
    web_search_calls = Column(Integer, default=0)
    error_log = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Database Manager
# ---------------------------------------------------------------------------

class DatabaseManager:
    """Manages SQLite database lifecycle and sessions."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self._session_factory = sessionmaker(bind=self.engine)

    def init_db(self) -> None:
        """Create all tables."""
        Base.metadata.create_all(self.engine)
        self._ensure_research_run_usage_columns()

    def _ensure_research_run_usage_columns(self) -> None:
        """Add token usage columns to existing databases."""
        inspector = inspect(self.engine)
        if "research_runs" not in inspector.get_table_names():
            return

        existing = {column["name"] for column in inspector.get_columns("research_runs")}
        usage_columns = {
            "input_tokens": "INTEGER DEFAULT 0",
            "output_tokens": "INTEGER DEFAULT 0",
            "total_tokens": "INTEGER DEFAULT 0",
            "cached_input_tokens": "INTEGER DEFAULT 0",
            "reasoning_tokens": "INTEGER DEFAULT 0",
            "llm_calls": "INTEGER DEFAULT 0",
            "web_search_calls": "INTEGER DEFAULT 0",
        }

        with self.engine.begin() as conn:
            for name, ddl in usage_columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE research_runs ADD COLUMN {name} {ddl}"))

    def drop_db(self) -> None:
        """Drop all tables (destructive)."""
        Base.metadata.drop_all(self.engine)

    def get_session(self) -> Session:
        """Create a new database session."""
        return self._session_factory()

    # -- Convenience methods ------------------------------------------------

    def get_stats(self) -> dict:
        """Return counts of all major entities."""
        with self.get_session() as session:
            return {
                "jurisdictions": session.query(JurisdictionRow).count(),
                "regulations": session.query(RegulationRow).count(),
                "ai_governance_requirements": session.query(AIGovernanceRequirementRow).count(),
                "ai_control_frameworks": session.query(AIControlFrameworkRow).count(),
                "source_documents": session.query(SourceDocumentRow).count(),
                "change_log_entries": session.query(ChangeLogRow).count(),
                "research_runs": session.query(ResearchRunRow).count(),
            }

    def upsert_jurisdiction(self, session: Session, **kwargs) -> JurisdictionRow:
        """Insert or update a jurisdiction."""
        row = session.get(JurisdictionRow, kwargs["id"])
        if row:
            for k, v in kwargs.items():
                setattr(row, k, v)
        else:
            row = JurisdictionRow(**kwargs)
            session.add(row)
        return row

    def get_jurisdictions(self, session: Session) -> list[JurisdictionRow]:
        """Return all jurisdictions, ordered by priority."""
        return (
            session.query(JurisdictionRow)
            .order_by(JurisdictionRow.research_priority)
            .all()
        )

    def get_regulations_by_jurisdiction(
        self, session: Session, jurisdiction_id: str
    ) -> list[RegulationRow]:
        """Return all regulations for a jurisdiction."""
        return (
            session.query(RegulationRow)
            .filter(RegulationRow.jurisdiction_id == jurisdiction_id)
            .order_by(RegulationRow.name)
            .all()
        )

    def get_recent_changes(
        self, session: Session, since: Optional[datetime] = None, limit: int = 50
    ) -> list[ChangeLogRow]:
        """Return recent changelog entries."""
        q = session.query(ChangeLogRow).order_by(ChangeLogRow.detected_at.desc())
        if since:
            q = q.filter(ChangeLogRow.detected_at >= since)
        return q.limit(limit).all()

    def get_ai_specific_regulations(self, session: Session) -> list[RegulationRow]:
        """Return regulations that are genuinely AI-specific."""
        return (
            session.query(RegulationRow)
            .filter(RegulationRow.ai_specific.is_(True))
            .order_by(RegulationRow.name)
            .all()
        )

    def get_applied_regulations(self, session: Session) -> list[RegulationRow]:
        """Return existing rules being applied to AI by analogy."""
        return (
            session.query(RegulationRow)
            .filter(RegulationRow.ai_specific.is_(False))
            .order_by(RegulationRow.name)
            .all()
        )
