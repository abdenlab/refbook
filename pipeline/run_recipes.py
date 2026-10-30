"""Apply flavor recipes to the roots, and check each against its published file.

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
- order    sort keys, applied in turn: "select" (entry index), "role" (index
           in the entry's roles), "assembly_unit" (unit name as text),
           "molecule" (assigned molecule, in the report's chromosome order),
           "object_rank" (position in the root's AGP file), "name" (the new
           name, as text), "sequence_name" (the GRC Sequence-Name, as text,
           whatever the root is renamed to), "parent_start" (start on the parent in the root's
           earliest placement), {"literal": "..."} (a constant, to place a
           block of roles among the names), {"template": "{stem}..."} (the
           same, built from the name up to its first "_"), {"key":
           "first_release", "min": n}
           (earliest GRCh38 release with the root, floored at n), {"key":
           "length", "reverse": true} (longest first), {"explicit": [root,
           ...]} (that order, listed roots first: for ties no rule explains).
           Either a
           list for every root, or {"default": [...], "by_role": {role:
           [...]}}; per-role lists should start with a literal that sets the
           block apart, so keys of different roles are never compared
- format   {"case": "upper" | "soft", "line_width": ...}: checked against the
           published file, not materialized. "soft" means the file has
           lowercase repeats; digests ignore case, and the soft-mask itself is
           not reproduced

Writes REGISTRY/build/grch38/flavor_sequences.parquet (flavor, position, name,
root_id, length, md5, sha512t24u) and compares each flavor, position by
position, with REGISTRY/build/grch38/observed/<flavor>.parquet (from
observe_fasta.py, or observe_dict.py, which gives only name, length and M5).
Exits nonzero if any flavor does not reproduce.

Usage: uv run python -I pipeline/run_recipes.py REGISTRY_DIR RECIPES.json
"""

import argparse
import base64
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def digests(seq: bytes) -> tuple[str, str]:
    """refget MD5 and SQ. digests of uppercase A-Z bytes."""
    md5 = hashlib.md5(seq).hexdigest()
    sq = "SQ." + base64.urlsafe_b64encode(hashlib.sha512(seq).digest()[:24]).decode()
    return md5, sq


def root_bases(build: Path, acc: str) -> bytearray:
    blocks = pq.read_table(build / "root_blocks.parquet", filters=[("root_id", "=", acc)])
    order = sorted(zip(blocks["start"].to_pylist(), blocks["bases"].to_pylist()))
    return bytearray(b"".join(b.encode() for _, b in order))


def select(recipe: dict, members: list[dict], roots: dict, external: list[dict],
           parent_types: dict) -> list[dict]:
    """The selected roots, each with the attributes the later steps need."""
    out = []
    for i, entry in enumerate(recipe["select"]):
        if "collection" in entry:
            rows = [e for e in external if e["collection"] == entry["collection"]
                    and e["group"] in entry["groups"]]
            if not rows:
                sys.exit(f"{recipe['flavor']}: nothing in {entry['collection']} {entry['groups']}")
            for e in rows:
                out.append({"root_id": e["root_id"], "select": i, "role": 0,
                            "assembly_unit": "", "molecule": 0,
                            "assembly": entry["collection"], "member": None,
                            "external": e})
            continue
        if "roots" in entry:
            for acc in entry["roots"]:
                if acc not in roots:
                    sys.exit(f"{recipe['flavor']}: no root {acc}")
                out.append({"root_id": acc, "select": i, "role": 0, "assembly_unit": "",
                            "molecule": 0, "assembly": None, "member": None})
            continue
        rows = [m for m in members if m["assembly_accession"] == entry["assembly"]]
        if not rows:
            sys.exit(f"{recipe['flavor']}: no assembly {entry['assembly']}")
        molecules = []
        for m in rows:
            if m["role"] == "assembled-molecule" and m["assigned_molecule"] not in molecules:
                molecules.append(m["assigned_molecule"])
        only = set(entry.get("accessions", [])) or None
        placed_on = set(entry.get("placed_on", [])) or None
        for m in rows:
            acc = m["genbank_accession"]
            if placed_on and parent_types.get(acc, placed_on) - placed_on:
                continue  # placed on a parent type the flavor leaves out
            if m["role"] in entry["roles"] and (only is None or acc in only):
                mol = m["assigned_molecule"]
                out.append({"root_id": m["genbank_accession"], "select": i,
                            "role": entry["roles"].index(m["role"]),
                            "assembly_unit": m["assembly_unit"],
                            "molecule": molecules.index(mol) if mol in molecules else len(molecules),
                            "assembly": entry["assembly"], "member": m})
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


def sort_key(s: dict, order) -> tuple:
    if isinstance(order, dict):
        role = s["member"] and s["member"]["role"]
        order = order["by_role"].get(role, order["default"])
    key = []
    for k in order:
        if isinstance(k, str):
            key.append(s[k])
        elif "literal" in k:
            key.append(k["literal"])
        elif "template" in k:
            key.append(k["template"].format(stem=s["name"].split("_")[0]))
        elif "explicit" in k:
            ids = k["explicit"]
            key.append(ids.index(s["root_id"]) if s["root_id"] in ids else len(ids))
        else:
            v = max(k.get("min", s[k["key"]]), s[k["key"]])
            key.append(-v if k.get("reverse") else v)
    return tuple(key)


def run(recipe: dict, build: Path, members: list[dict], roots: dict, rank: dict,
        masks: dict, iupac: dict, first_release: dict, parent_start: dict,
        external: list[dict], parent_types: dict) -> list[dict]:
    sel = select(recipe, members, roots, external, parent_types)
    for s in sel:
        acc = s["root_id"]
        s["object_rank"] = s["external"]["rank"] if s.get("external") else rank.get(acc, 0)
        s["first_release"] = first_release.get(acc, 0)
        s["parent_start"] = parent_start.get(acc, 0)
        s["length"] = roots[acc]["length"]
        s["sequence_name"] = (s["member"] or {}).get("sequence_name") or acc
        s["name"] = name_of(s, recipe["rename"])
    sel.sort(key=lambda s: sort_key(s, recipe["order"]))
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
    for pos, s in enumerate(sel):
        acc = s["root_id"]
        r = roots[acc]
        md5, sq = r["md5"], r["sha512t24u"]
        to_n = iupac.get(acc, []) if alphabet else []
        if s.get("external") and (spans.get(acc) or r["n_iupac"] and alphabet):
            sys.exit(f"{acc}: external root (bases not hosted) would need materializing")
        if spans.get(acc) or to_n:
            bases = root_bases(build, acc)
            for start, end in spans.get(acc, []):
                bases[start:end] = b"N" * (end - start)
            for p in to_n:
                bases[p] = ord("N")
            md5, sq = digests(bytes(bases))
        out.append({"flavor": recipe["flavor"], "position": pos,
                    "name": s["name"], "root_id": acc,
                    "length": r["length"], "md5": md5, "sha512t24u": sq})
    return out


def compare(recipe: dict, got: list[dict], observed: list[dict]) -> list[str]:
    errs = []
    if len(got) != len(observed):
        errs.append(f"{len(got)} sequences, published has {len(observed)}")
    for g, o in zip(got, observed):
        for k in ("name", "length", "md5", "sha512t24u"):
            if o[k] is not None and g[k] != o[k]:  # a .dict observation lacks SQ.
                errs.append(f"position {g['position']} {k}: {g[k]} != published {o[k]}")
        if o["defline_ac"] and o["defline_ac"] != g["root_id"]:
            errs.append(f"position {g['position']}: root {g['root_id']} != AC:{o['defline_ac']}")
    fmt = recipe.get("format", {})
    if any(o["n_lower"] is None for o in observed):
        return errs  # observed from a .dict: no case or line width to check
    if fmt.get("case") == "upper" and any(o["n_lower"] for o in observed):
        errs.append("published file has lowercase; recipe says upper")
    if fmt.get("case") == "soft" and not any(o["n_lower"] for o in observed):
        errs.append("published file has no lowercase; recipe says soft")
    widths = {o["line_width"] for o in observed if o["length"] > o["line_width"]}
    if "line_width" in fmt and widths != {fmt["line_width"]}:
        errs.append(f"published line widths {widths}; recipe says {fmt['line_width']}")
    return errs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("recipes", type=Path)
    args = ap.parse_args()
    build = args.registry / "build" / "grch38"

    members = pq.read_table(build / "assembly_members.parquet").to_pylist()
    cols = ["root_id", "length", "md5", "sha512t24u", "n_iupac"]
    roots = {r["root_id"]: r for r in pq.read_table(build / "roots.parquet", columns=cols).to_pylist()}
    ext_path = build / "roots_external.parquet"
    external = pq.read_table(ext_path).to_pylist() if ext_path.exists() else []
    roots.update({e["root_id"]: {k: e[k] for k in cols} for e in external})
    agp = pq.read_table(build / "layer_agp.parquet", columns=["root_id", "object_rank"])
    rank = dict(zip(agp["root_id"].to_pylist(), agp["object_rank"].to_pylist()))
    recipes = json.loads(args.recipes.read_text())["recipes"]
    masks = {}
    for name in {m["layer"] for r in recipes for m in r.get("mask", [])}:
        t = pq.read_table(build / f"layer_{name}.parquet", columns=["root_id", "start", "end"])
        masks[name] = list(zip(*(t[c].to_pylist() for c in ("root_id", "start", "end"))))

    iupac = defaultdict(list)
    t = pq.read_table(build / "layer_iupac.parquet", columns=["root_id", "pos"])
    for acc, p in zip(t["root_id"].to_pylist(), t["pos"].to_pylist()):
        iupac[acc].append(p)

    first_release = {}
    for m in members:
        if m["assembly_accession"].startswith("GCA_000001405."):
            acc = m["genbank_accession"]
            first_release[acc] = min(first_release.get(acc, m["release"]), m["release"])
    parent_types = defaultdict(set)
    for p in pq.read_table(build / "layer_placements.parquet",
                           columns=["root_id", "parent_type"]).to_pylist():
        parent_types[p["root_id"]].add(p["parent_type"])
    parent_start = {}
    for p in sorted(pq.read_table(build / "layer_placements.parquet",
                                  columns=["root_id", "parent_start", "first_release"]).to_pylist(),
                    key=lambda p: p["first_release"]):
        parent_start.setdefault(p["root_id"], p["parent_start"])

    rows, failed = [], []
    for recipe in recipes:
        got = run(recipe, build, members, roots, rank, masks, iupac, first_release,
                  parent_start, external, parent_types)
        observed = pq.read_table(build / "observed" / f"{recipe['flavor']}.parquet").to_pylist()
        errs = compare(recipe, got, observed)
        print(f"{recipe['flavor']}: {len(got)} sequences, "
              f"{'REPRODUCES' if not errs else f'{len(errs)} MISMATCHES'}", file=sys.stderr)
        for e in errs[:20]:
            print(f"  {e}", file=sys.stderr)
        if errs:
            failed.append(recipe["flavor"])
        rows += got

    out = build / "flavor_sequences.parquet"
    existing = pq.read_table(out).to_pylist() if out.exists() else []
    done = {r["flavor"] for r in recipes}
    rows = [r for r in existing if r["flavor"] not in done] + rows
    pq.write_table(pa.Table.from_pylist(rows), out, compression="zstd")
    if failed:
        sys.exit(f"not reproduced: {failed}")


if __name__ == "__main__":
    main()
