"""The recipe engine: compile a recipe into its sequences, and compare them with a target's observation.

Compiling is the Rust core's (crates/refbook-core/src/recipe.rs); this module loads the catalog tables it reads,
fills in lengths and digests, and compares the result with what a target was observed to hold.

A recipe (catalog/books/<book>/recipes/*.json) is data:

- select   a list of entries, each either {"assembly": <GenBank assembly accession.version>, "roles": [...],
           "accessions": [...]?} (rows of assembly_members, optionally only those accessions, and with
           "placed_on": [...] only roots placed, if at all, on those parent types: layer_placements.parent_type),
           {"roots": [...]} (roots in no assembly, e.g. EBV) or {"collection": ..., "groups": [...]} (external
           roots, roots_external.parquet, in their collection's rank order; never materialized)
- mask     [{"layer": <name>, "with": "N"}]: hard-mask the spans of layer_<name> that fall on selected roots
- alphabet {"iupac": "N"}: replace every IUPAC code (layer_iupac) with N
- rename   {"namespace": "ucsc", "by_role": {role: namespace}, "map": {root: name}, "template": {assembly or
           collection: "...{accession_v}..."}}; map wins, then template (for that assembly's roots; accession_v is
           the accession with "." -> "v", name an external root's name), then the by_role namespace for the root's
           role, then the default namespace. A namespace is a name column of assembly_members: ucsc, sequence
           (the GRC Sequence-Name), genbank (the accession) or refseq

Other keys (target, published, observed_from) are the recipe's metadata. A recipe defines a named sequence set: it
has no order and no formatting.
"""

from __future__ import annotations

import functools
import json
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from refbook import _core, refget
from refbook.blocks import row_groups_by_root

from . import Refused

IUPAC_TO_N = "iupac_to_n"


@functools.cache
def _blocks(path: Path) -> tuple[pq.ParquetFile, dict[str, list[int]]]:
    f = pq.ParquetFile(path)
    return f, row_groups_by_root(f)


def root_bases(blocks: Path, acc: str) -> bytes:
    """A root's bases, read from its own row groups of root_blocks only."""
    f, groups = _blocks(blocks)
    t = f.read_row_groups(groups[acc], columns=["start", "bases"])
    return b"".join(b.encode() for _, b in sorted(zip(t["start"].to_pylist(), t["bases"].to_pylist())))


def apply_operations(bases: bytes, spans: list[tuple[int, int]], positions: list[int]) -> bytes:
    """A root's bases with the masked spans (0-based half-open) and the given positions (IUPAC -> N) set to N:
    in Python, independently of the core, as a check on it."""
    out = bytearray(bases)
    for start, end in spans:
        out[start:end] = b"N" * (end - start)
    for p in positions:
        out[p] = ord("N")
    return bytes(out)


@functools.cache
def derivative_digests(blocks: Path, acc: str, spans: tuple, positions: tuple) -> tuple[str, str]:
    """Digests of a root after operations, by the Python apply_operations. Cached: editions share derivatives."""
    return refget.digests(apply_operations(root_bases(blocks, acc), spans, positions))


@functools.cache
def _derived(blocks: Path, acc: str, spans: tuple, to_n: bool) -> tuple[str, str]:
    return refget.digests(_core.apply_operations(root_bases(blocks, acc), 0, list(spans), to_n))


def compile(recipe: dict, t: dict) -> list[tuple[str, str, list[str]]]:
    """A recipe's manifest rows (name, root_id, operations), in canonical order (by name, code point), from the
    Rust core's recipe compiler."""
    try:
        return _core.compile_recipe(json.dumps(recipe), t["compiler"])
    except _core.RecipeError as e:
        raise Refused(f"{recipe['target']}: {e}") from e


def run(recipe: dict, t: dict) -> list[dict]:
    """A recipe's sequences, in canonical order, with their operations and the digests those give (the core's)."""
    out = []
    for name, acc, ops in compile(recipe, t):
        r = t["roots"][acc]
        md5, sq = r["md5"], r["sha512t24u"]
        if ops:
            spans = tuple(s for op in ops if op != IUPAC_TO_N for s in t["spans"][op].get(acc, ()))
            md5, sq = _derived(t["blocks"], acc, spans, IUPAC_TO_N in ops)
        out.append({"target": recipe["target"], "name": name, "root_id": acc, "operations": ops,
                    "length": r["length"], "md5": md5, "sha512t24u": sq})
    return out


def compare(got: list[dict], observed: list[dict]) -> list[str]:
    """Order-free reproduction: the same names, each with the same length and digests (where the observation
    has them; a .dict lacks SQ.), and the same root as a GRC defline's AC: tag."""
    errs = []
    want = {o["name"]: o for o in observed}
    if len(want) != len(observed):
        errs.append("the target uses a name twice")
    have = {g["name"]: g for g in got}
    if set(have) != set(want):
        errs.append(f"names only in the recipe: {sorted(set(have) - set(want))[:5]}; "
                    f"only in the target: {sorted(set(want) - set(have))[:5]}")
    for name in sorted(set(have) & set(want)):
        g, o = have[name], want[name]
        for k in ("length", "md5", "sha512t24u"):
            if o[k] is not None and g[k] != o[k]:
                errs.append(f"{name} {k}: {g[k]} != target {o[k]}")
        if o["defline_ac"] and o["defline_ac"] != g["root_id"]:
            errs.append(f"{name}: root {g['root_id']} != AC:{o['defline_ac']}")
    return errs


def in_observed_order(got: list[dict], observed: list[dict]) -> list[dict]:
    """A reproduced target's sequences in the target's own order."""
    by_name = {g["name"]: g for g in got}
    return [{"target": by_name[o["name"]]["target"], "position": o["position"], "name": o["name"],
             **{k: by_name[o["name"]][k] for k in ("root_id", "length", "md5", "sha512t24u")}}
            for o in sorted(observed, key=lambda o: o["position"])]


def load_tables(paths: dict[str, Path], recipes: list[dict]) -> dict:
    """The tables run() needs. `paths` gives assembly_members, roots, roots_external, root_blocks, layer_iupac,
    layer_placements and layer_<name> for every layer a recipe masks with."""
    members = pq.read_table(paths["assembly_members"]).to_pylist()
    cols = ["root_id", "length", "md5", "sha512t24u", "n_iupac"]
    roots = {r["root_id"]: r for r in pq.read_table(paths["roots"], columns=cols).to_pylist()}
    external = pq.read_table(paths["roots_external"]).to_pylist()
    roots.update({e["root_id"]: {k: e[k] for k in cols} for e in external})
    spans = {}
    for name in sorted({m["layer"] for r in recipes for m in r.get("mask", [])}):
        t = pq.read_table(paths[f"layer_{name}"], columns=["root_id", "start", "end"])
        by_root = defaultdict(list)
        for acc, start, end in zip(*(t[c].to_pylist() for c in ("root_id", "start", "end"))):
            by_root[acc].append((start, end))
        spans[name] = by_root
    iupac = defaultdict(list)
    t = pq.read_table(paths["layer_iupac"], columns=["root_id", "pos"])
    for acc, p in zip(t["root_id"].to_pylist(), t["pos"].to_pylist()):
        iupac[acc].append(p)
    parent_types = defaultdict(set)
    for p in pq.read_table(paths["layer_placements"], columns=["root_id", "parent_type"]).to_pylist():
        parent_types[p["root_id"]].add(p["parent_type"])
    compiler = _core.RecipeTables(
        members=[(m["assembly_accession"], m["genbank_accession"], m["role"], m["ucsc_name"],
                  m["sequence_name"], m["refseq_accession"]) for m in members],
        roots=list(roots), iupac=[acc for acc, r in roots.items() if r["n_iupac"]],
        layers={name: list(by_root) for name, by_root in spans.items()},
        external=[(e["root_id"], e["collection"], e["group"], e["name"]) for e in external],
        placements=[(acc, p) for acc, ps in parent_types.items() for p in sorted(ps)])
    return {"members": members, "roots": roots, "spans": spans, "iupac": iupac, "external": external,
            "parent_types": parent_types, "compiler": compiler, "blocks": paths["root_blocks"]}


def table_paths(published: dict[str, Path], recipes: list[dict]) -> dict[str, Path]:
    """The tables load_tables reads, by its names, from the catalog's published files (export.published): what a
    build or a release holds."""
    names = ["assembly_members", "roots", "root_blocks", "layer_iupac", "roots_external", "layer_placements"]
    names += sorted({f"layer_{m['layer']}" for r in recipes for m in r.get("mask", [])})
    return {n: published[f"{n}.parquet"] for n in names}
