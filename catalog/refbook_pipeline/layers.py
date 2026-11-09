"""The annotation layers of a book, from its assembly sources:

- layer_agp            one row per AGP part of each member root's component-level AGP (*.comp.agp.gz,
                       *.scaf.agp.gz of its releases and add-ons), 0-based half-open on the root and on the component.
                       Gap rows have null component columns and vice versa. `object_rank` is the root's position
                       among the objects of its `source` file (editions order by it). A root's AGP must be the same
                       in every release (and every book) that has it, so each root appears once: its first
                       release's, but where releases differ only in annotation, the latest release's: GRCh37 p0..p2
                       wrote AGP 1.1, then 2.0 (gap type, linkage, evidence), and p12 revised component types. A
                       revision of the layout itself is accepted only for the roots the book lists (`revised`). A minted root
                       with a BED of its parts (hs37d5's decoys) has the AGP that BED gives (build_agp_bed).
- layer_regions        named regions (alt loci regions, CEN, PAR, HET) on the chromosomes, and on the alt scaffolds
                       patches are placed on: one row per distinct span, with the releases it holds for
- layer_placements     where each alt scaffold and patch sits on its parent, one row per distinct placement, with
                       the releases it holds for
- layer_hardmask_grc   the spans the GRC's analysis sets replace with N, each with its unmasked cognate
- layer_par_y          chrY's pseudoautosomal regions, from the region definitions: what an edition writes as N
                       when it masks only the PARs
- layer_<derived mask> spans a published masked file writes as N where the root has bases, read from the file
                       itself where no file gives them (T2T's DJ/rDNA/PHR analysis sets: build_derived_mask)
- layer_padding        each alt scaffold's and patch's placement in the latest release that places it, and its
                       parent's length: what the `pad` operation (N-padding into the parent's coordinates) reads

The root-keyed layers (AGP, hard-mask, PAR, padding) serve every book whose roots they cover. Regions and placements are
numbered by release, which means something only within a book, so the catalog's
tables carry the book. Each function refuses what the reports don't bear out, and returns its notes (what it
accepted and why) for the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from refbook.parse import open_compressed

from . import Refused
from .members import release_of


@dataclass(frozen=True)
class Release:
    number: int          # the patch number: 0 for GRCh38
    name: str            # GRCh38.p2
    directory: Path      # its NCBI directory under raw/, e.g. raw/.../GCA_000001405.17_GRCh38.p2
    url: str             # that directory's URL
    structure: Path | None  # its assembly structure: <directory>/<asm>_assembly_structure, an archived copy, or
                            # none published (T2T-CHM13v1.0)

    @classmethod
    def of(cls, raw: Path, base: str, archive: str = "", number: int | None = None,
           unstructured: bool = False) -> Release:
        """The release whose NCBI directory is raw/<base>, numbered `number` (its place among its book's releases;
        by default its name's patch number). `archive`: the raw path of a directory holding its assembly structure
        as release-named subdirectories (NCBI's old_genbank archive, for a release whose directory no longer has it).
        `unstructured`: no assembly structure is published for it anywhere."""
        name = base.rsplit("/", 1)[-1].split("_", 2)[2]
        d = raw / base
        structure = None if unstructured else raw / archive / name if archive else structure_of(d)
        return cls(release_of(name) if number is None else number, name, d, f"https://{base}", structure)


def structure_of(directory: Path) -> Path:
    """An NCBI assembly directory's assembly structure tree."""
    return directory / f"{directory.name}_assembly_structure"


def agp_files(structure: Path) -> list[Path]:
    return sorted(p for p in structure.glob("**/AGP/*.agp.gz")
                  if p.name.endswith((".comp.agp.gz", ".scaf.agp.gz")))


def read_agp(path: Path) -> dict[str, list[tuple]]:
    """object -> AGP rows, as tuples of the (string) columns after `object`."""
    objs = {}
    with open_compressed(path, "rt") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            objs.setdefault(cols[0], []).append(tuple(cols[1:]))
    return objs


def agp_record(r: tuple) -> dict:
    """One AGP row (the columns after `object`) as a layer_agp record."""
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


AGP_COLUMNS = ["root_id", "part_number", "start", "end", "component_type", "component_id", "component_start",
               "component_end", "orientation", "gap_length", "gap_type", "linkage", "linkage_evidence", "source",
               "object_rank"]


def build_agp_bed(path: Path, url: str, name: str, root_id: str, length: int) -> list[dict]:
    """The AGP of a root concatenated from parts, from the BED that maps it to them (hs37d5cs.bed: the root's
    FASTA `name`, start, end, then `accession:start-end` 1-based, the part's source). Each part is a component of
    type O (other sequence) on the + strand: the BED gives no strand, and the parts checked against GenBank (2 of
    hs37d5's 4,715) match as is. What lies between parts is a gap of type N, gap_type contig, unlinked: AGP's
    nearest terms for the Ns a concatenation puts between unrelated sequences. The parts and gaps must tile the
    root."""
    rows, at = [], 0
    for line in path.read_text().splitlines():
        obj, s, e, part = line.split("\t")[:4]
        s, e = int(s), int(e)
        if obj != name:
            raise Refused(f"{path.name}: {obj} is not {name}")
        acc, _, span = part.rpartition(":")
        cs, ce = (int(x) for x in span.split("-"))
        if ce - cs + 1 != e - s or s < at:
            raise Refused(f"{path.name}: {line!r}: its part's span or its place doesn't fit")
        if s > at:
            rows.append({"start": at, "end": s, "component_type": "N", "gap_length": s - at,
                         "gap_type": "contig", "linkage": False})
        rows.append({"start": s, "end": e, "component_type": "O", "component_id": acc, "component_start": cs - 1,
                     "component_end": ce, "orientation": "+"})
        at = e
    if at != length:
        raise Refused(f"{path.name}: its parts end at {at}, {root_id} has {length} bases")
    out = []
    for i, r in enumerate(rows, 1):
        rec = {k: None for k in AGP_COLUMNS}
        rec.update(r, root_id=root_id, part_number=i, source=url, object_rank=0)
        out.append(rec)
    return out


def agp_parts(rows: list[tuple]) -> list[tuple]:
    """An AGP's layout, without its annotation (component type; gap type, linkage, evidence): each row's span and
    part number, then its component's ID, span and orientation, or its gap length."""
    return [r[:3] + (("gap", r[4]) if r[3] in ("N", "U") else tuple(r[4:8])) for r in rows]


def build_agp(raw: Path, structures: list[Path], roots: set[str], extra: list[dict] = (),
              notes: list[str] | None = None, revised: set[str] = frozenset()) -> pa.Table:
    """The AGP of every root in `roots` (the members; a loose root has none), from the assembly structure trees in
    release order: a root's source is the first file that has it, or the latest that annotates it otherwise, or
    (for a root in `revised`) that lays it out otherwise; each such change is added to `notes`. Then the `extra`
    rows (build_agp_bed's)."""
    agp, source, rank, used = {}, {}, {}, set()
    for d in structures:
        for path in agp_files(d):
            for i, (obj, rows) in enumerate(read_agp(path).items()):
                if obj not in roots:
                    continue  # placed scaffolds are AGP objects but not roots
                if obj in agp and agp[obj] != rows:
                    relaid = agp_parts(agp[obj]) != agp_parts(rows)
                    if relaid and obj not in revised:
                        raise Refused(f"{obj}: AGP in {path} differs from {source[obj]}")
                    used |= {obj} if relaid else set()
                    if notes is not None:
                        how = "revised (declared)" if relaid else "annotated otherwise"
                        notes.append(f"{obj}: AGP {how} in {path.relative_to(raw)}; kept")
                    agp[obj], source[obj], rank[obj] = rows, path, i
                if obj not in agp:
                    agp[obj], source[obj], rank[obj] = rows, path, i
    if roots - set(agp):
        raise Refused(f"no AGP for: {sorted(roots - set(agp))[:10]}")
    if revised - used:
        raise Refused(f"declared AGP revisions that no release makes: {sorted(revised - used)}")
    cols = {k: [] for k in AGP_COLUMNS}
    for obj in sorted(agp):
        url = "https://" + source[obj].relative_to(raw).as_posix()
        for r in agp[obj]:
            rec = agp_record(r)
            rec.update(root_id=obj, source=url, object_rank=rank[obj])
            for k, v in cols.items():
                v.append(rec[k])
    if {r["root_id"] for r in extra} & set(agp):
        raise Refused("a root has an AGP from both a structure tree and a BED")
    for rec in sorted(extra, key=lambda r: (r["root_id"], r["part_number"])):
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
    """Record value under key, refusing if a previous release gave a different one."""
    if table.setdefault(key, value) != value:
        raise Refused(f"{key}: {where} disagrees with an earlier release (was {table[key]}, now {value})")


def release_ranges(by_release: dict) -> list[tuple]:
    """{(key, release): value} -> [(key, value, first_release, last_release)], one entry per run of consecutive
    releases with the same value."""
    out = []
    for (key, n), value in sorted(by_release.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        if out and out[-1][0] == key and out[-1][1] == value and out[-1][3] == n - 1:
            out[-1] = (key, value, out[-1][2], n)
        else:
            out.append((key, value, n, n))
    return out


def region_definitions(structure: Path, chrom: dict[str, str]) -> list[dict]:
    """A release's region definitions: genomic_regions_definitions.txt, and, if it defines no PAR (GRCh37's
    archived p0..p12 leave them out), the PARs of its Primary_Assembly/pseudoautosomal_region/par.txt (`chrom`:
    chromosome name -> accession)."""
    rows = read_tsv(structure / "genomic_regions_definitions.txt", "#region_name")
    par = structure / "Primary_Assembly" / "pseudoautosomal_region" / "par.txt"
    if par.exists() and not any(r["region_name"].startswith("PAR") for r in rows):
        rows += [{"region_name": r["PAR-Name"], "chromosome": chrom[r["Chr"]], "start": r["Start"], "stop": r["Stop"]}
                 for r in read_tsv(par, "#Chr")]
    return rows


def build_regions(releases: list[Release], members: list[dict],
                  quirks: set[tuple[int, str, str]]) -> tuple[pa.Table, dict]:
    """Named regions, keyed by (region_name, root): the PARs share a name across X and Y. A region's span can change
    between releases (they grow to fit new patches): one row per distinct span, with its releases. Also returns
    {(name, root, release): span}. genomic_regions_definitions.txt is authoritative (region_definitions); its
    release's assembly_regions.txt must agree, but for the book's `quirks`."""
    by_release, rtype = {}, {}
    for rel in releases:
        if rel.structure is None:
            continue  # no region definitions published (and no alts or patches to place)
        d, n = rel.directory, rel.number
        if not (rel.structure / "genomic_regions_definitions.txt").exists() and \
                not (d / f"{d.name}_assembly_regions.txt").exists():
            continue  # a release that names no regions (T2T-CHM13v1.1: neither file); one file alone still refuses
        # The report's "Chromosome" is a chromosome name, or an alt scaffold's sequence name (patches to alts).
        chrom = {m["sequence_name"]: m["genbank_accession"] for m in members if m["assembly_name"] == rel.name}
        chrom.update({m["assigned_molecule"]: m["genbank_accession"] for m in members
                      if m["assembly_name"] == rel.name and m["role"] == "assembled-molecule"})
        for r in region_definitions(rel.structure, chrom):
            key = (r["region_name"], r["chromosome"], n)
            if key in by_release:
                raise Refused(f"{key}: defined twice")
            by_release[key] = (int(r["start"]) - 1, int(r["stop"]))
        reported = set()
        for r in read_tsv(d / f"{d.name}_assembly_regions.txt", "# Region-Name"):
            key = (r["Region-Name"], chrom[r["Chromosome"]])
            reported.add(key)
            if (n,) + key in quirks:
                continue
            span = (int(r["Chromosome-Start"]) - 1, int(r["Chromosome-Stop"]))
            if by_release.get(key + (n,)) != span:
                raise Refused(f"{key}: assembly_regions != definitions in {d.name}")
            role = r["Scaffold-Role"]
            if role in ("CEN", "PAR", "HET"):
                constant(rtype, key, role, d.name)
            elif role in ("alt-scaffold", "fix-patch", "novel-patch", "na"):
                rtype.setdefault(key, None)
            else:
                raise Refused(f"{key}: unknown Scaffold-Role {role!r}")
        for name, c, m in by_release:
            if m == n and (name, c) not in reported and (n, name, c) not in quirks:
                raise Refused(f"{(name, c)}: in definitions but not assembly_regions in {d.name}")
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


PLACEMENT_COLUMNS = ["root_id", "assembly_unit", "scaffold_name", "parent_type", "parent_id", "region_name",
                     "orientation", "start", "end", "parent_start", "parent_end", "start_tail", "end_tail",
                     "patch_type", "first_release", "last_release"]


def placement_rows(structure: Path) -> tuple[list[dict], set[str] | None]:
    """A release's alt scaffold placements, and the assembly units they cover (None: every unit). From
    all_alt_scaffold_placement.txt, or (an archived structure lacks it) the units' alt_scaffold_placement.txt, in
    unit order: GRCh37 p0..p2 have none for their alt loci units, which were not yet placed that way."""
    whole = structure / "all_alt_scaffold_placement.txt"
    if whole.exists():
        return read_tsv(whole, "#alt_asm_name"), None
    files = sorted(structure.glob("*/alt_scaffolds/alt_scaffold_placement.txt"))
    return [r for f in files for r in read_tsv(f, "#alt_asm_name")], {f.parent.parent.name for f in files}


def build_placements(releases: list[Release], members: list[dict], length: dict[str, int],
                     region_spans: dict) -> tuple[pa.Table, list[str]]:
    """Where each alt scaffold and patch sits on its parent (a chromosome, or an alt scaffold for patches to alts).
    NCBI revises some placements between releases: one row per distinct placement, with its releases. Also returns
    the notes: members a release leaves unplaced, and units whose structure has no placements."""
    place, ptype, notes = {}, {}, []
    for rel in releases:
        if rel.structure is None:
            notes.append(f"{rel.name}: no assembly structure published, so no placements")
            continue
        d, s = rel.directory, rel.structure
        rows, units = placement_rows(s)
        here = [m for m in members if m["assembly_name"] == rel.name]
        role = {m["genbank_accession"]: m["role"] for m in here}
        placed = [m for m in here if m["role"] in ("alt-scaffold", "fix-patch", "novel-patch")]
        missing = sorted({m["assembly_unit"] for m in placed} - units) if units is not None else []
        notes += [f"{rel.name}: no placements for {u} (its structure has none)" for u in missing]
        want = {m["genbank_accession"] for m in placed if m["assembly_unit"] not in missing}
        got = [r["alt_scaf_acc"] for r in rows]
        if len(got) != len(set(got)) or set(got) != want:
            raise Refused(f"{d.name}: placements != the report's alt and patch members")
        for r in rows:
            if r["parent_acc"] == "na":
                # A member but not placed (KI270825.1 in p14: withdrawn by editing p14's files in 2025, after
                # FCS flagged a bacterial end; the cause is inferred): its placement ends at the release before.
                notes.append(f"{r['alt_scaf_acc']}: no placement in {rel.name}")
                continue
            rs = region_spans.get((r["region_name"], r["parent_acc"], rel.number))
            if rs is None or int(r["parent_start"]) - 1 < rs[0] or int(r["parent_stop"]) > rs[1]:
                raise Refused(f"{r['alt_scaf_acc']}: placement outside region {r['region_name']} in {d.name}")
            place[r["alt_scaf_acc"], rel.number] = (
                r["alt_asm_name"], r["alt_scaf_name"], r["parent_type"].lower(), r["parent_acc"], r["region_name"],
                r["ori"], int(r["alt_scaf_start"]) - 1, int(r["alt_scaf_stop"]),
                int(r["parent_start"]) - 1, int(r["parent_stop"]), int(r["alt_start_tail"]), int(r["alt_stop_tail"]))
        pt = s / "PATCHES" / "alt_scaffolds" / "patch_type"
        for r in read_tsv(pt, "#alt_scaf_name") if pt.exists() else []:
            constant(ptype, r["alt_scaf_acc"], r["patch_type"], d.name)
            if role[r["alt_scaf_acc"]] != r["patch_type"].lower() + "-patch":
                raise Refused(f"{r['alt_scaf_acc']}: patch_type != report role in {d.name}")
    cols = {k: [] for k in PLACEMENT_COLUMNS}
    for acc, p, first, last in release_ranges(place):
        unit, s, e, st, et = p[0], p[6], p[7], p[10], p[11]
        if st + (e - s) + et != length[acc]:
            raise Refused(f"{acc}: tails + aligned span != length")
        if (unit == "PATCHES") != (acc in ptype):
            raise Refused(f"{acc}: patch_type missing, or on a non-patch")
        for k, v in zip(cols, (acc, *p, ptype.get(acc), first, last)):
            cols[k].append(v)
    return pa.table(cols), notes


def build_hardmask_grc(path: Path, length: dict[str, int], regions: pa.Table, par_root: str) -> pa.Table:
    """The GRC analysis-set hard masks, from unmasked_cognates_of_masked_CEN_PAR.txt. Each masked span is an exact
    duplicate of its unmasked cognate, so the two must have the same length; the spans on `par_root` (chrY) must
    be its PAR regions in the first release."""
    cols = {k: [] for k in ("root_id", "start", "end", "name", "cognate_root_id", "cognate_start", "cognate_end",
                            "cognate_name")}
    for r in read_tsv(path, "#masked_copy_chr_accn"):
        span = (r["masked_copy_chr_accn"], int(r["masked_copy_start"]) - 1, int(r["masked_copy_stop"]))
        cog = (r["unmasked_cognate_chr_accn"], int(r["unmasked_cognate_start"]) - 1, int(r["unmasked_cognate_stop"]))
        if span[2] - span[1] != cog[2] - cog[1]:
            raise Refused(f"{span}: masked span and cognate {cog} differ in length")
        if span[2] > length[span[0]] or cog[2] > length[cog[0]]:
            raise Refused(f"{span}: past the end of the root")
        for k, v in zip(cols, (*span, r["masked_scaf_or_region_name"], *cog, r["unmasked_scaf_or_region_name"])):
            cols[k].append(v)
    par = sorted((s, e) for n, a, s, e, t, f in zip(*(regions[c].to_pylist() for c in (
        "region_name", "root_id", "start", "end", "region_type", "first_release")))
        if t == "PAR" and a == par_root and f == 0)
    masked = sorted((s, e) for a, s, e in zip(cols["root_id"], cols["start"], cols["end"]) if a == par_root)
    if par != masked:
        raise Refused(f"{par_root}'s masks {masked} != its PAR regions {par}")
    return pa.table(cols)


def build_par_y(regions: pa.Table, members: list[dict]) -> pa.Table:
    """layer_par_y: chrY's pseudoautosomal regions (the region definitions' PAR regions on the root assigned to
    molecule Y), the spans that editions write as N when they mask only the PARs (Ensembl, and so b37 and hs37d5).
    A PAR is the same in every release that defines it; refuses if a root's PARs differ between releases."""
    y = {m["genbank_accession"] for m in members if m["assigned_molecule"] == "Y" and m["role"] == "assembled-molecule"}
    spans = {}
    for r in regions.to_pylist():
        if r["region_type"] == "PAR" and r["root_id"] in y:
            span = (r["start"], r["end"])
            if spans.setdefault((r["root_id"], r["region_name"]), span) != span:
                raise Refused(f"{r['root_id']} {r['region_name']}: its span differs between releases")
    if y and not spans:
        raise Refused(f"no PAR regions on chrY ({sorted(y)})")
    rows = sorted(spans.items(), key=lambda kv: (kv[0][0], kv[1]))
    return pa.table({"root_id": [k[0] for k, _ in rows], "start": [s for _, (s, _) in rows],
                     "end": [e for _, (_, e) in rows], "name": [k[1] for k, _ in rows]})


def build_derived_mask(path: Path, url: str, roots: dict[str, str], root_bases) -> pa.Table:
    """A mask layer read from a published masked FASTA, for the publishers who give no BED of what they masked:
    on each of `roots` (its name in the file -> root ID), the runs of N in the file that cover a base the root has
    (`root_bases(root)` gives the root's). Refuses unless masking the root with those spans gives the file's
    sequence, base for base (case aside): the layer then reproduces the file exactly, whatever it did."""
    import re

    from refbook.parse import open_compressed
    seqs, name, buf = {}, None, []
    with open_compressed(path) as f:
        for line in f:
            if line.startswith(b">"):
                if name in roots:
                    seqs[name] = b"".join(buf).upper()
                name, buf = line[1:].split()[0].decode(), []
            elif name in roots:
                buf.append(line.rstrip())
    if name in roots:
        seqs[name] = b"".join(buf).upper()
    if set(seqs) != set(roots):
        raise Refused(f"{path.name}: no {sorted(set(roots) - set(seqs))}")
    cols = {"root_id": [], "start": [], "end": [], "derived_from": []}
    for name, root in sorted(roots.items(), key=lambda kv: kv[1]):
        s, r = seqs[name], bytes(root_bases(root))
        if len(s) != len(r):
            raise Refused(f"{path.name} {name}: {len(s)} bases, root {root} has {len(r)}")
        spans = [(m.start(), m.end()) for m in re.finditer(rb"N+", s) if r[m.start():m.end()].count(b"N") != m.end() - m.start()]
        masked = bytearray(r)
        for a, b in spans:
            masked[a:b] = b"N" * (b - a)
        if bytes(masked) != s:
            raise Refused(f"{path.name} {name}: masking root {root} with its N-runs doesn't give the file's sequence")
        for a, b in spans:
            for k, v in zip(cols, (root, a, b, url)):
                cols[k].append(v)
    return pa.table(cols, schema=pa.schema([("root_id", pa.string()), ("start", pa.int64()), ("end", pa.int64()),
                                            ("derived_from", pa.string())]))


def build_padding(placements: pa.Table, length: dict[str, int]) -> pa.Table:
    """layer_padding: for each placed root, the placement `pad` lays it out by (operations.rs: N for the parent's
    bases before parent_start, the whole root, reverse-complemented if orientation is "-", then N up to
    parent_length): the one in the latest release that places it. `revised` marks a root whose placement on its
    parent differs between releases; the recipe compiler refuses to pad it, since its padded sequence would depend
    on the release."""
    by_root = {}
    for p in placements.to_pylist():
        by_root.setdefault(p["root_id"], []).append(p)
    cols = {k: [] for k in ("root_id", "parent_id", "parent_start", "parent_end", "orientation", "parent_length",
                            "revised")}
    for root, ps in sorted(by_root.items()):
        latest = max(ps, key=lambda p: p["last_release"])
        if latest["parent_id"] not in length:
            raise Refused(f"{root}: its parent {latest['parent_id']} is not a root")
        if latest["parent_end"] > length[latest["parent_id"]]:
            raise Refused(f"{root}: placed past the end of {latest['parent_id']}")
        layouts = {(p["parent_id"], p["parent_start"], p["parent_end"], p["orientation"]) for p in ps}
        for k, v in zip(cols, (root, latest["parent_id"], latest["parent_start"], latest["parent_end"],
                               latest["orientation"], length[latest["parent_id"]], len(layouts) > 1)):
            cols[k].append(v)
    return pa.table(cols)
