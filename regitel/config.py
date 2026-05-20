"""Configuration loader — reads regitel.yaml and environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

class LLMEndpointConfig(BaseModel):
    """OpenAI Responses API endpoint config."""
    base_url: Optional[str] = Field(
        default=None,
        description="Optional OpenAI-compatible base URL override",
    )
    api_key: str = Field(
        default="${OPENAI_API_KEY}",
        description="OpenAI API key",
    )
    model: str = Field(
        default="${OPENAI_MODEL}",
        description="OpenAI Responses model (e.g. gpt-5.5)",
    )
    temperature: Optional[float] = None
    max_tokens: int = 4096


class EmbeddingConfig(BaseModel):
    """Local embedding model config (sentence-transformers)."""
    model: str = "all-MiniLM-L6-v2"


class StorageConfig(BaseModel):
    database: str = "~/.regitel/data/regitel.db"
    chroma_path: str = "~/.regitel/data/chroma"
    documents_path: str = "~/.regitel/data/documents"

    def resolve_paths(self) -> "StorageConfig":
        """Expand ~ and resolve all paths."""
        from pathlib import Path
        return StorageConfig(
            database=str(Path(self.database).expanduser()),
            chroma_path=str(Path(self.chroma_path).expanduser()),
            documents_path=str(Path(self.documents_path).expanduser()),
        )


class ResearchConfig(BaseModel):
    max_reflection_iterations: int = 3
    confidence_threshold: float = 0.75
    search_provider: str = "openai"
    max_search_results_per_query: int = 10


class RegulatoryBodyProfile(BaseModel):
    name: str
    acronym: Optional[str] = None
    url: Optional[str] = None


class JurisdictionProfile(BaseModel):
    name: str
    region: str
    regulatory_bodies: list[RegulatoryBodyProfile] = Field(default_factory=list)
    key_regulations: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)


class RegitelConfig(BaseModel):
    """Top-level configuration for the RegIntel system."""

    llm: LLMEndpointConfig = Field(default_factory=LLMEndpointConfig)

    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)

    jurisdiction_priorities: dict[str, list[str]] = Field(default_factory=lambda: {
        "priority_1": ["eu", "uk", "usa", "singapore", "hong_kong"],
        "priority_2": ["australia", "switzerland", "brazil", "india"],
        "priority_3": [
            "austria", "luxembourg", "cayman_islands", "jersey",
            "taiwan", "korea_south", "monaco", "bahamas", "uae",
        ],
    })

    jurisdiction_profiles: dict[str, JurisdictionProfile] = Field(default_factory=dict)

    @property
    def all_jurisdictions(self) -> list[str]:
        """Return a flat list of all jurisdiction IDs, ordered by priority."""
        result = []
        for key in sorted(self.jurisdiction_priorities.keys()):
            result.extend(self.jurisdiction_priorities[key])
        return result


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATHS = [
    Path("regitel.yaml"),
    Path("regitel.yml"),
    Path.home() / ".config" / "regitel" / "regitel.yaml",
]


def _resolve_env(value: Any) -> Any:
    """Replace ${ENV_VAR} placeholders with environment variable values."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def load_config(config_path: Optional[str | Path] = None) -> RegitelConfig:
    """Load configuration from YAML file, falling back to defaults."""

    path: Optional[Path] = None
    if config_path:
        path = Path(config_path)
    else:
        for candidate in _DEFAULT_CONFIG_PATHS:
            if candidate.exists():
                path = candidate
                break

    if path and path.exists():
        raw = yaml.safe_load(path.read_text()) or {}
        raw = _resolve_env(raw)
    else:
        raw = {}

    # Map YAML structure to flat model
    cfg = {}

    if "llm" in raw:
        cfg["llm"] = raw["llm"]

    for key in ("embedding", "storage", "research",
                "jurisdiction_priorities", "jurisdiction_profiles"):
        if key in raw:
            cfg[key] = raw[key]

    config = RegitelConfig(**cfg)
    # Resolve ~ in storage paths
    config.storage = config.storage.resolve_paths()
    return config
