"""Build the GRCh38 annotation layers from the raw NCBI downloads.

Reads REGISTRY/raw (see fetch_grch38.sh) and REGISTRY/build/grch38/roots.parquet,
and writes Parquet to REGISTRY/build/grch38:

- layer_agp.parquet   one row per AGP part of each root's component-level AGP
                      (*.comp.agp.gz, *.scaf.agp.gz); start/end are 0-based
                      half-open on the root, component_start/end likewise on
                      the component. Gap rows have null component columns and
                      vice versa.

A root's AGP is the same in every release (checked by check_gaps.py and again
here), so each root appears once.

Usage: uv run --with pyarrow python build_layers.py REGISTRY_DIR
"""

import argparse
import gzip
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

NCBI = "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405"


# Known disagreements between genomic_regions_definitions.txt (authoritative
# here) and assembly_regions.txt, as (release, region_name, root_id).
REGION_QUIRKS = {
    (2, "REGION1A", "KI270905.1"),  # defined, missing from p2's assembly_regions
    (13, "AFCT06", "KI270752.1"),   # only in p13's assembly_regions; no scaffold
}


def release_number(release: Path) -> int:
    """0 for GRCh38 (GCA_000001405.15), 14 for GRCh38.p14 (.29)."""
    return int(release.name.split("_")[1].split(".")[1]) - 15


def releases(raw: Path) -> list[Path]:
    dirs = sorted(
        (raw / NCBI).glob("GCA_000001405.*_GRCh38*"),
        key=lambda p: int(p.name.split("_")[1].split(".")[1]),
    )
    return [d for d in dirs if 15 <= int(d.name.split("_")[1].split(".")[1]) <= 29]


def agp_files(release: Path) -> list[Path]:
    return sorted(p for p in release.glob("*_assembly_structure/**/AGP/*.agp.gz")
                  if p.name.endswith((".comp.agp.gz", ".scaf.agp.gz")))


def read_agp(path: Path) -> dict[str, list[tuple]]:
    """object -> AGP rows, as tuples of the (string) columns after `object`."""
    objs = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            objs.setdefault(cols[0], []).append(tuple(cols[1:]))
    return objs


def build_agp(raw: Path, roots: set[str]) -> pa.Table:
    agp, source = {}, {}
    for d in releases(raw):
        for path in agp_files(d):
            for obj, rows in read_agp(path).items():
                if obj not in roots:
                    continue  # placed scaffolds are AGP objects but not roots
                if obj in agp and agp[obj] != rows:
                    sys.exit(f"{obj}: AGP in {path} differs from {source[obj]}")
                if obj not in agp:
                    agp[obj], source[obj] = rows, path
    if roots - set(agp):
        sys.exit(f"no AGP for: {sorted(roots - set(agp))}")

    cols = {k: [] for k in (
        "root_id", "part_number", "start", "end", "component_type",
        "component_id", "component_start", "component_end", "orientation",
        "gap_length", "gap_type", "linkage", "linkage_evidence", "source",
    )}
    raw_prefix = len(str(raw)) + 1
    for obj in sorted(agp):
        url = "https://" + str(source[obj])[raw_prefix:]
        for r in agp[obj]:
            gap = r[3] in ("N", "U")
            cols["root_id"].append(obj)
            cols["part_number"].append(int(r[2]))
            cols["start"].append(int(r[0]) - 1)
            cols["end"].append(int(r[1]))
            cols["component_type"].append(r[3])
            cols["component_id"].append(None if gap else r[4])
            cols["component_start"].append(None if gap else int(r[5]) - 1)
            cols["component_end"].append(None if gap else int(r[6]))
            cols["orientation"].append(None if gap else r[7])
            cols["gap_length"].append(int(r[4]) if gap else None)
            cols["gap_type"].append(r[5] if gap else None)
            cols["linkage"].append((r[6] == "yes") if gap else None)
            cols["linkage_evidence"].append(
                (None if r[7] == "na" else r[7]) if gap else None)
            cols["source"].append(url)
    return pa.table(cols)


def read_tsv(path: Path, header_prefix: str) -> list[dict]:
    """Rows of a tab-separated file whose header is the `#` line starting with header_prefix."""
    rows, header = [], None
    for line in path.read_text().splitlines():
        if line.startswith(header_prefix):
            header = line.lstrip("# ").split("\t")
        elif line and not line.startswith("#"):
            rows.append(dict(zip(header, line.split("\t"))))
    return rows


def constant(table: dict, key, value, where: str) -> None:
    """Record value under key, exiting if a previous release gave a different one."""
    if table.setdefault(key, value) != value:
        sys.exit(f"{key}: {where} disagrees with an earlier release\n"
                 f"  was {table[key]}\n  now {value}")


def release_ranges(by_release: dict) -> list[tuple]:
    """{(key, release): value} -> [(key, value, first_release, last_release)],
    one entry per run of consecutive releases with the same value."""
    out = []
    for (key, n), value in sorted(by_release.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        if out and out[-1][0] == key and out[-1][1] == value and out[-1][3] == n - 1:
            out[-1] = (key, value, out[-1][2], n)
        else:
            out.append((key, value, n, n))
    return out


def build_regions(raw: Path, members: list[dict]) -> pa.Table:
    """Named regions (alt loci regions, CEN, PAR, HET) on the chromosomes, and
    on the alt scaffolds that patches are placed on.

    Keyed by (region_name, chromosome): the PARs share a name across X and Y.
    A region's span can change between releases (they grow to fit new
    patches), so there is one row per distinct span, with the range of
    releases it holds for. Also returns {(name, chromosome, release): span}.
    """
    by_release, rtype = {}, {}
    for d in releases(raw):
        rel = d.name.split("_", 2)[2]
        n = release_number(d)
        # The report's "Chromosome" is a chromosome name, or the sequence name
        # of an alt scaffold when the region is on one (patches to alts).
        chrom = {m["sequence_name"]: m["genbank_accession"] for m in members
                 if m["assembly_name"] == rel}
        chrom.update({m["assigned_molecule"]: m["genbank_accession"] for m in members
                      if m["assembly_name"] == rel and m["role"] == "assembled-molecule"})
        defs = read_tsv(d / f"{d.name}_assembly_structure" / "genomic_regions_definitions.txt",
                        "#region_name")
        for r in defs:
            key = (r["region_name"], r["chromosome"], n)
            if key in by_release:
                sys.exit(f"{key}: defined twice")
            by_release[key] = (int(r["start"]) - 1, int(r["stop"]))
        reported = set()
        for r in read_tsv(d / f"{d.name}_assembly_regions.txt", "# Region-Name"):
            key = (r["Region-Name"], chrom[r["Chromosome"]])
            reported.add(key)
            if (n,) + key in REGION_QUIRKS:
                continue
            span = (int(r["Chromosome-Start"]) - 1, int(r["Chromosome-Stop"]))
            if by_release.get(key + (n,)) != span:
                sys.exit(f"{key}: assembly_regions != definitions in {d.name}")
            role = r["Scaffold-Role"]
            if role in ("CEN", "PAR", "HET"):
                constant(rtype, key, role, d.name)
            elif role in ("alt-scaffold", "fix-patch", "novel-patch", "na"):
                rtype.setdefault(key, None)
            else:
                sys.exit(f"{key}: unknown Scaffold-Role {role!r}")
        for name, c, m in by_release:
            if m == n and (name, c) not in reported and (n, name, c) not in REGION_QUIRKS:
                sys.exit(f"{(name, c)}: in definitions but not assembly_regions in {d.name}")
    rows = release_ranges({((name, c), n): span for (name, c, n), span in by_release.items()})
    rows.sort(key=lambda r: (r[0][1], r[1], r[0][0], r[2]))
    table = pa.table({
        "region_name": [k[0] for k, *_ in rows],
        "root_id": [k[1] for k, *_ in rows],
        "start": [v[0] for _, v, *_ in rows],
        "end": [v[1] for _, v, *_ in rows],
        "region_type": [rtype.get(k) for k, *_ in rows],
        "first_release": [f for *_, f, _ in rows],
        "last_release": [last for *_, last in rows],
    })
    return table, by_release


def build_placements(raw: Path, members: list[dict], length: dict,
                     region_spans: dict) -> pa.Table:
    """Where each alt scaffold and patch sits on its parent (a chromosome, or an
    alt scaffold for patches to alts). NCBI revises some placements between
    releases, so there is one row per distinct placement with its release range.
    """
    place, ptype = {}, {}
    for d in releases(raw):
        rel = d.name.split("_", 2)[2]
        s = d / f"{d.name}_assembly_structure"
        rows = read_tsv(s / "all_alt_scaffold_placement.txt", "#alt_asm_name")
        role = {m["genbank_accession"]: m["role"] for m in members
                if m["assembly_name"] == rel}
        want = {a for a, r in role.items() if r in ("alt-scaffold", "fix-patch", "novel-patch")}
        got = [r["alt_scaf_acc"] for r in rows]
        if len(got) != len(set(got)) or set(got) != want:
            sys.exit(f"{d.name}: placements != alt/patch members of the report")
        for r in rows:
            if r["parent_acc"] == "na":
                # Member but not placed (KI270825.1 in p14, after FCS found a
                # bacterial tail): its placement rows end at the release before.
                print(f"{r['alt_scaf_acc']}: no placement in {d.name}", file=sys.stderr)
                continue
            rs = region_spans.get((r["region_name"], r["parent_acc"], release_number(d)))
            if (rs is None or int(r["parent_start"]) - 1 < rs[0]
                    or int(r["parent_stop"]) > rs[1]):
                sys.exit(f"{r['alt_scaf_acc']}: placement outside region "
                         f"{r['region_name']} in {d.name}")
            place[r["alt_scaf_acc"], release_number(d)] = (
                r["alt_asm_name"], r["alt_scaf_name"], r["parent_type"].lower(),
                r["parent_acc"], r["region_name"],
                r["ori"], int(r["alt_scaf_start"]) - 1, int(r["alt_scaf_stop"]),
                int(r["parent_start"]) - 1, int(r["parent_stop"]),
                int(r["alt_start_tail"]), int(r["alt_stop_tail"]))
        pt = s / "PATCHES" / "alt_scaffolds" / "patch_type"
        for r in read_tsv(pt, "#alt_scaf_name") if pt.exists() else []:
            constant(ptype, r["alt_scaf_acc"], r["patch_type"], d.name)
            if role[r["alt_scaf_acc"]] != r["patch_type"].lower() + "-patch":
                sys.exit(f"{r['alt_scaf_acc']}: patch_type != report role in {d.name}")

    cols = {k: [] for k in (
        "root_id", "assembly_unit", "scaffold_name", "parent_type", "parent_id",
        "region_name",
        "orientation", "start", "end", "parent_start", "parent_end",
        "start_tail", "end_tail", "patch_type", "first_release", "last_release",
    )}
    for acc, p, first, last in release_ranges(place):
        unit, s, e, st, et = p[0], p[6], p[7], p[10], p[11]
        if st + (e - s) + et != length[acc]:
            sys.exit(f"{acc}: tails + aligned span != length")
        if (unit == "PATCHES") != (acc in ptype):
            sys.exit(f"{acc}: patch_type missing or on a non-patch")
        for k, v in zip(cols, (acc, *p, ptype.get(acc), first, last)):
            cols[k].append(v)
    return pa.table(cols)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    args = ap.parse_args()
    raw = args.registry / "raw"
    out = args.registry / "build" / "grch38"
    roots = pq.read_table(out / "roots.parquet", columns=["root_id", "length"])
    length = dict(zip(roots["root_id"].to_pylist(), roots["length"].to_pylist()))
    members = pq.read_table(out / "assembly_members.parquet").to_pylist()

    agp = build_agp(raw, set(length))
    pq.write_table(agp, out / "layer_agp.parquet", compression="zstd")
    print(f"layer_agp: {agp.num_rows} parts on {len(length)} roots", file=sys.stderr)

    regions, region_spans = build_regions(raw, members)
    pq.write_table(regions, out / "layer_regions.parquet", compression="zstd")
    print(f"layer_regions: {regions.num_rows} region spans", file=sys.stderr)

    placements = build_placements(raw, members, length, region_spans)
    pq.write_table(placements, out / "layer_placements.parquet", compression="zstd")
    print(f"layer_placements: {placements.num_rows} alt scaffolds and patches",
          file=sys.stderr)


if __name__ == "__main__":
    main()
