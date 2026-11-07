"""Editions, aliases, external roots and the engine's comparison, on small inputs made here."""

import pytest
from refbook_pipeline import Refused, aliases, editions, engine, external

RELEASES = {"GRCh38", "GRCh38.p14"}


def member(acc, role="assembled-molecule", name="GRCh38.p14", **kw):
    return {"genbank_accession": acc, "role": role, "assembly_name": name, "assembly_accession": "GCA_1.1",
            "release": 14, "refseq_accession": None, "ucsc_name": None, "sequence_name": acc, **kw}


def test_kinds_for_the_contents_facet():
    loose, latest = {"AJ507799.2": "EBV"}, {"KN1.1"}
    assert editions.kind("AJ507799.2", None, RELEASES, latest, loose) == "EBV"  # a loose root: its source's name
    assert editions.kind("IMGTHLA:3.18.0:HLA00001", None, RELEASES, latest, loose) == "HLA allele"
    assert editions.kind("X.1", None, RELEASES, latest, loose) == "other"
    assert editions.kind("JTFH1.1", member("JTFH1.1", "unplaced-scaffold", "hs38d1"), RELEASES, latest, loose) == (
        "hs38d1 decoy")  # a member of an add-on, not of the book's releases
    assert editions.kind("KQ1.1", member("KQ1.1", "fix-patch"), RELEASES, latest, loose) == "superseded fix-patch"
    assert editions.kind("KN1.1", member("KN1.1", "fix-patch"), RELEASES, latest, loose) == "fix-patch"


def test_the_naming_facet_lists_each_exception():
    assert editions.naming({"namespace": "ucsc", "by_role": {"alt-scaffold": "genbank"},
                            "map": {"AJ507799.2": "chrEBV"}}) == "ucsc; alt-scaffold: genbank; AJ507799.2: chrEBV"


def test_excluded_counts_what_an_entry_covers_but_leaves_out():
    recipe = {"select": [{"assembly": "GCA_1.1", "roles": ["fix-patch"], "placed_on": ["chromosome"]}]}
    ms = [member("A.1", "fix-patch"), member("B.1", "fix-patch"), member("C.1", "assembled-molecule")]
    assert editions.excluded(recipe, ms, {"A.1"}) == ["1 fix-patch (not placed on chromosome)"]


def test_the_sequence_store_keeps_every_way_and_picks_the_fewest_operations():
    roots = {"Y.1": {"sha512t24u": "SQ.y", "md5": "m", "length": 9}}
    manifests = [{"edition": "a", "root_id": "Y.1", "operations": ["hardmask_grc", "iupac_to_n"], "sha512t24u": "SQ.m",
                  "md5": "mm", "length": 9},
                 {"edition": "b", "root_id": "Y.1", "operations": ["hardmask_grc"], "sha512t24u": "SQ.m",
                  "md5": "mm", "length": 9}]
    seqs, ders = editions.sequence_store(manifests, roots)
    by = {s["sha512t24u"]: s for s in seqs}
    assert by["SQ.m"]["operations"] == ["hardmask_grc"] and by["SQ.m"]["n_derivations"] == 2
    assert by["SQ.y"]["operations"] == [] and [d["editions"] for d in ders if d["sha512t24u"] == "SQ.m"] == [
        ["b"], ["a"]]


def test_book_aliases_scope_names_to_the_book(tmp_path):
    (tmp_path / "chromAlias.txt").write_text("# genbank\tensembl\nCM1.1\t1\nJ1.2\tMT\n")
    ms = [member("CM1.1", ucsc_name="chr1", refseq_accession="NC_1.1"), member("J1.2", ucsc_name="chrM"),
          member("D1.1", "unplaced-scaffold", "hs38d1")]
    declared = [{"namespace": "ensembl", "chromalias": {"source": "U", "file": "c"}, "label": "chromAlias"},
                {"namespace": "ensembl", "targets": ["E"], "roots": "fill", "label": "Ensembl"},
                {"namespace": "ucsc", "targets": ["G"], "roots": "outside_releases", "label": "GRC sets"}]
    reproduced = {"E": [{"root_id": "CM1.1", "name": "1"}, {"root_id": "J1.2", "name": "M"},
                        {"root_id": "D1.1", "name": "D1.1"}],
                  "G": [{"root_id": "CM1.1", "name": "chr1"}, {"root_id": "D1.1", "name": "chrUn_D1v1_decoy"},
                        {"root_id": "AJ1.2", "name": "chrEBV"}]}
    got, notes = aliases.book_aliases("b", ms, RELEASES, declared, reproduced, {"U/c": tmp_path / "chromAlias.txt"})
    assert (None, "CM1.1", "genbank", "CM1.1", "GCA_1.1 assembly report") in got  # accessions: no book
    assert ("b", "CM1.1", "ucsc", "chr1", "GCA_1.1 assembly report") in got      # names: the book's
    assert ("b", "CM1.1", "grc", "CM1.1", "GCA_1.1 assembly report") in got
    assert not any(r[1] == "D1.1" and r[2] == "grc" for r in got)                # an add-on has no GRC name
    assert ("b", "D1.1", "ensembl", "D1.1", "Ensembl") in got                    # filled: no chromAlias name
    assert not any(r[1] == "J1.2" and r[3] == "M" for r in got)                  # chromAlias wins, and it differs:
    assert notes and "1 roots" in notes[0]
    assert {r[3] for r in got if r[2] == "ucsc" and r[4] == "GRC sets"} == {"chrUn_D1v1_decoy", "chrEBV"}
    with pytest.raises(Refused, match="doesn't reproduce"):
        aliases.book_aliases("b", ms, RELEASES, declared[1:2], {}, {})


def test_sequence_aliases_give_a_derivative_only_its_own_names():
    al = {(None, "Y.1", "genbank", "CM1.2", "r"), ("b", "Y.1", "ucsc", "chrY", "r"), ("b", "Y.1", "grc", "Y", "r")}
    seqs = [{"sha512t24u": "SQ.y", "root_id": "Y.1", "operations": []},
            {"sha512t24u": "SQ.m", "root_id": "Y.1", "operations": ["hardmask_grc"]}]
    got = aliases.sequence_aliases(al, [{"sha512t24u": "SQ.m", "name": "chrY"}], seqs)
    assert {a for a in got if a[0] == "SQ.y"} == {("SQ.y", "insdc", "CM1.2"), ("SQ.y", "ucsc", "chrY"),
                                                    ("SQ.y", "grc", "Y")}
    assert {a for a in got if a[0] == "SQ.m"} == {("SQ.m", "ucsc", "chrY")}  # never the accession of other bases


def test_imgt_alleles_and_a_repeated_accession(tmp_path):
    (tmp_path / "A_gen.fasta").write_text(">HLA:HLA00001 A*01:01:01:01 8 bp\nACGTacgt\n")
    (tmp_path / "B_gen.fasta").write_text(">HLA:HLA00001 B*01 4 bp\nACGT\n")
    rows = external.imgt_hla("IMGT/HLA 1", "IMGTHLA:1", [(tmp_path / "A_gen.fasta", "u/A"), (tmp_path / "B_gen.fasta", "u/B")])
    assert [(r["root_id"], r["group"], r["rank"], r["n_lower"]) for r in rows] == [
        ("IMGTHLA:1:HLA00001", "A", 0, 4), ("IMGTHLA:1:HLA00001:B", "B", 1, 0)]
    assert external.table(rows).num_rows == 2
    (tmp_path / "C_gen.fasta").write_text(">HLA:HLA00002 C*01 5 bp\nACGT\n")
    with pytest.raises(Refused, match="says 5 bp"):
        external.imgt_hla("c", "p", [(tmp_path / "C_gen.fasta", "u")])
    with pytest.raises(Refused, match="unexpected IMGT/HLA header"):
        external.parse_header("HLA00001 A*01 3 nt")


def test_reproduction_is_order_free_and_checks_every_digest_it_has():
    got = [{"name": "a", "root_id": "A.1", "length": 3, "md5": "m1", "sha512t24u": "s1"},
           {"name": "b", "root_id": "B.1", "length": 4, "md5": "m2", "sha512t24u": "s2"}]
    obs = [{"name": "b", "length": 4, "md5": "m2", "sha512t24u": None, "defline_ac": None, "position": 0},
           {"name": "a", "length": 3, "md5": "m1", "sha512t24u": "s1", "defline_ac": "A.1", "position": 1}]
    assert engine.compare(got, obs) == []  # a .dict lacks SQ.: skipped
    assert [r["name"] for r in engine.in_observed_order([{**g, "target": "t"} for g in got], obs)] == ["b", "a"]
    obs[1]["defline_ac"] = "Z.1"
    assert engine.compare(got, obs) == ["a: root A.1 != AC:Z.1"]
    assert "names only in the recipe" in engine.compare(got, obs[:1])[0]
