"""Books: each a book.toml in pipeline/books/<book>/, naming the sources it draws on.

A book is the corpus its editions are made from: one assembly, every release, with its add-ons (sequences from
other assemblies, or in none). A source can serve several books.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import Refused
from .sources import Source


@dataclass(frozen=True)
class Book:
    name: str
    sources: tuple[str, ...]                 # every source the book reads
    releases: tuple[str, ...] = ()           # its assembly's releases, p0 first (NCBI assembly sources)
    addons: tuple[str, ...] = ()             # other assemblies it draws on (members, AGPs; no regions)
    region_quirks: tuple[tuple[int, str, str], ...] = ()   # (release, region, root): known report disagreements
    hardmask_grc: dict | None = None         # source, file, par_root (see the book's book.toml)


def load(books_dir: Path, sources: dict[str, Source]) -> dict[str, Book]:
    """Every book, by name, in name order; refuses a book that names an undeclared source."""
    out = {}
    for path in sorted(books_dir.glob("*/book.toml")):
        b = tomllib.loads(path.read_text())
        if b["name"] != path.parent.name:
            raise Refused(f"{path}: the book is named {b['name']}, its directory {path.parent.name}")
        unknown = [s for s in b["sources"] if s not in sources]
        if unknown:
            raise Refused(f"{b['name']}: sources not declared in sources.toml: {unknown}")
        for key in ("releases", "addons"):
            stray = [s for s in b.get(key, []) if s not in b["sources"]]
            if stray:
                raise Refused(f"{b['name']}: {key} not among its sources: {stray}")
        if b.get("hardmask_grc") and b["hardmask_grc"]["source"] not in b["sources"]:
            raise Refused(f"{b['name']}: hardmask_grc's source is not among its sources")
        out[b["name"]] = Book(b["name"], tuple(b["sources"]), tuple(b.get("releases", [])), tuple(b.get("addons", [])),
                              tuple((q["release"], q["region"], q["root"]) for q in b.get("region_quirks", [])),
                              b.get("hardmask_grc"))
    return out


def sources_of(books: dict[str, Book], sources: dict[str, Source]) -> list[Source]:
    """The sources any book draws on, each once, in their order in sources.toml."""
    used = {s for b in books.values() for s in b.sources}
    return [s for name, s in sources.items() if name in used]


def recipes(books_dir: Path, book: str) -> list[dict]:
    """Every recipe of a book, from books/<book>/recipes/*.json (each holds a list); refuses a target named twice."""
    out = [r for p in sorted((books_dir / book / "recipes").glob("*.json"))
           for r in json.loads(p.read_text())["recipes"]]
    targets = [r["target"] for r in out]
    if len(targets) != len(set(targets)):
        raise Refused(f"{book}: a target is defined in more than one recipe")
    return out


def target_of(recipe: dict) -> str:
    """The raw path of the file a recipe is checked against: `observed_from`, else `published` (its URL)."""
    return recipe.get("observed_from", recipe["published"]).split("://", 1)[1]
