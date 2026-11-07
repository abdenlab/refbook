"""Where everything is.

- raw/: the downloads, at raw/<host>/<url path>. $REFBOOK_RAW, else the first pipeline's raw directory
  (catalog/output/raw, a symlink to the shared mirror), which both pipelines read until the switch.
- pipeline/sources.toml: every source, declared (see sources.py); pipeline/locks/<source>.lock its lock.
- pipeline/books/<book>/book.toml: a book and the sources it draws on.
- pipeline/output/build/: what the tasks write ($REFBOOK_BUILD overrides). Gitignored.
"""

import hashlib
import json
import os
import shutil
from contextlib import contextmanager
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


@contextmanager
def output(directory: Path):
    """A task's output directory, assembled as <directory>.partial and renamed into place only if the task
    finishes, replacing its last run: a failure leaves the last good output as it was."""
    tmp = directory.with_name(f"{directory.name}.partial")
    if tmp.exists():
        shutil.rmtree(tmp)  # left by an interrupted run
    tmp.mkdir(parents=True)
    try:
        yield tmp
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if directory.exists():
        shutil.rmtree(directory)
    tmp.rename(directory)


def record_inputs(out: Path, lock_paths: list[Path]) -> None:
    """<out>/inputs.json: the sha256 of every lock the task read its sources through (the export's gate checks
    that each is the current lock)."""
    out.joinpath("inputs.json").write_text(json.dumps(
        {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(lock_paths)}, indent=1) + "\n")
