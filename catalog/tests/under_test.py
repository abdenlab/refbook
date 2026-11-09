"""The catalog the build-wide tests read: REFBOOK_CATALOG, else this repository's build (catalog/output/build/catalog).
A build or a release: either is opened by its catalog.json, and its tables found by their published names."""

import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from refbook_pipeline import books, export, layout

CATALOG = Path(os.environ.get("REFBOOK_CATALOG", layout.build_dir() / "catalog"))
BOOK = "grch38"
needs_catalog = pytest.mark.skipif(not (CATALOG / "catalog.json").exists(), reason="no catalog")


def file(name: str) -> Path:
    """A published table (or the collections directory) of the catalog under test."""
    from refbook import Catalog
    if name == "collections":
        return Catalog(CATALOG).file(next(n for n in Catalog(CATALOG).manifest["files"] if n.startswith("collections/"))).parent
    return Catalog(CATALOG).file(name)


def table(name: str) -> list[dict]:
    return pq.read_table(file(name)).to_pylist()


def published() -> dict[str, Path]:
    """Every published name's file in the catalog under test, as export.published gives a build's: the fixed names,
    and the derived mask layers its index lists."""
    from refbook import Catalog
    derived = [n for n in Catalog(CATALOG).manifest["files"] if n.startswith("layer_") and n not in export.PUBLISHED]
    return {name: file(name) for name in [*export.PUBLISHED, *derived]}


def recipes() -> list[dict]:
    return books.recipes(layout.BOOKS, BOOK)


def observed(target: str) -> Path:
    """A target's observation: in a build, books/<book>/observed/; in a release, evidence/observed/."""
    build = CATALOG.parent / "books" / BOOK / "observed" / f"{target}.parquet"
    return build if build.exists() else CATALOG / "evidence" / "observed" / f"{target}.parquet"
