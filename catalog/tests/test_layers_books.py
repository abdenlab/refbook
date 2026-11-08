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
    assert layers.Release.of(tmp_path, "x/GCA_000001405.15_GRCh38").number == 0


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
