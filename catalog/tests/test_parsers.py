"""Unit tests carried over from the first pipeline: the parsers and operations the new tests don't cover, and the
frozen reference compiler's selection and naming (reference_engine.py), on made-up inputs."""

import gzip
from pathlib import Path

import pytest
import reference_engine
from refbook_pipeline import checks, engine, layers, observe

from refbook import refget


def write(path: Path, text: str) -> Path:
    with (gzip.open(path, "wt") if path.suffix == ".gz" else open(path, "w")) as f:
        f.write(text)
    return path


def test_scan_records_runs_and_positions():
    sc = refget.scan(b"acGTNNNRACgt")
    assert sc["bases"] == b"ACGTNNNRACGT"
    assert sc["lower"] == [(0, 2), (10, 12)] and sc["n_runs"] == [(4, 7)] and sc["iupac"] == [(7, "R")]
    assert (sc["md5"], sc["sha512t24u"]) == refget.digests(b"ACGTNNNRACGT")


def test_scan_edge_cases():
    assert refget.scan(b"NNNN")["n_runs"] == [(0, 4)]
    empty = refget.scan(b"")
    assert empty["bases"] == b"" and empty["lower"] == empty["n_runs"] == empty["iupac"] == []
    with pytest.raises(refget.NonCanonicalBase):
        refget.scan(b"ACGT-ACGT")


def test_read_agp_groups_rows_by_object(tmp_path):
    agp = write(tmp_path / "x.agp.gz", "# comment\nA\t1\t5\t1\tF\tC1\t1\t5\t+\n\n"
                                       "A\t6\t9\t2\tN\t4\tscaffold\tyes\tmap\nB\t1\t3\t1\tF\tC2\t1\t3\t+\n")
    objs = layers.read_agp(agp)
    assert list(objs) == ["A", "B"] and len(objs["A"]) == 2
    assert objs["A"][1] == ("6", "9", "2", "N", "4", "scaffold", "yes", "map")


def test_grc_m5_reads_deflines(tmp_path):
    fa = write(tmp_path / "set.fna.gz", (
        ">chr1  AC:CM000663.2  gi:568336023  LN:248956422  rl:Chromosome  M5:6aef897c3d6ff0c78aff06ac189178dd  AS:GRCh38\n"
        "NNNN\n>chrEBV  AC:AJ507799.2  M5:6743bd63b3ff2b5b8985d8933c53290a\nACGT\n>noTags\nA\n"))
    assert checks.grc_m5(fa) == {"CM000663.2": "6aef897c3d6ff0c78aff06ac189178dd",
                                 "AJ507799.2": "6743bd63b3ff2b5b8985d8933c53290a"}


def test_fasta_records(tmp_path):
    fa = write(tmp_path / "x.fa", ">a one\r\nAC\r\nGT\r\n>empty\n>b\nTT")
    assert list(observe.records(fa)) == [("a one", [b"AC", b"GT"]), ("empty", []), ("b", [b"TT"])]


def test_parse_dict():
    rows = observe.parse_dict("@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:248956422\tM5:6aef897c3d6ff0c78aff06ac189178dd\tUR:file:x\n"
                              "@SQ\tSN:chrM\tLN:16569\n")
    assert [(r["position"], r["name"], r["length"], r["md5"]) for r in rows] == [
        (0, "chr1", 248956422, "6aef897c3d6ff0c78aff06ac189178dd"), (1, "chrM", 16569, None)]


def test_an_observation_keeps_its_files_provenance(tmp_path):
    fa = write(tmp_path / "x.fa", ">chr1 AC:CM1.1 M5:abc\nACgtN\n")
    t = observe.observe(fa)
    assert t.to_pylist()[0] | {"md5": None, "sha512t24u": None} == {
        "position": 0, "name": "chr1", "length": 5, "md5": None, "sha512t24u": None, "n_N": 1, "n_lower": 2,
        "line_width": 5, "defline_ac": "CM1.1", "defline_m5": "abc", "defline": "chr1 AC:CM1.1 M5:abc"}
    entry = {"path": "h/x.fa", "url": "https://h/x.fa", "bytes": 1, "sha256": "s", "last_modified": "t"}
    out = tmp_path / "o.parquet"
    import pyarrow.parquet as pq
    pq.write_table(t.replace_schema_metadata(observe.provenance(entry)), out)
    assert observe.read_provenance(out) == {**{k: str(v) for k, v in entry.items()}, "evidence": "content"}


def test_apply_operations():
    bases = b"ACGTRACGTY"
    assert engine.apply_operations(bases, [], []) == bases
    assert engine.apply_operations(bases, [(0, 2), (1, 3)], []) == b"NNNTRACGTY"
    assert engine.apply_operations(bases, [(8, 10)], [4, 9]) == b"ACGTNACGNN"


def member(acc, role, molecule=None, unit="Primary Assembly", assembly="GCA_1.1", **names):
    return {"assembly_accession": assembly, "genbank_accession": acc, "role": role,
            "assigned_molecule": molecule, "assembly_unit": unit, **names}


MEMBERS = [member("C1.1", "assembled-molecule", "1", ucsc_name="chr1", sequence_name="1"),
           member("U1.1", "unlocalized-scaffold", "1", ucsc_name="chr1_U1v1_random"),
           member("P1.1", "unplaced-scaffold", ucsc_name="chrUn_P1v1"),
           member("A1.1", "alt-scaffold", "1", unit="ALT_REF_LOCI_1", ucsc_name="chr1_A1v1_alt"),
           member("F1.1", "fix-patch", "1", unit="PATCHES", ucsc_name="chr1_F1v1_fix"),
           member("F2.1", "fix-patch", "1", unit="PATCHES", ucsc_name="chr1_F2v1_fix")]
EXTERNAL = [{"root_id": "IMGTHLA:1:H1", "collection": "IMGT/HLA 1", "group": "A", "name": "A*01"},
            {"root_id": "IMGTHLA:1:H2", "collection": "IMGT/HLA 1", "group": "B", "name": "B*07"}]
ROOTS = {"EBV.1": {}}
PARENTS = {"A1.1": {"chromosome"}, "F1.1": {"chromosome"}, "F2.1": {"scaffold"}}


def selected(entries):
    sel = reference_engine.select({"target": "t", "select": entries}, MEMBERS, ROOTS, EXTERNAL, PARENTS)
    return [s["root_id"] for s in sel]


def test_select_entry_kinds():
    assert selected([{"assembly": "GCA_1.1", "roles": ["assembled-molecule", "unplaced-scaffold"]},
                     {"roots": ["EBV.1"]},
                     {"collection": "IMGT/HLA 1", "groups": ["B"]}]) == ["C1.1", "P1.1", "EBV.1", "IMGTHLA:1:H2"]


def test_select_narrowings():
    roles = ["assembled-molecule", "alt-scaffold", "fix-patch"]
    assert selected([{"assembly": "GCA_1.1", "roles": roles, "placed_on": ["chromosome"]}]) == ["C1.1", "A1.1", "F1.1"]
    assert selected([{"assembly": "GCA_1.1", "roles": ["fix-patch"], "accessions": ["F2.1"]}]) == ["F2.1"]


@pytest.mark.parametrize("entries", [
    [{"assembly": "GCA_1.1", "roles": ["assembled-molecule"]}, {"assembly": "GCA_1.1", "roles": ["assembled-molecule"]}],
    [{"assembly": "GCA_9.9", "roles": ["assembled-molecule"]}],
    [{"roots": ["NOPE.1"]}],
    [{"collection": "IMGT/HLA 1", "groups": ["Z"]}],
])
def test_select_errors(entries):
    with pytest.raises(SystemExit):
        selected(entries)


def test_name_of_precedence():
    rename = {"namespace": "ucsc", "by_role": {"assembled-molecule": "grc"},
              "map": {"U1.1": "mapped"}, "template": {"GCA_1.1": "t_{accession_v}"}}
    s = {"root_id": "C1.1", "assembly": "GCA_1.1", "member": MEMBERS[0]}
    assert reference_engine.name_of({**s, "root_id": "U1.1"}, rename) == "mapped"  # map first
    assert reference_engine.name_of(s, rename) == "t_C1v1"                         # then template
    del rename["template"]
    assert reference_engine.name_of(s, rename) == "1"                              # then by_role
    assert reference_engine.name_of({"root_id": "P1.1", "assembly": "GCA_1.1", "member": MEMBERS[2]},
                                    rename) == "chrUn_P1v1"                        # then namespace
    ext = {"root_id": "IMGTHLA:1:H1", "assembly": "IMGT/HLA 1", "member": None, "external": EXTERNAL[0]}
    assert reference_engine.name_of(ext, {"namespace": "ucsc", "template": {"IMGT/HLA 1": "HLA-{name}"}}) == "HLA-A*01"
    with pytest.raises(SystemExit):
        reference_engine.name_of({"root_id": "C1.1", "assembly": "GCA_1.1",
                                  "member": {**MEMBERS[0], "refseq_accession": None}}, {"namespace": "refseq"})
