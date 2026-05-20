# RegIntel-AgenticAI — GenAI Regulatory Intelligence for Tier 1 Financial Services Organizations

> Autonomous regulatory intelligence platform for tracking, extracting, and comparing GenAI regulations across global financial jurisdictions.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![OpenAI](https://img.shields.io/badge/OpenAI-Responses%20API-black.svg)](https://platform.openai.com/docs/guides/responses)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Tests](https://img.shields.io/badge/Tests-42-green.svg)](tests/)

RegIntel-AgenticAI is a CLI tool that uses OpenAI Responses API agents to autonomously research, extract, and compare **GenAI regulations** across global financial services jurisdictions. Built for Tier 1 banks navigating the fast-evolving regulatory landscape around generative AI — from the EU AI Act to US state-level AI laws and APAC frameworks.

## ✨ Features

- 🔍 **Autonomous Regulatory Research** — AI agents search, extract, and validate GenAI-specific regulations from global regulators
- 🌍 **16 Priority Jurisdictions** — EU, UK, USA (NY, CO, TX), Singapore, HK, China, Australia, Switzerland, and more
- 🧠 **4-Agent State Machine** — Research → Validate → Reflect → Persist (LangGraph)
- 💾 **Hybrid Storage** — SQLite (structured) + ChromaDB (semantic search)
- 📊 **Comparison Matrices** — Side-by-side GenAI regulatory requirements across regions
- 🔎 **Gap Analysis** — Identify uncovered regulatory themes across jurisdictions
- 🧪 **Model Risk Coverage** — Track MRM applicability to GenAI across regulators
- 🔎 **Hosted Web Search** — Uses OpenAI Responses API web search for current regulatory sources
- 📈 **Token Usage Tracking** — Stores input, output, reasoning, and cached token totals per research run

## Quick Start

```bash
# Clone and install
git clone https://github.com/yourusername/regitel.git
cd regitel
pip install -e .

# Configure OpenAI
cp .env.example .env
# Edit .env:
#   - Set OPENAI_API_KEY
#   - Set OPENAI_MODEL to the Responses model you want to use

# First run — initialize databases, download embedding model, and seed jurisdictions
regitel db init --seed

# Scan regulations for priority jurisdictions
regitel scan --all

# Natural language query
regitel query semantic "GenAI model risk management requirements for banks"

# System health check
regitel doctor
```

## Commands

| Command | Description |
|---|---|
| `regitel db init --seed` | Initialize database and seed jurisdiction profiles |
| `regitel scan -j eu` | Research GenAI regulations for a jurisdiction |
| `regitel scan --all` | Scan all jurisdictions |
| `regitel query search -t "AI Act"` | Structured text search |
| `regitel query semantic "model risk for Gen AI"` | Natural language search |
| `regitel query compare eu usa singapore` | Side-by-side comparison |
| `regitel gaps` | Governance coverage gap analysis |
| `regitel matrix eu usa` | Gen AI governance matrix |
| `regitel export json --ai-specific-only` | Export AI-specific regs only |
| `regitel doctor` | Health checks |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     RegIntel CLI                        │
│  (Click + Rich)                                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Research Agent ──→ OpenAI Responses Web Search         │
│       ↓                                                  │
│  Validator Agent                                         │
│       ↓                                                  │
│  Reflection Agent (quality gate, hallucination check)   │
│       ↓                                                  │
│  Persister Agent (SQLite + ChromaDB)                    │
│                                                         │
│  └── LLM inference via OpenAI Responses API             │
│  └── Embeddings via sentence-transformers (on-device)   │
└─────────────────────────────────────────────────────────┘
```

Live research uses OpenAI for both LLM inference and hosted web search. Embeddings run locally via sentence-transformers.

## GenAI Regulatory Domain Coverage

| Theme | What's Tracked |
|---|---|
| Model Risk Management | SR 11-7 / SR 19-13 applicability to GenAI models |
| Data Residency & Geolocation | Where GenAI model data/outputs can be stored |
| AI Inventory & Classification | Mandatory registries of GenAI/AI systems |
| Explainability & Transparency | Regulatory requirements for GenAI output explainability |
| Human Oversight & Control | Human-in-the-loop mandates for GenAI decision-making |
| Fair Lending & AI | UDAP / ECOA compliance for GenAI in lending |
| Automated Decision-Making | ADADRA, CFPB consent decrees on AI/GenAI decisions |
| ICT Third-Party Risk | DORA, FFIEC guidance on GenAI vendors and model supply chains |
| Security Controls | Mandatory vs recommended cybersecurity controls for GenAI systems |

## Tech Stack

| Component | Technology |
|---|---|
| LLM Inference | OpenAI Responses API |
| Embeddings | **sentence-transformers** (all-MiniLM-L6-v2) |
| Agent Orchestration | LangGraph (StateGraph) |
| Web Search | OpenAI Responses hosted web search |
| Structured Storage | SQLite (SQLAlchemy ORM) |
| Vector Storage | ChromaDB (local embeddings) |
| Document Parsing | PyMuPDF, pdfplumber |
| CLI | Click + Rich |
| Testing | pytest (42 tests) |

## Requirements

- Python 3.10+
- OpenAI API key with access to the configured Responses model
- ~200MB disk space for the embedding model (all-MiniLM-L6-v2)

## License

MIT
