"""Load the catalog: reproduced flavors, roots, aliases and sequence derivatives.

A catalog is a directory of the pipeline's Parquet outputs: a release made by
pipeline/export_catalog.py (with a catalog.json manifest), or the build
directory itself (REGISTRY/build/grch38). Open it by path or by URL. Remotely,
each table is downloaded once into a cache keyed by the release version and
checked against the manifest's sha256; root_blocks is never downloaded, only
read by HTTP range requests.
"""

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from refbook.remote import HttpFile, _open, download

KINDS = {"assembled-molecule": "chromosomes", "unlocalized-scaffold": "unlocalized scaffolds",
         "unplaced-scaffold": "unplaced scaffolds", "alt-scaffold": "alt scaffolds",
         "fix-patch": "fix patches", "novel-patch": "novel patches"}


@dataclass
class Seq:
    flavor: str
    position: int
    name: str
    root_id: str
    length: int
    md5: str
    sha512t24u: str


class Catalog:
    def __init__(self, source: str | Path, cache: str | Path | None = None):
        self.remote = str(source).startswith(("http://", "https://"))
        if self.remote:
            self.url = str(source).rstrip("/") + "/"
            r, _ = _open(self.url + "catalog.json")
            with r:
                self.manifest = json.load(r)
            cache = Path(cache or os.environ.get("REFBOOK_CACHE", Path.home() / ".cache" / "refbook"))
            self.path = cache / "catalog" / self.manifest["version"]
        else:
            self.url = None
            self.path = Path(source)
            m = self.path / "catalog.json"
            self.manifest = json.loads(m.read_text()) if m.exists() else None
        self.flavors: dict[str, list[Seq]] = defaultdict(list)
        for r in pq.read_table(self.file("flavor_sequences.parquet")).to_pylist():
            self.flavors[r["flavor"]].append(Seq(**r))
        for seqs in self.flavors.values():
            seqs.sort(key=lambda s: s.position)
        self.recipes = {r["flavor"]: r for r in pq.read_table(self.file("recipes.parquet")).to_pylist()}

        # Roots, hosted and external: md5 -> root, and what kind of root each is.
        self.root_length, self.root_md5, self.root_by_md5 = {}, {}, {}
        for r in pq.read_table(self.file("roots.parquet"), columns=["root_id", "length", "md5"]).to_pylist():
            self.root_length[r["root_id"]], self.root_md5[r["root_id"]] = r["length"], r["md5"]
            self.root_by_md5[r["md5"]] = r["root_id"]
        self.external = {}
        if self.exists("roots_external.parquet"):
            for r in pq.read_table(self.file("roots_external.parquet")).to_pylist():
                self.external[r["root_id"]] = r
                self.root_length[r["root_id"]], self.root_md5[r["root_id"]] = r["length"], r["md5"]
                self.root_by_md5.setdefault(r["md5"], r["root_id"])
        self.role = {}
        for m in pq.read_table(self.file("assembly_members.parquet")).to_pylist():
            self.role.setdefault(m["genbank_accession"], (m["assembly_name"], m["role"]))

        # Every published derivative of each root: md5 -> (root, how it was made).
        # Release 0.1.0 calls them "variants".
        self.derivative = {md5: (root, "as submitted (INSDC)") for md5, root in self.root_by_md5.items()}
        if self.exists("family_tree.json"):
            tree = json.loads(self.file("family_tree.json").read_text())
            key = "derivatives" if "derivatives" in tree else "variants"
            for d in tree[key]:
                for x in d[key]:
                    self.derivative.setdefault(x["md5"], (d["root_id"], " or ".join(x["why"])))
        self.flavors_with_md5 = defaultdict(set)
        for f, seqs in self.flavors.items():
            for s in seqs:
                self.flavors_with_md5[s.md5].add(f)

        # Names: alias -> roots (an alias such as "1" or "chr1" names one root here).
        self.by_alias = defaultdict(set)
        aliases = pq.read_table(self.file("aliases.parquet")).to_pylist()
        for r in aliases:
            self.by_alias[r["alias"]].add(r["root_id"])
        for seqs in self.flavors.values():
            for s in seqs:
                self.by_alias[s.name].add(s.root_id)
        self.display = {}
        for r in aliases:
            if r["namespace"] in ("ucsc", "imgt"):
                self.display.setdefault(r["root_id"], r["alias"])

    def exists(self, name: str) -> bool:
        if self.remote:
            return name in self.manifest["files"]
        return (self.path / name).exists()

    def file(self, name: str) -> Path:
        """A local path to one catalog file; downloaded (and checked) on first use if remote."""
        local = self.path / name
        if self.remote:
            entry = self.manifest["files"].get(name)
            if entry is None:
                raise FileNotFoundError(f"{name}: not in catalog {self.manifest['version']}")
            if not (local.exists() and local.stat().st_size == entry["bytes"]):
                download(self.url + name, local, entry["sha256"], entry["bytes"])
        return local

    def blocks_location(self) -> str:
        """root_blocks.parquet as a path or URL (for engines that open it themselves)."""
        return self.url + "root_blocks.parquet" if self.remote else str(self.path / "root_blocks.parquet")

    def open_blocks(self) -> pq.ParquetFile:
        """root_blocks.parquet: a local file, or HTTP range reads; never downloaded whole."""
        if self.remote:
            size = self.manifest["files"]["root_blocks.parquet"]["bytes"]
            self.blocks_http = HttpFile(self.blocks_location(), size)
            return pq.ParquetFile(self.blocks_http)
        return pq.ParquetFile(self.path / "root_blocks.parquet")

    def kind(self, root_id: str) -> str:
        if root_id in self.external:
            return f"HLA alleles ({self.external[root_id]['collection']})"
        if root_id == "AJ507799.2":
            return "EBV"
        role = self.role.get(root_id)
        if role and role[0] == "hs38d1":
            return "hs38d1 decoys"
        return KINDS.get(role and role[1], "other sequences")

    def label(self, root_id: str) -> str:
        return self.display.get(root_id, root_id)
