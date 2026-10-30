"""Apply flavor recipes to the roots, and check each against its published file.

A recipe (see recipes/*.json) is data. The operations, in the order applied:

- select   a list of entries, each either {"assembly": <GenBank assembly
           accession.version>, "roles": [...]} (rows of assembly_members) or
           {"roots": [...]} (roots in no assembly, e.g. EBV)
- mask     [{"layer": <name>, "with": "N"}]: hard-mask the spans of
           layer_<name> that fall on selected roots
- rename   {"namespace": "ucsc", "map": {root: name}, "template":
           {assembly: "...{accession_v}..."}}; map wins, then template (for
           that assembly's roots; accession_v is the accession with "." -> "v"),
           then the namespace column of assembly_members
- order    sort keys, applied in turn: "select" (entry index), "role" (index
           in the entry's roles), "assembly_unit" (unit name as text),
           "molecule" (assigned molecule, in the report's chromosome order),
           "object_rank" (position in the root's AGP file)
- format   {"case": ..., "line_width": ...}: checked against the published
           file's case and line width, not materialized

Writes REGISTRY/build/grch38/flavor_sequences.parquet (flavor, position, name,
root_id, length, md5, sha512t24u) and compares each flavor, position by
position, with REGISTRY/build/grch38/observed/<flavor>.parquet (from
observe_fasta.py). Exits nonzero if any flavor does not reproduce.

Usage: uv run --with pyarrow python run_recipes.py REGISTRY_DIR RECIPES.json
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


def select(recipe: dict, members: list[dict], roots: dict) -> list[dict]:
    """The selected roots, each with the attributes the later steps need."""
    out = []
    for i, entry in enumerate(recipe["select"]):
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
        for m in rows:
            if m["role"] in entry["roles"]:
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
        return template.format(accession=acc, accession_v=acc.replace(".", "v"))
    name = s["member"] and s["member"].get(f"{rename['namespace']}_name")
    if not name:
        sys.exit(f"{acc}: no {rename['namespace']} name and no rule to make one")
    return name


def run(recipe: dict, build: Path, members: list[dict], roots: dict, rank: dict,
        masks: dict) -> list[dict]:
    sel = select(recipe, members, roots)
    for s in sel:
        s["object_rank"] = rank.get(s["root_id"], 0)
    sel.sort(key=lambda s: tuple(s[k] for k in recipe["order"]))
    spans = defaultdict(list)
    for m in recipe.get("mask", []):
        if m["with"] != "N":
            sys.exit(f"{recipe['flavor']}: only N masks are implemented")
        for acc, start, end in masks[m["layer"]]:
            spans[acc].append((start, end))
    out = []
    for pos, s in enumerate(sel):
        acc = s["root_id"]
        r = roots[acc]
        md5, sq = r["md5"], r["sha512t24u"]
        if spans.get(acc):
            bases = root_bases(build, acc)
            for start, end in spans[acc]:
                bases[start:end] = b"N" * (end - start)
            md5, sq = digests(bytes(bases))
        out.append({"flavor": recipe["flavor"], "position": pos,
                    "name": name_of(s, recipe["rename"]), "root_id": acc,
                    "length": r["length"], "md5": md5, "sha512t24u": sq})
    return out


def compare(recipe: dict, got: list[dict], observed: list[dict]) -> list[str]:
    errs = []
    if len(got) != len(observed):
        errs.append(f"{len(got)} sequences, published has {len(observed)}")
    for g, o in zip(got, observed):
        for k in ("name", "length", "md5", "sha512t24u"):
            if g[k] != o[k]:
                errs.append(f"position {g['position']} {k}: {g[k]} != published {o[k]}")
        if o["defline_ac"] and o["defline_ac"] != g["root_id"]:
            errs.append(f"position {g['position']}: root {g['root_id']} != AC:{o['defline_ac']}")
    fmt = recipe.get("format", {})
    if fmt.get("case") == "upper" and any(o["n_lower"] for o in observed):
        errs.append("published file has lowercase; recipe says upper")
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
    roots = {r["root_id"]: r for r in pq.read_table(
        build / "roots.parquet", columns=["root_id", "length", "md5", "sha512t24u"]).to_pylist()}
    agp = pq.read_table(build / "layer_agp.parquet", columns=["root_id", "object_rank"])
    rank = dict(zip(agp["root_id"].to_pylist(), agp["object_rank"].to_pylist()))
    recipes = json.loads(args.recipes.read_text())["recipes"]
    masks = {}
    for name in {m["layer"] for r in recipes for m in r.get("mask", [])}:
        t = pq.read_table(build / f"layer_{name}.parquet", columns=["root_id", "start", "end"])
        masks[name] = list(zip(*(t[c].to_pylist() for c in ("root_id", "start", "end"))))

    rows, failed = [], []
    for recipe in recipes:
        got = run(recipe, build, members, roots, rank, masks)
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
