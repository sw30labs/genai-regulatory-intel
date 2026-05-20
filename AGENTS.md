# Repository Guidelines

## Project Structure & Module Organization

Regitel is a Python 3.10+ CLI package. Source code lives in `regitel/`: `cli.py` defines the Click command entry point, `agents/` contains the research, validation, reflection, and persistence agents, `graphs/` holds LangGraph orchestration, `models/` defines domain/state models, `storage/` manages SQLite and ChromaDB, and `query/`, `tools/`, `validate/`, and `utils/` provide supporting services. Tests live in `tests/`, with focused modules such as `test_config.py`, `test_storage.py`, and subpackages for CLI and agent coverage. Project docs are in `README.md`, `QUICKSTART.md`, and `docs/`. Runtime outputs under `data/`, local databases, and `.env` files are intentionally ignored.

## Build, Test, and Development Commands

- `pip install -e ".[dev]"`: install the package in editable mode with pytest and Ruff.
- `regitel db init --seed`: initialize SQLite/ChromaDB storage and seed jurisdictions.
- `regitel doctor`: verify local configuration, database state, and service connectivity.
- `regitel scan -j eu --dry-run`: exercise the scan flow without live model/search calls.
- `pytest`: run the test suite.
- `ruff check .`: run lint checks using the repository Ruff settings.

## Coding Style & Naming Conventions

Use 4-space indentation and Python type hints for new public functions and models. Follow the existing module style: concise docstrings, explicit imports, and small functions that keep CLI, storage, agent, and query responsibilities separate. Ruff is configured for Python 3.11 syntax and a 100-character line length. Use `snake_case` for functions, variables, modules, and Click command callbacks; use `PascalCase` for classes and Pydantic/SQLAlchemy models.

## Testing Guidelines

Tests use pytest and pytest-asyncio. Keep tests deterministic and prefer mock LLM/search utilities where possible so OpenAI calls are not required. Name files `tests/test_<area>.py` and test functions `test_<behavior>`. When changing storage, config, or CLI behavior, add or update the nearest focused test module and run at least `pytest tests/test_<area>.py` before the full suite.

## Commit & Pull Request Guidelines

This repository currently has no commit history to infer conventions from. Use short, imperative commit subjects, for example `Add semantic query export filter`, and keep unrelated changes in separate commits. Pull requests should include a brief summary, test evidence, linked issues or TODO items, and screenshots only when CLI output, reports, or visual assets change.

## Security & Configuration Tips

Do not commit `.env`, API keys, local databases, ChromaDB files, or generated exports. Use `regitel.yaml` and environment variables for OpenAI settings, and document any new required configuration in both `README.md` and `QUICKSTART.md`.
