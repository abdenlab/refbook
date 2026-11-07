"""Where everything is.

- raw/: the downloads, at raw/<host>/<url path>. $REFBOOK_RAW, else the first pipeline's raw directory
  (catalog/output/raw, a symlink to the shared mirror), which both pipelines read until the switch.
- pipeline/sources.toml: every source, declared (see sources.py); pipeline/locks/<source>.lock its lock.
- pipeline/books/<book>/book.toml: a book and the sources it draws on.
- pipeline/output/build/: what the tasks write ($REFBOOK_BUILD overrides). Gitignored.
"""

import os
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent
REPO = PIPELINE.parent
SOURCES = PIPELINE / "sources.toml"
LOCKS = PIPELINE / "locks"
BOOKS = PIPELINE / "books"


def raw_dir() -> Path:
    return Path(os.environ.get("REFBOOK_RAW") or REPO / "catalog" / "output" / "raw")


def build_dir() -> Path:
    return Path(os.environ.get("REFBOOK_BUILD") or PIPELINE / "output" / "build")
