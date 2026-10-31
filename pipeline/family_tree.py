"""Explain how the reproduced flavors relate: the GRCh38 family tree.

For every pair of flavors in flavor_sequences.parquet, classify how they
differ, from the reproduced outputs, with the recipes for the why:

- content   roots only in one of them, grouped by kind (alt scaffolds, fix and
            novel patches, hs38d1 decoys, EBV, HLA alleles, ...)
- bases     shared roots whose digests differ: explained by the recipes' mask
            layers and alphabet step
- names     shared roots named differently
- order     shared roots in a different relative order
- format    line width and case, as the recipes record them

Two baselines anchor the tree: the INSDC assemblies GRCh38 (GCA_000001405.15)
and GRCh38.p14 (GCA_000001405.29), i.e. the roots themselves under GenBank
names in report order. Each flavor's parent is the flavor (or baseline) it
differs from least: fewest kinds of difference, then fewest roots added or
removed, then fewest differing sequences. Flavors with identical names, roots,
digests and order are one node; members that differ only in format (line
width, case) are listed with their format.

Writes REGISTRY/build/grch38/family_tree.json and prints the tree.

Usage: uv run python -I pipeline/family_tree.py REGISTRY_DIR recipes/*.json
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

BASELINES = {"INSDC_GRCh38": "GCA_000001405.15", "INSDC_GRCh38.p14": "GCA_000001405.29"}
KINDS = {"assembled-molecule": "chromosomes", "unlocalized-scaffold": "unlocalized scaffolds",
         "unplaced-scaffold": "unplaced scaffolds", "alt-scaffold": "alt scaffolds",
         "fix-patch": "fix patches", "novel-patch": "novel patches"}
MASKS = {"hardmask_grc": "GRC hard-mask (CEN/WGS duplicates on chr5, 14, 19, 21, 22; PAR on chrY)"}


def kind_of(root: str, roles: dict) -> str:
    if root.startswith("IMGTHLA:"):
        return "HLA alleles (" + " ".join(root.split(":")[:2]).replace("IMGTHLA", "IMGT/HLA") + ")"
    if root == "AJ507799.2":
        return "EBV"
    role = roles.get(root)
    if role and role[0] == "hs38d1":
        return "hs38d1 decoys"
    return KINDS.get(role and role[1], role and role[1] or "other")


def describe(a: dict, b: dict, roles: dict) -> dict:
    """How flavor b differs from flavor a."""
    ra, rb = {s["root_id"]: s for s in a["seqs"]}, {s["root_id"]: s for s in b["seqs"]}
    added = Counter(kind_of(r, roles) for r in rb if r not in ra)
    removed = Counter(kind_of(r, roles) for r in ra if r not in rb)
    shared = [r for r in rb if r in ra]
    rebased = [r for r in shared if ra[r]["md5"] != rb[r]["md5"]]
    renamed = [r for r in shared if ra[r]["name"] != rb[r]["name"]]
    order_a = [s["root_id"] for s in a["seqs"] if s["root_id"] in rb]
    order_b = [s["root_id"] for s in b["seqs"] if s["root_id"] in ra]
    d = {}
    if added:
        d["added"] = dict(added)
    if removed:
        d["removed"] = dict(removed)
    if rebased:
        ops = []
        ma, mb = set(a["recipe"].get("mask_layers", [])), set(b["recipe"].get("mask_layers", []))
        for m in sorted(mb - ma):
            ops.append(f"+ {MASKS.get(m, m)}")
        for m in sorted(ma - mb):
            ops.append(f"- {MASKS.get(m, m)}")
        if a["recipe"].get("alphabet") != b["recipe"].get("alphabet"):
            ops.append("IUPAC codes -> N" if b["recipe"].get("alphabet") else "IUPAC codes kept (not -> N)")
        d["bases"] = {"sequences": len(rebased), "because": ops or ["unexplained"]}
    if renamed:
        d["names"] = {"sequences": len(renamed),
                      "examples": [f"{ra[r]['name']} -> {rb[r]['name']}" for r in renamed[:3]]}
    if order_a != order_b:
        d["order"] = "different"
    fa, fb = a["recipe"].get("format", {}), b["recipe"].get("format", {})
    if fa and fb and fa != fb:
        d["format"] = {k: f"{fa.get(k)} -> {fb.get(k)}" for k in sorted(set(fa) | set(fb))
                       if fa.get(k) != fb.get(k)}
    return d


def cost(d: dict) -> tuple:
    n_kinds = len(d)
    n_roots = sum(d.get("added", {}).values()) + sum(d.get("removed", {}).values())
    n_seqs = d.get("bases", {}).get("sequences", 0) + d.get("names", {}).get("sequences", 0)
    return (n_kinds, n_roots, n_seqs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("recipes", type=Path, nargs="+")
    args = ap.parse_args()
    build = args.registry / "build" / "grch38"

    recipes = {}
    for path in args.recipes:
        for r in json.loads(path.read_text())["recipes"]:
            recipes[r["flavor"]] = {
                "mask_layers": [m["layer"] for m in r.get("mask", [])],
                "alphabet": r.get("alphabet") or None,
                "format": r.get("format", {}),
                "published": r["published"],
                "checked_against": r.get("observed_from", r["published"]),
                "file": path.name,
            }
    flavors = defaultdict(list)
    for s in pq.read_table(build / "flavor_sequences.parquet").to_pylist():
        if s["flavor"] in recipes:
            flavors[s["flavor"]].append(s)
    missing = set(recipes) - set(flavors)
    if missing:
        sys.exit(f"recipes without reproduced sequences (run run_recipes.py): {sorted(missing)}")

    members = pq.read_table(build / "assembly_members.parquet").to_pylist()
    roots = {r["root_id"]: r for r in pq.read_table(
        build / "roots.parquet", columns=["root_id", "length", "md5"]).to_pylist()}
    roles = {}
    for m in members:
        roles.setdefault(m["genbank_accession"], (m["assembly_name"], m["role"]))
    nodes = {}
    for name, accession in BASELINES.items():
        rows = [m for m in members if m["assembly_accession"] == accession]
        nodes[name] = {"recipe": {"published": f"INSDC {accession} (the roots, GenBank names)"},
                       "seqs": [{"root_id": m["genbank_accession"], "name": m["genbank_accession"],
                                 "md5": roots[m["genbank_accession"]]["md5"]} for m in rows],
                       "baseline": True}
    for f, seqs in flavors.items():
        nodes[f] = {"recipe": recipes[f], "seqs": sorted(seqs, key=lambda s: s["position"]),
                    "baseline": False}

    # Identical flavors (same names, roots, digests and order) form one node.
    sig = {f: tuple((s["name"], s["root_id"], s["md5"]) for s in n["seqs"]) for f, n in nodes.items()}
    groups = defaultdict(list)
    for f in nodes:
        groups[sig[f]].append(f)
    rep = {}
    for members_ in groups.values():
        members_.sort(key=lambda f: (not nodes[f]["baseline"], f))
        for f in members_:
            rep[f] = members_[0]

    order = sorted({rep[f] for f in nodes}, key=lambda f: (not nodes[f]["baseline"], len(nodes[f]["seqs"]), f))
    tree = {}
    for i, f in enumerate(order):
        if nodes[f]["baseline"] and i == 0:
            tree[f] = {"parent": None, "diff": {}}
            continue
        best = None
        for p in order[:i]:
            d = describe(nodes[p], nodes[f], roles)
            if best is None or cost(d) < best[0]:
                best = (cost(d), p, d)
        tree[f] = {"parent": best[1], "diff": best[2]}

    # Derivatives: the distinct sequences published under one root, and why.
    masked = set(pq.read_table(build / "layer_hardmask_grc.parquet", columns=["root_id"])
                 ["root_id"].to_pylist())
    has_iupac = {r["root_id"] for r in pq.read_table(
        build / "roots.parquet", columns=["root_id", "n_iupac"]).to_pylist() if r["n_iupac"]}
    ucsc = {}
    for m in members:
        if m["ucsc_name"]:
            ucsc.setdefault(m["genbank_accession"], m["ucsc_name"])
    by_root = defaultdict(lambda: defaultdict(list))
    for f, n in nodes.items():
        r = n["recipe"]
        for s in n["seqs"]:
            acc = s["root_id"]
            why = []
            if acc in masked and "hardmask_grc" in r.get("mask_layers", []):
                why.append("GRC hard-mask")
            if acc in has_iupac and r.get("alphabet"):
                why.append("IUPAC -> N")
            by_root[acc][s["md5"]].append((f, " + ".join(why) or "as submitted (INSDC)"))
    derivatives = []
    for acc, md5s in by_root.items():
        if len(md5s) < 2:
            continue
        derivatives.append({
            "root_id": acc, "name": ucsc.get(acc, acc), "length": roots[acc]["length"],
            "derivatives": [{"md5": md5, "why": sorted({w for _, w in fl}),
                          "flavors": sorted({f for f, _ in fl})} for md5, fl in md5s.items()],
        })
    derivatives.sort(key=lambda d: (-len(d["derivatives"]), d["root_id"]))

    out = {"nodes": {f: {"sequences": len(nodes[f]["seqs"]), "baseline": nodes[f]["baseline"],
                         "same_as": [{"flavor": g, "format": nodes[g]["recipe"].get("format", {}),
                                      "published": nodes[g]["recipe"].get("published"),
                                      "checked_against": nodes[g]["recipe"].get("checked_against")}
                                     for g in nodes if rep[g] == f and g != f],
                         "parent": tree[f]["parent"], "diff": tree[f]["diff"],
                         **{k: v for k, v in nodes[f]["recipe"].items() if k != "mask_layers"}}
                     for f in order},
           "derivatives": derivatives}
    (build / "family_tree.json").write_text(json.dumps(out, indent=2) + "\n")

    children = defaultdict(list)
    for f in order:
        children[tree[f]["parent"]].append(f)

    def show(f: str, depth: int) -> None:
        fmt = nodes[f]["recipe"].get("format", {})
        same = [g["flavor"] + ("" if g["format"] == fmt else f" {g['format']}")
                for g in out["nodes"][f]["same_as"]]
        label = f + (f"  (= {', '.join(same)})" if same else "")
        print("  " * depth + f"{label}  [{len(nodes[f]['seqs'])}]")
        for k, v in tree[f]["diff"].items():
            print("  " * depth + f"    {k}: {v}")
        for c in children[f]:
            show(c, depth + 1)

    for root in children[None]:
        show(root, 0)


if __name__ == "__main__":
    main()
