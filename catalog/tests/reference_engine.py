"""The Python recipe compiler the Rust core replaced, frozen as its oracle.

select and name_of are catalog/engine.py's as of the switch-over; compile
gives the operations as 41_flavors.py derived them. test_golden.py checks
the core against compile, row for row, on every recipe.
"""

import sys

IUPAC_TO_N = "iupac_to_n"


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
NAMESPACES = {"ucsc": "ucsc_name", "sequence": "sequence_name", "grc": "sequence_name",
              "genbank": "genbank_accession", "refseq": "refseq_accession"}


def compile(recipe: dict, t: dict) -> list[tuple[str, str, list[str]]]:
    """(name, root_id, operations), in canonical order (by name, code point)."""
    sel = select(recipe, t["members"], t["roots"], t["external"], t["parent_types"])
    for s in sel:
        s["name"] = name_of(s, recipe["rename"])
    names = [s["name"] for s in sel]
    if len(names) != len(set(names)):
        sys.exit(f"{recipe['flavor']}: a name is used twice")
    layers = [m["layer"] for m in recipe.get("mask", [])]
    alphabet = bool(recipe.get("alphabet"))
    out = []
    for s in sorted(sel, key=lambda s: s["name"].encode()):
        acc = s["root_id"]
        ops = [m for m in layers if t["spans"][m].get(acc)]
        if alphabet and t["iupac"].get(acc):
            ops.append(IUPAC_TO_N)
        out.append((s["name"], acc, ops))
    return out
