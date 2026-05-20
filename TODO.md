# RegIntel — TODO

## Completed

- [x] **Phase 1** — Data model, SQLite/SQLAlchemy ORM (7 tables), domain enums
- [x] **Phase 2** — LangGraph research pipeline (research → validate → reflect → persist)
- [x] **Phase 3** — CLI (Click + Rich), query engine, export (JSON/CSV/summary), status, changelog
- [x] **Phase 4** — ChromaDB vector store, semantic search, dual LLM (omlx + local embeddings)
- [x] **Phase 5** — Hardening: dedup (raw SQL merge), doctor health checks, 34 tests passing
- [x] **Phase 6** — Gap analysis, confidence re-scoring, governance matrices
- [x] **Batch orchestrator** — `regitel scan` with per-jurisdiction isolation
- [x] **YAML jurisdictions** — `jurisdictions.yaml` with 12 priority jurisdictions for GenAI
- [x] **Research baseline** — `data/research_baseline.md` with comprehensive GenAI governance knowledge
- [x] **Domain pivot** — Full rewrite from penetration testing to GenAI/agentic AI governance

## Pending

### [P0] Apply grounding improvements from `grounding.md`

Apply the 8 grounding principles to all agent prompts in `regitel/utils/prompts.py`. Covers temporal grounding, capability boundaries, pipeline-awareness, and JSON output formatting.

### [P1] Document Acquisition & Ingestion (Phase 7)

The current pipeline stores regulation metadata. Next: download actual PDF/HTML artifacts and embed full text for deep semantic search.

- [ ] `regitel/agents/downloader.py` — HTTP fetch with httpx, retry, rate-limiting
- [ ] `regitel/extractors/pdf.py` — Full text extraction from regulatory PDFs
- [ ] `regitel/extractors/html.py` — HTML-to-text using trafilatura
- [ ] `regitel/extractors/chunker.py` — RecursiveCharacterTextSplitter for document chunks
- [ ] `SOURCE_DOCS` collection in ChromaDB for full-text search
- [ ] `regitel ingest` CLI command for standalone document ingestion
- [ ] `--ingest` flag on `regitel scan` for post-research download

### [P2] Validation & Benchmarking

- [ ] Benchmark against existing KB PDFs — measure coverage/precision for GenAI regs
- [ ] Ground truth datasets for EU AI Act, FINMA AI guidance, MAS AI standards
- [ ] Hallucination detection tests with known regulations

## Future Enhancements

- [ ] **OCR for scanned PDFs** — Tesseract for image-based regulatory documents
- [ ] **Document versioning** — Track regulation amendments and superseded versions
- [ ] **Authenticated downloads** — Cookie/API-key auth for gated regulator portals
- [ ] **LLM-powered summarization** — Local LLM generates per-document GenAI summaries
- [ ] **Change detection** — "What changed in the AI Act Annex since last quarter?"
- [ ] **Scheduled scans** — Cron-based scans with alerts on new regulations
- [ ] **Regulatory timeline view** — Visual timeline of GenAI regulation effective dates
- [ ] **Vendor assessment generator** — Auto-generate third-party AI vendor assessment checklists
