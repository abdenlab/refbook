"""Load a catalog: the sequence store, the collection store, editions and targets.

The sequence store says, for every sequence refbook knows (keyed by its `SQ.`
digest, findable by MD5), how to make its bases: a root and the nucleotide
operations applied to it. The collection store holds named collections by
seqcol digest. Editions (cataloged named sequence sets, with labels, recipes and
facets) and targets (the files that reproduce them) are curated entries on top;
see docs/GLOSSARY.md.

A catalog is a directory of the pipeline's outputs: a release made by
the pipeline's export (`doit export`, with a catalog.json manifest), or a
build's catalog itself (catalog/output/build/catalog, whose catalog.json
indexes the task directories the pipeline wrote). Open it by path or by URL. Remotely,
each table is downloaded once into a cache keyed by the release version and
checked against the manifest's sha256; root_blocks is never downloaded, only
read by HTTP range requests. This version reads catalog format 2.
"""

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from refbook.remote import HttpFile, _open, download

FORMAT = 2
KINDS = {"assembled-molecule": "chromosomes", "unlocalized-scaffold": "unlocalized scaffolds",
         "unplaced-scaffold": "unplaced scaffolds", "alt-scaffold": "alt scaffolds",
         "fix-patch": "fix patches", "novel-patch": "novel patches"}
OPERATIONS = {"hardmask_grc": "GRC hard-mask", "iupac_to_n": "IUPAC -> N"}


@dataclass(frozen=True)
class Seq:
    """One named sequence of a collection."""
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
        if self.manifest is not None and self.manifest.get("format", 1) != FORMAT:
            raise ValueError(f"catalog {self.manifest['version']} is format "
                             f"{self.manifest.get('format', 1)}; this refbook reads format {FORMAT}")

        # The sequence store.
        self.sequence = {r["sha512t24u"]: r for r in pq.read_table(self.file("sequences.parquet")).to_pylist()}
        self.sq_by_md5 = {r["md5"]: sq for sq, r in self.sequence.items()}
        self.derivations = defaultdict(list)
        for r in pq.read_table(self.file("derivations.parquet")).to_pylist():
            self.derivations[r["sha512t24u"]].append(r)

        # Editions, their manifests, and the targets that reproduce them.
        self.editions = {r["edition"]: r for r in pq.read_table(self.file("editions.parquet")).to_pylist()}
        self.manifests: dict[str, list[Seq]] = defaultdict(list)
        for r in pq.read_table(self.file("manifests.parquet")).to_pylist():
            self.manifests[r["edition"]].append(Seq(r["name"], r["root_id"], r["length"], r["md5"],
                                                   r["sha512t24u"]))
        self.targets = {r["target"]: r for r in pq.read_table(self.file("targets.parquet")).to_pylist()}
        order = defaultdict(list)
        for r in pq.read_table(self.file("target_sequences.parquet")).to_pylist():
            order[r["target"]].append(r)
        self.target_order = {t: [r["name"] for r in sorted(v, key=lambda r: r["position"])]
                             for t, v in order.items()}
        # Collection digests of the curated entries: seqcol digest -> edition label or target.
        self.named = {r["seqcol_digest"]: f for f, r in self.editions.items()}
        for t, r in self.targets.items():
            self.named.setdefault(r["seqcol_digest"], t)
        self.edition_by_id = {r["id"]: f for f, r in self.editions.items()}

        # Roots, hosted and external, and what kind each is.
        self.root_length, self.external = {}, {}
        for r in pq.read_table(self.file("roots.parquet"), columns=["root_id", "length"]).to_pylist():
            self.root_length[r["root_id"]] = r["length"]
        if self.exists("roots_external.parquet"):
            for r in pq.read_table(self.file("roots_external.parquet")).to_pylist():
                self.external[r["root_id"]] = r
                self.root_length[r["root_id"]] = r["length"]
        self.role = {}
        for m in pq.read_table(self.file("assembly_members.parquet")).to_pylist():
            self.role.setdefault(m["genbank_accession"], (m["assembly_name"], m["role"]))

        # Names: alias -> roots (an alias such as "1" or "chr1" names one root here).
        self.by_alias = defaultdict(set)
        aliases = pq.read_table(self.file("aliases.parquet")).to_pylist()
        for r in aliases:
            self.by_alias[r["alias"]].add(r["root_id"])
        for seqs in self.manifests.values():
            for s in seqs:
                self.by_alias[s.name].add(s.root_id)
        self.display = {}
        for r in aliases:
            if r["namespace"] in ("ucsc", "imgt"):
                self.display.setdefault(r["root_id"], r["alias"])
        self._spans = {}
        self._sequence_aliases = None

    def _local(self, name: str) -> Path:
        """A file's place under self.path: a build index maps names to step directories."""
        if self.manifest is not None and self.manifest.get("build"):
            entry = self.manifest["files"].get(name)
            return self.path / (entry["path"] if entry else name)
        return self.path / name

    def exists(self, name: str) -> bool:
        if self.remote:
            return name in self.manifest["files"]
        return self._local(name).exists()

    def file(self, name: str) -> Path:
        """A local path to one catalog file; downloaded (and checked) on first use if remote."""
        if not self.remote:
            return self._local(name)
        local = self.path / name
        if self.remote:
            entry = self.manifest["files"].get(name)
            if entry is None:
                raise FileNotFoundError(f"{name}: not in catalog {self.manifest['version']}")
            if not (local.exists() and local.stat().st_size == entry["bytes"]):
                download(self.url + name, local, entry["sha256"], entry["bytes"])
        return local

    def stored_collection(self, digest: str) -> dict | None:
        """The level-2 representation of a collection in the collection store."""
        name = f"collections/{digest}.json"
        return json.loads(self.file(name).read_text()) if self.exists(name) else None

    def sequence_aliases(self) -> dict[str, list[tuple[str, str]]]:
        """sha512t24u -> [(naming_authority, alias)]: refget's aliases of each
        stored sequence (sequence_aliases.parquet); empty if the catalog has none."""
        if self._sequence_aliases is None:
            self._sequence_aliases = defaultdict(list)
            if self.exists("sequence_aliases.parquet"):
                t = pq.read_table(self.file("sequence_aliases.parquet"))
                for sq, auth, alias in zip(*(t[c].to_pylist() for c in ("sha512t24u", "naming_authority", "alias"))):
                    self._sequence_aliases[sq].append((auth, alias))
        return self._sequence_aliases

    def by_identifier(self) -> dict[tuple[str, str], set[str]]:
        """(naming_authority, alias) -> the stored sequences it names."""
        if getattr(self, "_by_identifier", None) is None:
            self._by_identifier = defaultdict(set)
            for sq, pairs in self.sequence_aliases().items():
                for pair in pairs:
                    self._by_identifier[pair].add(sq)
        return self._by_identifier

    def edition_names(self) -> dict[str, list[tuple[str, str]]]:
        """sha512t24u -> [(edition, name)]: the editions that use a sequence, under which names."""
        if getattr(self, "_edition_names", None) is None:
            out = defaultdict(list)
            for edition, seqs in self.manifests.items():
                for s in seqs:
                    out[s.sha512t24u].append((edition, s.name))
            self._edition_names = {sq: sorted(v) for sq, v in out.items()}
        return self._edition_names

    def identify_tables(self):
        """The tables identify reads, built once (refbook-core identify)."""
        if getattr(self, "_identify_tables", None) is None:
            from refbook import _core
            stored = [(sq, r["md5"], r["length"], r["root_id"], list(r["operations"]))
                      for sq, r in self.sequence.items()]
            aliases = pq.read_table(self.file("aliases.parquet"), columns=["root_id", "alias"])
            manifests = [(f, s.name, s.sha512t24u) for f, seqs in self.manifests.items() for s in seqs]
            self._identify_tables = _core.IdentifyTables(
                stored, list(self.root_length.items()),
                list(zip(aliases["root_id"].to_pylist(), aliases["alias"].to_pylist())), manifests)
        return self._identify_tables

    def spans(self, layer: str) -> dict[str, list[tuple[int, int]]]:
        """root_id -> the spans of a mask layer (layer_<name>.parquet)."""
        if layer not in self._spans:
            t = pq.read_table(self.file(f"layer_{layer}.parquet"), columns=["root_id", "start", "end"])
            spans = defaultdict(list)
            for r, s, e in zip(*(t[c].to_pylist() for c in ("root_id", "start", "end"))):
                spans[r].append((s, e))
            self._spans[layer] = spans
        return self._spans[layer]

    def blocks_location(self) -> str:
        """root_blocks.parquet as a path or URL (for engines that open it themselves)."""
        return self.url + "root_blocks.parquet" if self.remote else str(self._local("root_blocks.parquet"))

    def open_blocks(self) -> pq.ParquetFile:
        """root_blocks.parquet: a local file, or HTTP range reads; never downloaded whole."""
        if self.remote:
            size = self.manifest["files"]["root_blocks.parquet"]["bytes"]
            self.blocks_http = HttpFile(self.blocks_location(), size)
            return pq.ParquetFile(self.blocks_http)
        return pq.ParquetFile(self._local("root_blocks.parquet"))

    def how(self, sq: str) -> str:
        """How a known sequence is made from its root, in words."""
        ways = []
        for d in self.derivations.get(sq, []):
            if d["operations"]:
                ways.append(" + ".join(OPERATIONS.get(o, o) for o in d["operations"]))
            elif d["root_id"] in self.external:
                ways.append(f"as released ({self.external[d['root_id']]['collection']})")
            else:
                ways.append("as submitted (INSDC)")
        return " or ".join(ways) or "unknown"

    def editions_with(self, sq: str) -> list[str]:
        """The cataloged editions containing a sequence."""
        return sorted({f for d in self.derivations.get(sq, []) for f in d["editions"]})

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
