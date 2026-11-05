"""The recipe engine: compile a recipe into its sequences.

A component, not a pipeline step: 40_recipes.py and 41_flavors.py use it,
and it is the reference the Rust core must agree with (tests/test_golden.py).
A recipe (see recipes/*.json) is data. The operations, in the order applied:

- select   a list of entries, each either {"assembly": <GenBank assembly
           accession.version>, "roles": [...], "accessions": [...]?} (rows of
           assembly_members, optionally only those accessions, and with
           "placed_on": ["chromosome"] only roots placed, if at all, on those
           parent types: layer_placements.parent_type), {"roots":
           [...]} (roots in no assembly, e.g. EBV) or {"collection": ...,
           "groups": [...]} (external roots, roots_external.parquet, in their
           collection's rank order; never materialized)
- mask     [{"layer": <name>, "with": "N"}]: hard-mask the spans of
           layer_<name> that fall on selected roots
- alphabet {"iupac": "N"}: replace every IUPAC code (layer_iupac) with N
- rename   {"namespace": "ucsc", "by_role": {role: namespace}, "map": {root:
           name}, "template": {assembly or collection: "...{accession_v}..."}};
           map wins, then template (for that assembly's roots; accession_v is
           the accession with "." -> "v", name an external root's name), then
           the by_role namespace for the
           root's role, then the default namespace. A namespace is a name
           column of assembly_members: ucsc, sequence (the GRC
           Sequence-Name), genbank (the accession) or refseq

A recipe defines a named sequence set: it has no order and no formatting.
"""

import functools
import sys
from collections import defaultdict
from pathlib import Path

import layout
import pyarrow.parquet as pq

from refbook import refget
from refbook.blocks import row_groups_by_root


@functools.cache
def _blocks(build: Path) -> tuple[pq.ParquetFile, dict[str, list[int]]]:
    f = pq.ParquetFile(layout.path(build, "root_blocks.parquet"))
    return f, row_groups_by_root(f)


def root_bases(build: Path, acc: str) -> bytes:
    """A root's bases, read from its own row groups only."""
    f, groups = _blocks(build)
    t = f.read_row_groups(groups[acc], columns=["start", "bases"])
    order = sorted(zip(t["start"].to_pylist(), t["bases"].to_pylist()))
    return b"".join(b.encode() for _, b in order)


def apply_operations(bases: bytes, spans: list[tuple[int, int]], positions: list[int]) -> bytes:
    """A root's bases with the masked spans (0-based half-open) and the given
    positions (IUPAC -> N) set to N."""
    out = bytearray(bases)
    for start, end in spans:
        out[start:end] = b"N" * (end - start)
    for p in positions:
        out[p] = ord("N")
    return bytes(out)


@functools.cache
def derivative_digests(build: Path, acc: str, spans: tuple, positions: tuple) -> tuple[str, str]:
    """Digests of a root after operations; cached, since targets share derivatives."""
    return refget.digests(apply_operations(root_bases(build, acc), spans, positions))


def select(recipe: dict, members: list[dict], roots: dict, external: list[dict],
           parent_types: dict) -> list[dict]:
    """The selected roots: each with the entry's assembly (or collection) and the
    report row or external record it was selected through, which rename uses."""
    out = []
    for entry in recipe["select"]:
        if "collection" in entry:
            rows = [e for e in external if e["collection"] == entry["collection"]
                    and e["group"] in entry["groups"]]
            if not rows:
                sys.exit(f"{recipe['flavor']}: nothing in {entry['collection']} {entry['groups']}")
            for e in rows:
                out.append({"root_id": e["root_id"], "assembly": entry["collection"],
                            "member": None, "external": e})
            continue
        if "roots" in entry:
            for acc in entry["roots"]:
                if acc not in roots:
                    sys.exit(f"{recipe['flavor']}: no root {acc}")
                out.append({"root_id": acc, "assembly": None, "member": None})
            continue
        rows = [m for m in members if m["assembly_accession"] == entry["assembly"]]
        if not rows:
            sys.exit(f"{recipe['flavor']}: no assembly {entry['assembly']}")
        only = set(entry.get("accessions", [])) or None
        placed_on = set(entry.get("placed_on", [])) or None
        for m in rows:
            acc = m["genbank_accession"]
            if placed_on and parent_types.get(acc, placed_on) - placed_on:
                continue  # placed on a parent type the flavor leaves out
            if m["role"] in entry["roles"] and (only is None or acc in only):
                out.append({"root_id": acc, "assembly": entry["assembly"], "member": m})
    ids = [s["root_id"] for s in out]
    if len(ids) != len(set(ids)):
        sys.exit(f"{recipe['flavor']}: a root is selected twice")
    return out


def name_of(s: dict, rename: dict) -> str:
    acc = s["root_id"]
    if acc in rename.get("map", {}):
        return rename["map"][acc]
    template = rename.get("template", {}).get(s["assembly"])
    if template:
        ext = s.get("external") or {}
        return template.format(accession=acc, accession_v=acc.replace(".", "v"),
                               name=ext.get("name"))
    m = s["member"]
    ns = rename.get("by_role", {}).get(m and m["role"], rename["namespace"])
    name = m and m.get(NAMESPACES[ns])
    if not name:
        sys.exit(f"{acc}: no {ns} name and no rule to make one")
    return name


# Recipe namespace -> assembly_members column.
NAMESPACES = {"ucsc": "ucsc_name", "sequence": "sequence_name",
              "genbank": "genbank_accession", "refseq": "refseq_accession"}


def run(recipe: dict, build: Path, t: dict) -> list[dict]:
    """A recipe's sequences, in canonical order (by name, code point)."""
    sel = select(recipe, t["members"], t["roots"], t["external"], t["parent_types"])
    roots, masks, iupac = t["roots"], t["masks"], t["iupac"]
    for s in sel:
        s["name"] = name_of(s, recipe["rename"])
    names = [s["name"] for s in sel]
    if len(names) != len(set(names)):
        sys.exit(f"{recipe['flavor']}: a name is used twice")
    sel.sort(key=lambda s: s["name"].encode())
    spans = defaultdict(list)
    for m in recipe.get("mask", []):
        if m["with"] != "N":
            sys.exit(f"{recipe['flavor']}: only N masks are implemented")
        for acc, start, end in masks[m["layer"]]:
            spans[acc].append((start, end))
    alphabet = recipe.get("alphabet", {})
    if alphabet not in ({}, {"iupac": "N"}):
        sys.exit(f"{recipe['flavor']}: only the alphabet change iupac -> N is implemented")
    out = []
    for s in sel:
        acc = s["root_id"]
        r = roots[acc]
        md5, sq = r["md5"], r["sha512t24u"]
        to_n = iupac.get(acc, []) if alphabet else []
        if s.get("external") and (spans.get(acc) or r["n_iupac"] and alphabet):
            sys.exit(f"{acc}: external root (bases not hosted) would need materializing")
        if spans.get(acc) or to_n:
            md5, sq = derivative_digests(build, acc, tuple(spans.get(acc, [])), tuple(to_n))
        out.append({"flavor": recipe["flavor"], "name": s["name"], "root_id": acc,
                    "length": r["length"], "md5": md5, "sha512t24u": sq})
    return out


def compare(got: list[dict], observed: list[dict]) -> list[str]:
    """Order-free reproduction: the same names, each with the same length and
    digests (where the observation has them; a .dict lacks SQ.), and the same
    root as a GRC defline's AC: tag."""
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
    out = []
    for o in sorted(observed, key=lambda o: o["position"]):
        g = by_name[o["name"]]
        out.append({"flavor": g["flavor"], "position": o["position"], "name": g["name"],
                    "root_id": g["root_id"], "length": g["length"], "md5": g["md5"],
                    "sha512t24u": g["sha512t24u"]})
    return out


def load_tables(build: Path, recipes: list[dict]) -> dict:
    """The catalog tables run() needs, by name."""
    members = pq.read_table(layout.path(build, "assembly_members.parquet")).to_pylist()
    cols = ["root_id", "length", "md5", "sha512t24u", "n_iupac"]
    roots = {r["root_id"]: r for r in pq.read_table(layout.path(build, "roots.parquet"), columns=cols).to_pylist()}
    try:
        external = pq.read_table(layout.path(build, "roots_external.parquet")).to_pylist()
    except FileNotFoundError:
        external = []
    roots.update({e["root_id"]: {k: e[k] for k in cols} for e in external})
    masks = {}
    for name in {m["layer"] for r in recipes for m in r.get("mask", [])}:
        t = pq.read_table(layout.path(build, f"layer_{name}.parquet"), columns=["root_id", "start", "end"])
        masks[name] = list(zip(*(t[c].to_pylist() for c in ("root_id", "start", "end"))))

    iupac = defaultdict(list)
    t = pq.read_table(layout.path(build, "layer_iupac.parquet"), columns=["root_id", "pos"])
    for acc, p in zip(t["root_id"].to_pylist(), t["pos"].to_pylist()):
        iupac[acc].append(p)

    parent_types = defaultdict(set)
    for p in pq.read_table(layout.path(build, "layer_placements.parquet"),
                           columns=["root_id", "parent_type"]).to_pylist():
        parent_types[p["root_id"]].add(p["parent_type"])
    return {"members": members, "roots": roots, "masks": masks, "iupac": iupac,
            "external": external, "parent_types": parent_types}
