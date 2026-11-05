"""Build the GRCh38 annotation layers from the raw NCBI downloads.

Reads REGISTRY/raw (see 00_fetch_inputs.sh) and the roots (10_roots), and
writes Parquet to REGISTRY/build/grch38/20_layers/:

- layer_agp.parquet   one row per AGP part of each root's component-level AGP
                      (*.comp.agp.gz, *.scaf.agp.gz of GRCh38 and hs38d1; EBV,
                      in no assembly, has none); start/end are 0-based
                      half-open on the root, component_start/end likewise on
                      the component. Gap rows have null component columns and
                      vice versa. `object_rank` is the root's position among
                      the objects of its `source` file (flavors order by it).
- layer_regions.parquet, layer_placements.parquet   see build_regions and
                      build_placements
- layer_hardmask_grc.parquet   the spans the GRC hard-masks with N in its
                      analysis sets (CEN/WGS duplicates on chr5, 14, 19, 21,
                      22; PAR on chrY), with each span's unmasked cognate

A root's AGP is the same in every release (checked by 60_check_gaps.py and again
here), so each root appears once.

Usage: uv run python -I pipeline/20_layers.py REGISTRY_DIR [--assembly grch38]
"""

import argparse
import gzip
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout

STEP = "20_layers"

# Known disagreements between genomic_regions_definitions.txt (authoritative
# here) and assembly_regions.txt, as (release, region_name, root_id).
REGION_QUIRKS = {
    (2, "REGION1A", "KI270905.1"),  # defined, missing from p2's assembly_regions
    (13, "AFCT06", "KI270752.1"),   # only in p13's assembly_regions; no scaffold
}


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


def agp_record(r: tuple) -> dict:
    """One AGP row (the columns after `object`) as a layer_agp record, 0-based
    half-open on both the object and the component; gap rows have null
    component columns and vice versa."""
    gap = r[3] in ("N", "U")
    return {
        "part_number": int(r[2]), "start": int(r[0]) - 1, "end": int(r[1]),
        "component_type": r[3],
        "component_id": None if gap else r[4],
        "component_start": None if gap else int(r[5]) - 1,
        "component_end": None if gap else int(r[6]),
        "orientation": None if gap else r[7],
        "gap_length": int(r[4]) if gap else None,
        "gap_type": r[5] if gap else None,
        "linkage": (r[6] == "yes") if gap else None,
        "linkage_evidence": (None if r[7] == "na" else r[7]) if gap else None,
    }


def build_agp(raw: Path, roots: set[str]) -> pa.Table:
    """AGP of every root in `roots` (the assembly members; EBV has none)."""
    agp, source, rank = {}, {}, {}
    for d in layout.assembly_dirs(raw):
        for path in agp_files(d):
            for i, (obj, rows) in enumerate(read_agp(path).items()):
                if obj not in roots:
                    continue  # placed scaffolds are AGP objects but not roots
                if obj in agp and agp[obj] != rows:
                    sys.exit(f"{obj}: AGP in {path} differs from {source[obj]}")
                if obj not in agp:
                    agp[obj], source[obj], rank[obj] = rows, path, i
    if roots - set(agp):
        sys.exit(f"no AGP for: {sorted(roots - set(agp))}")

    cols = {k: [] for k in (
        "root_id", "part_number", "start", "end", "component_type",
        "component_id", "component_start", "component_end", "orientation",
        "gap_length", "gap_type", "linkage", "linkage_evidence", "source",
        "object_rank",
    )}
    raw_prefix = len(str(raw)) + 1
    for obj in sorted(agp):
        url = "https://" + str(source[obj])[raw_prefix:]
        for r in agp[obj]:
            rec = agp_record(r)
            rec.update(root_id=obj, source=url, object_rank=rank[obj])
            for k, v in cols.items():
                v.append(rec[k])
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
    for d in layout.release_dirs(raw):
        rel = d.name.split("_", 2)[2]
        n = layout.release_number(d)
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
    for d in layout.release_dirs(raw):
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
            rs = region_spans.get((r["region_name"], r["parent_acc"], layout.release_number(d)))
            if (rs is None or int(r["parent_start"]) - 1 < rs[0]
                    or int(r["parent_stop"]) > rs[1]):
                sys.exit(f"{r['alt_scaf_acc']}: placement outside region "
                         f"{r['region_name']} in {d.name}")
            place[r["alt_scaf_acc"], layout.release_number(d)] = (
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


def build_hardmask_grc(raw: Path, length: dict, regions: pa.Table) -> pa.Table:
    """The GRC analysis-set hard masks, from unmasked_cognates_of_masked_CEN_PAR.txt.

    Each masked span is an exact duplicate of its unmasked cognate, so the two
    must have the same length; the chrY spans must be its PAR regions.
    """
    path = (layout.release_dir(raw, 0) / "seqs_for_alignment_pipelines.ucsc_ids"
            / "unmasked_cognates_of_masked_CEN_PAR.txt")
    cols = {k: [] for k in ("root_id", "start", "end", "name", "cognate_root_id",
                            "cognate_start", "cognate_end", "cognate_name")}
    for r in read_tsv(path, "#masked_copy_chr_accn"):
        span = (r["masked_copy_chr_accn"], int(r["masked_copy_start"]) - 1,
                int(r["masked_copy_stop"]))
        cog = (r["unmasked_cognate_chr_accn"], int(r["unmasked_cognate_start"]) - 1,
               int(r["unmasked_cognate_stop"]))
        if span[2] - span[1] != cog[2] - cog[1]:
            sys.exit(f"{span}: masked span and cognate {cog} differ in length")
        if span[2] > length[span[0]] or cog[2] > length[cog[0]]:
            sys.exit(f"{span}: past the end of the root")
        for k, v in zip(cols, (*span, r["masked_scaf_or_region_name"], *cog,
                               r["unmasked_scaf_or_region_name"])):
            cols[k].append(v)
    par_y = sorted((s, e) for n, a, s, e, t, f in zip(*(regions[c].to_pylist() for c in (
        "region_name", "root_id", "start", "end", "region_type", "first_release")))
        if t == "PAR" and a == "CM000686.2" and f == 0)
    masked_y = sorted((s, e) for a, s, e in zip(cols["root_id"], cols["start"], cols["end"])
                      if a == "CM000686.2")
    if par_y != masked_y:
        sys.exit(f"chrY masks {masked_y} != PAR regions {par_y}")
    return pa.table(cols)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("--assembly", default=layout.ASSEMBLY)
    args = ap.parse_args()
    if args.assembly != "grch38":
        sys.exit(f"{args.assembly}: only grch38's sources are defined (see layout.py)")
    build = layout.build_dir(args.registry, args.assembly)
    with layout.step_output(build, STEP) as out:
        run(layout.raw_dir(args.registry), build, out)
        layout.record_inputs(out, STEP, layout.INPUTS_LOCK)


def run(raw: Path, build: Path, out: Path) -> None:
    roots = pq.read_table(layout.path(build, "roots.parquet"), columns=["root_id", "length"])
    length = dict(zip(roots["root_id"].to_pylist(), roots["length"].to_pylist()))
    members = pq.read_table(layout.path(build, "assembly_members.parquet")).to_pylist()

    in_assembly = {m["genbank_accession"] for m in members}
    agp = build_agp(raw, in_assembly)
    pq.write_table(agp, out / "layer_agp.parquet", compression="zstd")
    print(f"layer_agp: {agp.num_rows} parts on {len(in_assembly)} roots", file=sys.stderr)

    regions, region_spans = build_regions(raw, members)
    pq.write_table(regions, out / "layer_regions.parquet", compression="zstd")
    print(f"layer_regions: {regions.num_rows} region spans", file=sys.stderr)

    placements = build_placements(raw, members, length, region_spans)
    pq.write_table(placements, out / "layer_placements.parquet", compression="zstd")
    print(f"layer_placements: {placements.num_rows} alt scaffolds and patches",
          file=sys.stderr)

    hardmask = build_hardmask_grc(raw, length, regions)
    pq.write_table(hardmask, out / "layer_hardmask_grc.parquet", compression="zstd")
    print(f"layer_hardmask_grc: {hardmask.num_rows} spans, "
          f"{sum(e - s for s, e in zip(hardmask['start'].to_pylist(), hardmask['end'].to_pylist()))} bp",
          file=sys.stderr)


if __name__ == "__main__":
    main()
