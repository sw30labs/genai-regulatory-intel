"""Logging and Rich console utilities."""

from __future__ import annotations

import logging
from rich.console import Console
from rich.theme import Theme

# Shared Rich console for CLI output
theme = Theme({
    "info": "cyan",
    "success": "green bold",
    "warning": "yellow",
    "error": "red bold",
    "muted": "dim",
    "highlight": "bold magenta",
})

console = Console(theme=theme)


def setup_logging(verbose: bool = False) -> None:
    """Configure Python logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy libraries
    for lib in ("httpx", "httpcore", "chromadb", "sqlalchemy.engine"):
        logging.getLogger(lib).setLevel(logging.WARNING)
