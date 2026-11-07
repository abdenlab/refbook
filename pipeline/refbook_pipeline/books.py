"""Books: each a book.toml in pipeline/books/<book>/, naming the sources it draws on.

A book is the corpus its editions are made from: one assembly, every release, with its add-ons (sequences from
other assemblies, or in none). A source can serve several books.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import Refused
from .sources import Source


@dataclass(frozen=True)
class Book:
    name: str
    sources: tuple[str, ...]


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
        out[b["name"]] = Book(b["name"], tuple(b["sources"]))
    return out


def sources_of(books: dict[str, Book], sources: dict[str, Source]) -> list[Source]:
    """The sources any book draws on, each once, in their order in sources.toml."""
    used = {s for b in books.values() for s in b.sources}
    return [s for name, s in sources.items() if name in used]
