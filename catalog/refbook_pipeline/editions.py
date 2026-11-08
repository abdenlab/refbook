"""Editions: a book's targets grouped by their named sequence set, each group one edition with refbook's label.

From a book's reproduced targets (reproduce: each target's sequences in its own order), its recipes and its
curated labels (books/<book>/editions.json):

- editions          one row per edition: label, id (the named-sequence-set digest), the seqcol digest of its
                    manifest, counts, the facets made from its recipe and manifest (assembly, patch_release,
                    contents by kind, excluded, operations, naming) and the recipe itself
- manifests         one row per sequence of each edition, by name (code point): root, operations, length, digests
- targets           one row per target: its edition, publisher, alias, URLs, the exact file it was checked against
                    and the evidence, and the seqcol digests of its own collection (its order)
- target_sequences  each target's order: target, position, name
- collections/      the level-2 seqcol representation of every manifest and target collection, by digest

Refuses unless the targets that share a named-sequence-set digest are exactly those editions.json lists under one
label, and unless rebuilding each manifest row from its root and operations (in Python) gives its digests.

The sequence store (sequences, derivations) is made from every book's manifests at once (sequence_store).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from refbook import seqcol

from . import Refused, engine

IUPAC_TO_N = engine.IUPAC_TO_N
PAD = engine.PAD


def kind(root: str, member: dict | None, releases: set[str], latest: set[str], loose: dict[str, str]) -> str:
    """What sort of sequence a root is, for the contents facet. `releases` are the names of the book's assembly
    releases (a member of another assembly is an add-on), `latest` the roots of its last release, `loose` each
    loose root's kind (the name of the source that declares it, e.g. EBV)."""
    if root in loose:
        return loose[root]
    if root.startswith("IMGTHLA:"):
        return "HLA allele"
    if member is None:
        return "other"
    if member["assembly_name"] not in releases:
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
    """Members an entry's assembly and roles cover that the edition leaves out (e.g. patches placed on alt
    scaffolds), by role and reason."""
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


def collection_file(names, lengths, sequences, out: Path) -> tuple[str, dict]:
    """Write a collection's level-2 representation as collections/<digest>.json; return its seqcol digests."""
    top, level1 = seqcol.digests(names, lengths, sequences)
    (out / f"{top}.json").write_text(json.dumps(seqcol.level2(names, lengths, sequences)) + "\n")
    return top, level1


def build(assembly: str, recipes: list[dict], curated: list[dict], reproduced: list[dict], tables: dict,
          provenance: dict[str, dict], releases: set[str], loose: dict[str, str], out: Path) -> dict[str, list]:
    """The book's editions, manifests, targets and target_sequences rows; collections written under `out`."""
    recipes = {r["target"]: r for r in recipes}
    label_of = {t: f["label"] for f in curated for t in f["targets"]}
    target_meta = {t: m for f in curated for t, m in f["targets"].items()}
    if len({f["label"] for f in curated}) != len(curated):
        raise Refused("editions.json: a label is used twice")
    rows = defaultdict(list)
    for r in reproduced:
        rows[r["target"]].append(r)
    for v in rows.values():
        v.sort(key=lambda r: r["position"])
    if set(rows) != set(recipes) or set(rows) != set(label_of):
        raise Refused(f"targets differ between reproduced, recipes and editions.json: "
                      f"{sorted(set(rows) ^ set(label_of))}")

    by_digest = defaultdict(list)  # the curation must group targets exactly as their named sequence sets do
    for t, v in rows.items():
        by_digest[seqcol.named_set_digest([r["name"] for r in v], [r["sha512t24u"] for r in v])].append(t)
    for ts in by_digest.values():
        if len({label_of[t] for t in ts}) != 1:
            raise Refused(f"targets {sorted(ts)} are one named sequence set but labeled "
                          f"{sorted({label_of[t] for t in ts})}")
    if len(by_digest) != len(curated):
        raise Refused(f"{len(curated)} labels for {len(by_digest)} named sequence sets")

    members = tables["members"]
    member_of = {}
    for m in members:
        member_of.setdefault(m["genbank_accession"], m)
    in_releases = [m for m in members if m["assembly_name"] in releases]
    last = max(m["release"] for m in in_releases)
    latest = {m["genbank_accession"] for m in in_releases if m["release"] == last}
    collections = out / "collections"
    collections.mkdir()
    editions, manifests, targets, orders = [], [], [], []
    for digest, ts in sorted(by_digest.items(), key=lambda kv: label_of[kv[1][0]]):
        label = label_of[ts[0]]
        first = next(t for f in curated if f["label"] == label for t in f["targets"] if t in ts)
        recipe = recipes[first]
        compiled = {name: (root, ops) for name, root, ops in engine.compile(recipe, tables)}
        manifest = []
        for r in sorted(rows[first], key=lambda r: r["name"].encode()):
            acc = r["root_id"]
            if compiled.get(r["name"], (None,))[0] != acc:
                raise Refused(f"{label} {r['name']}: the recipe compiles to another root")
            ops = compiled[r["name"]][1]
            if ops:  # rebuilding from root and operations, in Python, must give the digests
                spans = tuple(s for m in ops if m not in (IUPAC_TO_N, PAD) for s in tables["spans"][m].get(acc, []))
                positions = tuple(tables["iupac"].get(acc, [])) if IUPAC_TO_N in ops else ()
                padding = engine.padding_of(tables, acc, ops)
                if engine.derivative_digests(tables["blocks"], acc, spans, positions, padding) != (
                        r["md5"], r["sha512t24u"]):
                    raise Refused(f"{label} {r['name']}: operations {ops} don't give its digests")
            elif (r["md5"], r["sha512t24u"]) != (tables["roots"][acc]["md5"], tables["roots"][acc]["sha512t24u"]):
                raise Refused(f"{label} {r['name']}: differs from root {acc}, with no operations")
            manifest.append({"edition": label, "name": r["name"], "root_id": acc, "operations": ops,
                             "length": r["length"], "md5": r["md5"], "sha512t24u": r["sha512t24u"]})
        manifests += manifest
        top, _ = collection_file([r["name"] for r in manifest], [r["length"] for r in manifest],
                                 [r["sha512t24u"] for r in manifest], collections)
        roots_used = {r["root_id"] for r in manifest}
        kinds = Counter(kind(r["root_id"], member_of.get(r["root_id"]), releases, latest, loose) for r in manifest)
        patch_releases = [m["release"] for m in members if m["genbank_accession"] in roots_used
                          and m["role"] in ("fix-patch", "novel-patch")]
        mask_layers = [m["layer"] for m in recipe.get("mask", [])]
        editions.append({
            "edition": label, "id": digest, "seqcol_digest": top,
            "n_sequences": len(manifest), "total_length": sum(r["length"] for r in manifest),
            "assembly": assembly, "patch_release": max(patch_releases) if patch_releases else None,
            "contents": [{"kind": k, "count": n} for k, n in sorted(kinds.items())],
            "excluded": excluded(recipe, members, roots_used),
            "operations": mask_layers + ([IUPAC_TO_N] if recipe.get("alphabet") else [])
                          + ([PAD] if recipe.get("pad") else []),
            "naming": naming(recipe["rename"]),
            "recipe": json.dumps({k: recipe[k] for k in ("select", "mask", "alphabet", "pad", "rename") if k in recipe},
                                 sort_keys=True),
            "n_targets": len(ts),
        })
        for t in ts:
            v, prov = rows[t], provenance[t]
            t_top, t_level1 = collection_file([x["name"] for x in v], [x["length"] for x in v],
                                              [x["sha512t24u"] for x in v], collections)
            targets.append({
                "target": t, "edition": label, **target_meta[t],
                "published": recipes[t]["published"], "checked_against": prov["url"],
                "evidence": prov["evidence"], "checked_sha256": prov["sha256"],
                "checked_bytes": int(prov["bytes"]), "checked_last_modified": prov["last_modified"],
                "n_sequences": len(v), "seqcol_digest": t_top,
                "seqcol_names": t_level1["names"], "seqcol_lengths": t_level1["lengths"],
                "seqcol_sequences": t_level1["sequences"],
            })
            orders += [{"target": t, "position": x["position"], "name": x["name"]} for x in v]
    return {"editions": editions, "manifests": manifests, "targets": targets, "target_sequences": orders}


def sequence_store(manifests: list[dict], roots: dict) -> tuple[list[dict], list[dict]]:
    """The sequences and derivations tables: every root as submitted, and every derivative a manifest uses, with
    each way it is made. A sequence's canonical derivation: fewest operations, then sorted names, then root."""
    ways = defaultdict(lambda: defaultdict(set))  # sq -> (root, operations) -> editions
    info = {}
    for acc, r in roots.items():
        ways[r["sha512t24u"]][acc, ()]
        info[r["sha512t24u"]] = (r["md5"], r["length"])
    for r in manifests:
        ways[r["sha512t24u"]][r["root_id"], tuple(r["operations"])].add(r["edition"])
        info[r["sha512t24u"]] = (r["md5"], r["length"])
    sequences, derivations = [], []
    for sq in sorted(ways):
        root, ops = min(ways[sq], key=lambda w: (len(w[1]), sorted(w[1]), w[0]))
        md5, length = info[sq]
        sequences.append({"sha512t24u": sq, "md5": md5, "length": length, "root_id": root, "operations": list(ops),
                          "n_derivations": len(ways[sq])})
        for (acc, o), fl in sorted(ways[sq].items()):
            derivations.append({"sha512t24u": sq, "root_id": acc, "operations": list(o), "editions": sorted(fl)})
    return sequences, derivations
