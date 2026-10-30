"""Load the catalog: reproduced flavors, roots, aliases and sequence variants.

A catalog directory holds the pipeline's Parquet outputs (for now
REGISTRY/build/grch38): flavor_sequences, recipes, roots, roots_external,
assembly_members, aliases and family_tree.json.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

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
    def __init__(self, path: str | Path):
        path = Path(path)
        self.path = path
        self.flavors: dict[str, list[Seq]] = defaultdict(list)
        for r in pq.read_table(path / "flavor_sequences.parquet").to_pylist():
            self.flavors[r["flavor"]].append(Seq(**r))
        for seqs in self.flavors.values():
            seqs.sort(key=lambda s: s.position)
        self.recipes = {r["flavor"]: r for r in pq.read_table(path / "recipes.parquet").to_pylist()}

        # Roots, hosted and external: md5 -> root, and what kind of root each is.
        self.root_length, self.root_md5, self.root_by_md5 = {}, {}, {}
        for r in pq.read_table(path / "roots.parquet", columns=["root_id", "length", "md5"]).to_pylist():
            self.root_length[r["root_id"]], self.root_md5[r["root_id"]] = r["length"], r["md5"]
            self.root_by_md5[r["md5"]] = r["root_id"]
        ext = path / "roots_external.parquet"
        self.external = {}
        if ext.exists():
            for r in pq.read_table(ext).to_pylist():
                self.external[r["root_id"]] = r
                self.root_length[r["root_id"]], self.root_md5[r["root_id"]] = r["length"], r["md5"]
                self.root_by_md5.setdefault(r["md5"], r["root_id"])
        self.role = {}
        for m in pq.read_table(path / "assembly_members.parquet").to_pylist():
            self.role.setdefault(m["genbank_accession"], (m["assembly_name"], m["role"]))

        # Every published version of each root: md5 -> (root, how it was made).
        self.variant = {md5: (root, "as submitted (INSDC)") for md5, root in self.root_by_md5.items()}
        tree = path / "family_tree.json"
        if tree.exists():
            for v in json.loads(tree.read_text())["variants"]:
                for x in v["variants"]:
                    self.variant.setdefault(x["md5"], (v["root_id"], " or ".join(x["why"])))
        self.flavors_with_md5 = defaultdict(set)
        for f, seqs in self.flavors.items():
            for s in seqs:
                self.flavors_with_md5[s.md5].add(f)

        # Names: alias -> roots (an alias such as "1" or "chr1" names one root here).
        self.by_alias = defaultdict(set)
        for r in pq.read_table(path / "aliases.parquet").to_pylist():
            self.by_alias[r["alias"]].add(r["root_id"])
        for seqs in self.flavors.values():
            for s in seqs:
                self.by_alias[s.name].add(s.root_id)
        self.display = {}
        for r in pq.read_table(path / "aliases.parquet").to_pylist():
            if r["namespace"] in ("ucsc", "imgt"):
                self.display.setdefault(r["root_id"], r["alias"])

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
