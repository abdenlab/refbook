"""Build the flavors, the targets that reproduce them, and each flavor's manifest.

A flavor is a named sequence set that refbook catalogs; a target is a file
that reproduces one (see docs/GLOSSARY.md). Reads the reproduced targets
(flavor_sequences.parquet, from 40_recipes.py), the
recipes, the catalog tables, and the curated labels in
catalog/assemblies/<assembly>/flavors.json, and
writes to build/grch38/41_flavors/:

- flavors.parquet     one row per flavor: label, id (the named-sequence-set
                      digest, refbook.seqcol.named_set_digest), the seqcol
                      digest of its manifest, counts, and the facets generated
                      from its recipe and manifest: assembly, patch_release,
                      contents (sequences by kind), excluded, operations,
                      naming, plus the recipe itself (select, mask, alphabet,
                      rename)
- manifests.parquet   one row per sequence of each flavor, in canonical order
                      (by name, code point): name, root_id, operations (the
                      nucleotide operations applied to the root), length, MD5,
                      SQ. digest
- targets.parquet     one row per target: its flavor, publisher, alias (the
                      publisher's name for the file), URLs, the exact file it
                      was checked against (sha256, size and Last-Modified from
                      the targets lock) and the evidence (FASTA content or
                      .dict), and the seqcol digests of the target's own
                      collection (its order)
- target_sequences.parquet   each target's order: target, position, name
- sequences.parquet   the sequence store: one row per distinct sequence (every
                      root, and every derivative a manifest uses), keyed by
                      sha512t24u, with md5, length and the canonical
                      derivation (root_id, operations) used to build it:
                      fewest operations, then sorted operation names, then root
- derivations.parquet every known way to make each sequence: sha512t24u,
                      root_id, operations, and the flavors whose recipes give it
                      (none for a root as submitted)
- collections/<digest>.json  the level-2 seqcol representation of every
                      manifest and target collection, with the ancillary
                      attributes, named by top-level digest

Fails unless the targets that share a named-sequence-set digest are exactly
the targets flavors.json lists under one label, and unless rebuilding each
manifest row from its root and operations gives its digests.

Usage: uv run python -I catalog/41_flavors.py [--assembly A] [--raw DIR] [--build DIR]
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from refbook import seqcol

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import engine
import layout
from observe import read_provenance

GRCH38 = layout.GRCH38
STEP = "41_flavors"
OPERATION_OF_ALPHABET = "iupac_to_n"


def kind(root: str, member: dict | None, latest: set[str]) -> str:
    """What sort of sequence a root is, for the contents facet."""
    if root.startswith("IMGTHLA:"):
        return "HLA allele"
    if member is None:
        return "other"  # roots in no assembly report, e.g. EBV, named below
    if not member["assembly_accession"].startswith(GRCH38):
        return f"{member['assembly_name']} decoy"
    if member["role"] in ("fix-patch", "novel-patch") and root not in latest:
        return f"superseded {member['role']}"
    return member["role"]


def naming(rename: dict) -> str:
    """The naming facet: the default namespace, then each exception."""
    parts = [rename["namespace"]]
    parts += [f"{role}: {ns}" for role, ns in sorted(rename.get("by_role", {}).items())]
    parts += [f"{asm}: {tpl}" for asm, tpl in sorted(rename.get("template", {}).items())]
    parts += [f"{root}: {name}" for root, name in sorted(rename.get("map", {}).items())]
    return "; ".join(parts)


def excluded(recipe: dict, members: list[dict], selected: set[str]) -> list[str]:
    """Members an entry's assembly and roles cover that the flavor leaves out,
    e.g. patches placed on alt scaffolds, by role and reason."""
    out = Counter()
    for entry in recipe["select"]:
        if "assembly" not in entry or "accessions" in entry:
            continue
        for m in members:
            if (m["assembly_accession"] == entry["assembly"] and m["role"] in entry["roles"]
                    and m["genbank_accession"] not in selected):
                why = f"not placed on {' or '.join(entry['placed_on'])}" if "placed_on" in entry else "left out"
                out[f"{m['role']} ({why})"] += 1
    return [f"{n} {what}" for what, n in sorted(out.items())]


def collection_files(names, lengths, sequences, out: Path) -> tuple[str, dict]:
    """Write a collection's level-2 representation; return its seqcol digests."""
    top, level1 = seqcol.digests(names, lengths, sequences)
    obj = {"names": names, "lengths": lengths, "sequences": sequences,
           **seqcol.ancillary(names, lengths, sequences)}
    (out / f"{top}.json").write_text(json.dumps(obj) + "\n")
    return top, level1


def main() -> None:
    ap = argparse.ArgumentParser()
    args = layout.arguments(ap)
    build = args.build
    with layout.step_output(build, STEP) as out:
        run(args, build, out)


def run(args, build: Path, out: Path) -> None:

    recipes = {r["flavor"]: r for r in layout.recipes(args.assembly)}
    curated = json.loads(layout.flavors_file(args.assembly).read_text())["flavors"]
    label_of = {t: f["label"] for f in curated for t in f["targets"]}
    target_meta = {t: m for f in curated for t, m in f["targets"].items()}
    if len({f["label"] for f in curated}) != len(curated):
        sys.exit("flavors.json: a label is used twice")

    rows = defaultdict(list)
    for r in pq.read_table(layout.path(build, "flavor_sequences.parquet")).to_pylist():
        rows[r["flavor"]].append(r)  # "flavor" here is still the target
    for v in rows.values():
        v.sort(key=lambda r: r["position"])
    if set(rows) != set(recipes) or set(rows) != set(label_of):
        sys.exit(f"targets differ between flavor_sequences, recipes and flavors.json: "
                 f"{sorted(set(rows) ^ set(label_of))}")

    # Group targets by their named sequence set, and check the curation.
    by_digest = defaultdict(list)
    for t, v in rows.items():
        by_digest[seqcol.named_set_digest([r["name"] for r in v], [r["sha512t24u"] for r in v])].append(t)
    for digest, ts in by_digest.items():
        labels = {label_of[t] for t in ts}
        if len(labels) != 1:
            sys.exit(f"targets {sorted(ts)} are one named sequence set but labeled {sorted(labels)}")
    if len(by_digest) != len(curated):
        sys.exit(f"{len(curated)} labels for {len(by_digest)} named sequence sets")

    members = pq.read_table(layout.path(build, "assembly_members.parquet")).to_pylist()
    member_of = {}
    for m in members:
        member_of.setdefault(m["genbank_accession"], m)
    latest_release = max(m["release"] for m in members if m["assembly_accession"].startswith(GRCH38))
    latest = {m["genbank_accession"] for m in members
              if m["assembly_accession"].startswith(GRCH38) and m["release"] == latest_release}
    tables = engine.load_tables(build, list(recipes.values()))
    spans_of = tables["spans"]

    out_dir = out / "collections"
    out_dir.mkdir()
    flavors, manifests, targets, orders = [], [], [], []
    for digest, ts in sorted(by_digest.items(), key=lambda kv: label_of[kv[1][0]]):
        label = label_of[ts[0]]
        first = next(t for t in curated_targets(curated, label) if t in ts)
        recipe = recipes[first]
        mask_layers = [m["layer"] for m in recipe.get("mask", [])]
        alphabet = bool(recipe.get("alphabet"))

        compiled = {name: (root, ops) for name, root, ops in engine.compile(recipe, tables)}
        manifest = []
        for r in sorted(rows[first], key=lambda r: r["name"].encode()):
            acc = r["root_id"]
            if compiled.get(r["name"], (None,))[0] != acc:
                sys.exit(f"{label} {r['name']}: the recipe compiles to another root")
            ops = compiled[r["name"]][1]
            if ops:  # rebuilding from root and operations, in Python, must give the digests
                spans = tuple(s for m in ops if m != OPERATION_OF_ALPHABET for s in spans_of[m].get(acc, []))
                positions = tuple(tables["iupac"].get(acc, [])) if OPERATION_OF_ALPHABET in ops else ()
                if engine.derivative_digests(build, acc, spans, positions) != (r["md5"], r["sha512t24u"]):
                    sys.exit(f"{label} {r['name']}: operations {ops} don't give its digests")
            elif (r["md5"], r["sha512t24u"]) != (tables["roots"][acc]["md5"], tables["roots"][acc]["sha512t24u"]):
                sys.exit(f"{label} {r['name']}: differs from root {acc} with no operations")
            manifest.append({"flavor": label, "name": r["name"], "root_id": acc, "operations": ops,
                             "length": r["length"], "md5": r["md5"], "sha512t24u": r["sha512t24u"]})
        manifests += manifest
        names = [r["name"] for r in manifest]
        top, _ = collection_files(names, [r["length"] for r in manifest],
                                       [r["sha512t24u"] for r in manifest], out_dir)

        kinds = Counter("EBV" if r["root_id"] == "AJ507799.2" else
                        kind(r["root_id"], member_of.get(r["root_id"]), latest) for r in manifest)
        patch_releases = [m["release"] for m in members if m["genbank_accession"] in
                          {r["root_id"] for r in manifest} and m["role"] in ("fix-patch", "novel-patch")]
        selected = {r["root_id"] for r in manifest}
        flavors.append({
            "flavor": label, "id": digest, "seqcol_digest": top,
            "n_sequences": len(manifest), "total_length": sum(r["length"] for r in manifest),
            "assembly": "GRCh38",
            "patch_release": max(patch_releases) if patch_releases else None,
            "contents": [{"kind": k, "count": n} for k, n in sorted(kinds.items())],
            "excluded": excluded(recipe, members, selected),
            "operations": mask_layers + ([OPERATION_OF_ALPHABET] if alphabet else []),
            "naming": naming(recipe["rename"]),
            "recipe": json.dumps({k: recipe[k] for k in ("select", "mask", "alphabet", "rename")
                                  if k in recipe}, sort_keys=True),
            "n_targets": len(ts),
        })

        for t in ts:
            r = recipes[t]
            v = rows[t]
            t_top, t_level1 = collection_files([x["name"] for x in v], [x["length"] for x in v],
                                               [x["sha512t24u"] for x in v], out_dir)
            prov = read_provenance(layout.path(build, f"observed/{t}.parquet"))
            targets.append({
                "target": t, "flavor": label, **target_meta[t],
                "published": r["published"], "checked_against": prov["url"],
                "evidence": prov["evidence"], "checked_sha256": prov["sha256"],
                "checked_bytes": int(prov["bytes"]), "checked_last_modified": prov["last_modified"],
                "n_sequences": len(v), "seqcol_digest": t_top,
                "seqcol_names": t_level1["names"], "seqcol_lengths": t_level1["lengths"],
                "seqcol_sequences": t_level1["sequences"],
            })
            orders += [{"target": t, "position": x["position"], "name": x["name"]} for x in v]

    sequences, derivations = sequence_store(manifests, tables["roots"])
    for name, table in (("flavors", flavors), ("manifests", manifests), ("targets", targets),
                        ("target_sequences", orders), ("sequences", sequences),
                        ("derivations", derivations)):
        pq.write_table(pa.Table.from_pylist(table), out / f"{name}.parquet", compression="zstd")
    print(f"{len(flavors)} flavors, {len(targets)} targets, {len(manifests)} manifest rows",
          file=sys.stderr)
    for f in flavors:
        print(f"  {f['flavor']:<30} {f['id']}  {f['n_targets']} target(s)", file=sys.stderr)


def sequence_store(manifests: list[dict], roots: dict) -> tuple[list[dict], list[dict]]:
    """The sequences and derivations tables: every root as submitted, and every
    derivative the manifests use, with each way it is made."""
    ways = defaultdict(lambda: defaultdict(set))  # sq -> (root, operations) -> flavors
    info = {}
    for acc, r in roots.items():
        ways[r["sha512t24u"]][acc, ()]
        info[r["sha512t24u"]] = (r["md5"], r["length"])
    for r in manifests:
        ways[r["sha512t24u"]][r["root_id"], tuple(r["operations"])].add(r["flavor"])
        info[r["sha512t24u"]] = (r["md5"], r["length"])
    sequences, derivations = [], []
    for sq in sorted(ways):
        root, ops = min(ways[sq], key=lambda w: (len(w[1]), sorted(w[1]), w[0]))
        md5, length = info[sq]
        sequences.append({"sha512t24u": sq, "md5": md5, "length": length,
                          "root_id": root, "operations": list(ops),
                          "n_derivations": len(ways[sq])})
        for (acc, o), fl in sorted(ways[sq].items()):
            derivations.append({"sha512t24u": sq, "root_id": acc, "operations": list(o),
                                "flavors": sorted(fl)})
    return sequences, derivations


def curated_targets(curated: list[dict], label: str) -> list[str]:
    return list(next(f for f in curated if f["label"] == label)["targets"])


if __name__ == "__main__":
    main()
