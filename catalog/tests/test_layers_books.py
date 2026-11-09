"""Layers and books, on small inputs made here: release ranges, AGP rows, an AGP that differs between releases, a
release's name and number from its directory, the checks on a book's declaration, and its recipes."""

import gzip
import json

import pytest
from refbook_pipeline import Refused, books, layers, sources


def test_release_ranges_merge_consecutive_equal_values():
    by_release = {("a", 0): 1, ("a", 1): 1, ("a", 2): 2, ("a", 4): 2, ("b", 3): 1}
    assert layers.release_ranges(by_release) == [("a", 1, 0, 1), ("a", 2, 2, 2), ("a", 2, 4, 4), ("b", 1, 3, 3)]


def test_agp_rows_are_zero_based_with_gaps_apart():
    part = layers.agp_record(("1", "100", "1", "F", "AC1.1", "1", "100", "+"))
    assert (part["start"], part["end"], part["component_id"], part["component_start"], part["gap_length"]) == (
        0, 100, "AC1.1", 0, None)
    gap = layers.agp_record(("101", "150", "2", "N", "50", "scaffold", "yes", "paired-ends"))
    assert (gap["start"], gap["gap_length"], gap["gap_type"], gap["linkage"], gap["component_id"]) == (
        100, 50, "scaffold", True, None)
    assert layers.agp_record(("1", "10", "1", "U", "10", "contig", "no", "na"))["linkage_evidence"] is None


def agp(raw, release, rows):
    d = raw / release / f"{release}_assembly_structure" / "Primary_Assembly" / "AGP"
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / "chr1.comp.agp.gz", "wt") as f:
        f.writelines("\t".join(r) + "\n" for r in rows)
    return raw / release


def test_an_agp_must_be_the_same_in_every_release(tmp_path):
    row = ("CM1.1", "1", "100", "1", "F", "AC1.1", "1", "100", "+")
    a, b = agp(tmp_path, "GCA_1.1_T", [row]), agp(tmp_path, "GCA_1.2_T.p1", [row])
    t = layers.build_agp(tmp_path, [a, b], {"CM1.1"})
    assert t.num_rows == 1 and t["source"][0].as_py().startswith("https://GCA_1.1_T/")  # the first release's
    agp(tmp_path, "GCA_1.2_T.p1", [row[:2] + ("99",) + row[3:7] + ("99", "+")])
    with pytest.raises(Refused, match="CM1.1: AGP in .* differs"):
        layers.build_agp(tmp_path, [a, b], {"CM1.1"})
    with pytest.raises(Refused, match="no AGP for"):
        layers.build_agp(tmp_path, [a], {"CM1.1", "CM2.1"})


def test_a_release_is_named_and_numbered_by_its_directory(tmp_path):
    r = layers.Release.of(tmp_path, "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.17_GRCh38.p2")
    assert (r.number, r.name, r.directory.name) == (2, "GRCh38.p2", "GCA_000001405.17_GRCh38.p2")
    assert r.structure == r.directory / "GCA_000001405.17_GRCh38.p2_assembly_structure"
    assert layers.Release.of(tmp_path, "x/GCA_000001405.15_GRCh38").number == 0
    archived = layers.Release.of(tmp_path, "x/GCA_000001405.6_GRCh37.p5", archive="old/Homo_sapiens")
    assert archived.structure == tmp_path / "old/Homo_sapiens/GRCh37.p5"


PLACEMENT_HEADER = ("#alt_asm_name\tprim_asm_name\talt_scaf_name\talt_scaf_acc\tparent_type\tparent_name\t"
                    "parent_acc\tregion_name\tori\talt_scaf_start\talt_scaf_stop\tparent_start\tparent_stop\t"
                    "alt_start_tail\talt_stop_tail\n")


def test_placements_come_from_the_units_when_the_whole_list_is_missing(tmp_path):
    for unit, acc in (("ALT_REF_LOCI_1", "GL1.1"), ("PATCHES", "JH1.1")):
        d = tmp_path / unit / "alt_scaffolds"
        d.mkdir(parents=True)
        (d / "alt_scaffold_placement.txt").write_text(
            PLACEMENT_HEADER + f"{unit}\tPrimary Assembly\tX\t{acc}\tCHROMOSOME\t1\tCM1.1\tR\t+\t1\t9\t1\t9\t0\t0\n")
    rows, units = layers.placement_rows(tmp_path)
    assert [r["alt_scaf_acc"] for r in rows] == ["GL1.1", "JH1.1"] and units == {"ALT_REF_LOCI_1", "PATCHES"}
    assert layers.placement_rows(tmp_path / "PATCHES") == ([], set())  # no unit has placements
    (tmp_path / "all_alt_scaffold_placement.txt").write_text(PLACEMENT_HEADER)
    assert layers.placement_rows(tmp_path) == ([], None)  # the whole list, when there is one, for every unit


BED = "d\t0\t4\tAC1.1:11-14\nd\t6\t9\tAEKP1.1:1-3\n"


def test_a_bed_of_parts_gives_an_agp(tmp_path):
    (tmp_path / "d.bed").write_text(BED)
    rows = layers.build_agp_bed(tmp_path / "d.bed", "https://x/d.bed", "d", "P:d", 9)
    assert [(r["part_number"], r["start"], r["end"], r["component_type"], r["component_id"], r["component_start"],
             r["component_end"], r["orientation"], r["gap_length"], r["gap_type"], r["linkage"]) for r in rows] == [
        (1, 0, 4, "O", "AC1.1", 10, 14, "+", None, None, None),
        (2, 4, 6, "N", None, None, None, None, 2, "contig", False),
        (3, 6, 9, "O", "AEKP1.1", 0, 3, "+", None, None, None)]
    assert {r["root_id"] for r in rows} == {"P:d"} and set(rows[0]) == set(layers.AGP_COLUMNS)
    t = layers.build_agp(tmp_path, [], set(), rows)
    assert t["root_id"].to_pylist() == ["P:d"] * 3
    with pytest.raises(Refused, match="its parts end at 9, P:d has 10"):
        layers.build_agp_bed(tmp_path / "d.bed", "u", "d", "P:d", 10)
    (tmp_path / "d.bed").write_text(BED.replace("1-3", "1-4"))
    with pytest.raises(Refused, match="doesn't fit"):
        layers.build_agp_bed(tmp_path / "d.bed", "u", "d", "P:d", 9)


def declare(tmp_path, book_toml, recipes=None):
    (tmp_path / "s.toml").write_text('[[source]]\nname = "A"\nroles = ["input"]\n'
                                     '[[source]]\nname = "B"\nroles = ["target"]\n')
    d = tmp_path / "books" / "t"
    d.mkdir(parents=True)
    (d / "book.toml").write_text(book_toml)
    if recipes is not None:
        (d / "recipes").mkdir()
        (d / "recipes" / "r.json").write_text(json.dumps({"recipes": recipes}))
    return books.load(tmp_path / "books", sources.load(tmp_path / "s.toml"))


def test_a_book_names_only_declared_sources(tmp_path):
    b = declare(tmp_path, 'name = "t"\nreleases = ["A"]\nsources = ["A", "B"]\n')["t"]
    assert (b.releases, b.addons, b.sources) == (("A",), (), ("A", "B"))


@pytest.mark.parametrize(("toml", "match"), [
    ('name = "u"\nsources = ["A"]\n', "named u, its directory t"),
    ('name = "t"\nsources = ["A", "C"]\n', "not declared"),
    ('name = "t"\nreleases = ["B"]\nsources = ["A"]\n', "releases not among its sources"),
    ('name = "t"\nsources = ["A"]\n[hardmask_grc]\nsource = "B"\nfile = "x"\npar_root = "Y.1"\n',
     "hardmask_grc's source"),
])
def test_a_book_declaration_refuses(tmp_path, toml, match):
    with pytest.raises(Refused, match=match):
        declare(tmp_path, toml)


def test_a_release_without_its_structure_needs_an_archive(tmp_path):
    (tmp_path / "s.toml").write_text('[[source]]\nname = "R"\nroles = ["input"]\nncbi_assembly = "h/GCA_1.2_T.p1"\n'
                                     'structure = false\n[[source]]\nname = "Old"\nroles = ["input"]\nbase = "h/old"\n')
    d = tmp_path / "books" / "t"
    d.mkdir(parents=True)
    (d / "book.toml").write_text('name = "t"\nreleases = ["R"]\nsources = ["R", "Old"]\n')
    srcs = sources.load(tmp_path / "s.toml")
    assert srcs["R"].ncbi_assembly and not srcs["R"].structure and sources.reports(srcs["R"])
    with pytest.raises(Refused, match="no structure_archive"):
        books.load(tmp_path / "books", srcs)
    (d / "book.toml").write_text('name = "t"\nreleases = ["R"]\nsources = ["R", "Old"]\nstructure_archive = "Old"\n')
    b = books.load(tmp_path / "books", srcs)["t"]
    assert [r.structure for r in books.releases(b, srcs, tmp_path)] == [tmp_path / "h/old/T.p1"]


def test_releases_are_numbered_by_place_and_may_publish_no_structure(tmp_path):
    (tmp_path / "s.toml").write_text(
        '[[source]]\nname = "V1"\nroles = ["input"]\nncbi_assembly = "h/GCA_1.2_T-v1.0"\nstructure = false\n'
        '[[source]]\nname = "V2"\nroles = ["input"]\nncbi_assembly = "h/GCA_1.3_T-v1.1"\n')
    d = tmp_path / "books" / "t"
    d.mkdir(parents=True)
    (d / "book.toml").write_text('name = "t"\nreleases = ["V1", "V2"]\nsources = ["V1", "V2"]\n'
                                 '[[releases_without_structure]]\nrelease = "V1"\nwhy = "none published"\n')
    srcs = sources.load(tmp_path / "s.toml")
    b = books.load(tmp_path / "books", srcs)["t"]
    rels = books.releases(b, srcs, tmp_path)
    # Named T-v1.0 and T-v1.1 (no patch number): numbered 0 and 1 by their place.
    assert [(r.name, r.number, r.structure is None) for r in rels] == [("T-v1.0", 0, True), ("T-v1.1", 1, False)]
    assert books.release_order(b, srcs, tmp_path) == {"T-v1.0": 0, "T-v1.1": 1}
    (d / "book.toml").write_text('name = "t"\nreleases = ["V1", "V2"]\nsources = ["V1", "V2"]\n'
                                 '[[releases_without_structure]]\nrelease = "V3"\nwhy = "x"\n')
    with pytest.raises(Refused, match="releases_without_structure not among its releases"):
        books.load(tmp_path / "books", srcs)


def test_recipes_and_their_targets(tmp_path):
    declare(tmp_path, 'name = "t"\nsources = ["A"]\n', [
        {"target": "x", "published": "https://h/p/x.fa.gz"},
        {"target": "y", "published": "https://h/p/y.fa.gz", "observed_from": "https://h/p/y.dict"}])
    rs = books.recipes(tmp_path / "books", "t")
    assert [books.target_of(r) for r in rs] == ["h/p/x.fa.gz", "h/p/y.dict"]
    (tmp_path / "books" / "t" / "recipes" / "r2.json").write_text(json.dumps({"recipes": [rs[0]]}))
    with pytest.raises(Refused, match="more than one recipe"):
        books.recipes(tmp_path / "books", "t")


def test_par_y_takes_the_par_regions_on_the_y_chromosome_only():
    import pyarrow as pa
    def region(name, root, start, end, kind="PAR", first=0):
        return {"region_name": name, "root_id": root, "start": start, "end": end, "region_type": kind,
                "first_release": first, "last_release": first}
    members = [{"genbank_accession": "Y.1", "assigned_molecule": "Y", "role": "assembled-molecule"},
               {"genbank_accession": "X.1", "assigned_molecule": "X", "role": "assembled-molecule"}]
    regions = [region("PAR#1", "X.1", 60000, 2699520), region("PAR#1", "Y.1", 10000, 2649520),
               region("PAR#2", "Y.1", 59034049, 59363566), region("PAR#2", "Y.1", 59034049, 59363566, first=3),
               region("REGION108", "Y.1", 100, 200, kind=None)]
    t = layers.build_par_y(pa.Table.from_pylist(regions), members).to_pylist()
    assert t == [{"root_id": "Y.1", "start": 10000, "end": 2649520, "name": "PAR#1"},
                 {"root_id": "Y.1", "start": 59034049, "end": 59363566, "name": "PAR#2"}]
    with pytest.raises(Refused, match="differs between releases"):
        layers.build_par_y(pa.Table.from_pylist(regions + [region("PAR#2", "Y.1", 59034049, 59363567, first=5)]),
                           members)
    with pytest.raises(Refused, match="no PAR regions"):
        layers.build_par_y(pa.Table.from_pylist(regions[:1]), members)


def test_a_derived_mask_reads_the_file_and_takes_labels_that_tile_it(tmp_path):
    fa = tmp_path / "m.fa"
    fa.write_text(">c1\nACNNNNGTAC\n>c2\nNacg\n")
    roots = {"R1": b"ACGTACGTAC", "R2": b"NACG"}  # R2's N is its own: not masked
    def build(labels=None):
        return layers.build_derived_mask(fa, "u", {"c1": "R1", "c2": "R2"}, roots.__getitem__, labels, "L").to_pylist()
    assert [(r["root_id"], r["start"], r["end"], r["name"], r["labels_from"]) for r in build()] == [
        ("R1", 2, 6, None, None)]
    named = build({"c1": [(2, 4, "dj"), (4, 6, "rdna")]})  # one run, two labels end to end
    assert [(r["start"], r["end"], r["name"], r["labels_from"]) for r in named] == [(2, 4, "dj", "L"), (4, 6, "rdna", "L")]
    for bad in ([(2, 5, "dj")], [(2, 4, "dj"), (3, 6, "rdna")], [(2, 6, "a"), (8, 9, "b")], []):
        with pytest.raises(Refused, match="overlaps|don't tile"):
            build({"c1": bad})
    roots["R1"] = b"ACGTACGTAA"  # outside the run, the file has a base the root doesn't
    with pytest.raises(Refused, match="doesn't give the file's sequence"):
        build()
    bed = tmp_path / "l.bed"
    bed.write_text("# a comment\n#chrom\tstart\tend\tname\nc1\t4\t6\trdna\nc1\t2\t4\tdj\n")
    assert layers.read_labels(bed) == {"c1": [(2, 4, "dj"), (4, 6, "rdna")]}


def test_padding_takes_the_latest_placement_and_marks_revised_ones():
    import pyarrow as pa
    def placement(root, start, end, first, last, ori="+", parent="C.1"):
        return {"root_id": root, "parent_id": parent, "parent_start": start, "parent_end": end, "orientation": ori,
                "first_release": first, "last_release": last}
    length = {"C.1": 1000, "A.1": 50, "P.1": 40}
    t = layers.build_padding(pa.Table.from_pylist([
        placement("P.1", 100, 140, 2, 5), placement("P.1", 90, 140, 6, 14),
        placement("A.1", 500, 560, 0, 14, ori="-")]), length).to_pylist()
    assert t == [
        {"root_id": "A.1", "parent_id": "C.1", "parent_start": 500, "parent_end": 560, "orientation": "-",
         "parent_length": 1000, "revised": False},
        {"root_id": "P.1", "parent_id": "C.1", "parent_start": 90, "parent_end": 140, "orientation": "+",
         "parent_length": 1000, "revised": True}]
    with pytest.raises(Refused, match="past the end"):
        layers.build_padding(pa.Table.from_pylist([placement("A.1", 990, 1010, 0, 14)]), length)
    with pytest.raises(Refused, match="not a root"):
        layers.build_padding(pa.Table.from_pylist([placement("A.1", 9, 10, 0, 14, parent="Z.1")]), length)
