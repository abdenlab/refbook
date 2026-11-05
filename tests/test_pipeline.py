"""Unit tests for the pure parts of the pipeline scripts, on made-up inputs."""

import gzip
from pathlib import Path

import engine
import lock
import observe
import pytest
import reference_engine
from conftest import step

from refbook import refget

build_roots = step("10_roots")
build_external_roots = step("11_external_roots")
build_layers = step("20_layers")
check_gaps = step("60_check_gaps")
verify_roots = step("61_check_roots")
build_flavors = step("41_flavors")


def write(path: Path, text: str) -> Path:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt") as f:
        f.write(text)
    return path


# build_roots

def test_scan_records_runs_and_positions():
    sc = build_roots.scan(b"acGTNNNRACgt")
    assert sc["bases"] == b"ACGTNNNRACGT"
    assert sc["lower"] == [(0, 2), (10, 12)] and sc["n_lower"] == 4
    assert sc["n_runs"] == [(4, 7)] and sc["n_N"] == 3
    assert sc["iupac"] == [(7, "R")]
    assert (sc["md5"], sc["sha512t24u"]) == refget.digests(b"ACGTNNNRACGT")


def test_scan_edge_cases():
    assert build_roots.scan(b"NNNN")["n_runs"] == [(0, 4)]
    empty = build_roots.scan(b"")
    assert empty["bases"] == b"" and empty["lower"] == empty["n_runs"] == empty["iupac"] == []
    with pytest.raises(refget.NonCanonicalBase):
        build_roots.scan(b"ACGT-ACGT")


def test_parse_report(tmp_path):
    report = write(tmp_path / "r.txt", (
        "# Assembly name:  GRCh38.p1\n"
        "# GenBank assembly accession: GCA_000001405.16\n"
        "# Sequence-Name\tSequence-Role\tGenBank-Accn\n"
        "1\tassembled-molecule\tCM000663.2\n"
        "HSCHR1_CTG1\tfix-patch\tKN196472.1\n"))
    meta, rows = build_roots.parse_report(report)
    assert meta["Assembly name"] == "GRCh38.p1"
    assert meta["GenBank assembly accession"] == "GCA_000001405.16"
    assert [r["GenBank-Accn"] for r in rows] == ["CM000663.2", "KN196472.1"]


def test_read_fasta_takes_the_accession_and_joins_lines(tmp_path):
    fa = write(tmp_path / "x.fa.gz", ">CM000663.2 Homo sapiens chromosome 1\nACGT\nAC\n>EMPTY.1\n>X.1\nGG")
    assert list(build_roots.read_fasta(fa)) == [("CM000663.2", b"ACGTAC"), ("EMPTY.1", b""), ("X.1", b"GG")]


# build_external_roots

def test_parse_hla_header():
    assert build_external_roots.parse_header("HLA:HLA00001 A*01:01:01:01 3503 bp") == (
        "HLA00001", "A*01:01:01:01", 3503)
    with pytest.raises(ValueError):
        build_external_roots.parse_header("HLA00001 A*01:01:01:01 3503 bp")


# build_layers

def test_agp_record_component_and_gap():
    comp = build_layers.agp_record(("10001", "207666", "2", "F", "GL000001.2", "1", "197666", "-"))
    assert comp["start"] == 10000 and comp["end"] == 207666 and comp["part_number"] == 2
    assert (comp["component_id"], comp["component_start"], comp["component_end"],
            comp["orientation"]) == ("GL000001.2", 0, 197666, "-")
    assert comp["gap_length"] is comp["gap_type"] is comp["linkage"] is None
    gap = build_layers.agp_record(("1", "10000", "1", "N", "10000", "telomere", "no", "na"))
    assert (gap["start"], gap["end"], gap["gap_length"], gap["gap_type"]) == (0, 10000, 10000, "telomere")
    assert gap["linkage"] is False and gap["linkage_evidence"] is None
    assert gap["component_id"] is gap["component_start"] is gap["orientation"] is None
    linked = build_layers.agp_record(("1", "100", "3", "U", "100", "scaffold", "yes", "paired-ends;map"))
    assert linked["linkage"] is True and linked["linkage_evidence"] == "paired-ends;map"


def test_release_ranges():
    by_release = {("a", 0): "x", ("a", 1): "x", ("a", 2): "y", ("a", 4): "y", ("b", 1): "x"}
    assert build_layers.release_ranges(by_release) == [
        ("a", "x", 0, 1), ("a", "y", 2, 2), ("a", "y", 4, 4), ("b", "x", 1, 1)]


def test_read_agp_groups_rows_by_object(tmp_path):
    agp = write(tmp_path / "x.agp.gz", "# comment\nA\t1\t5\t1\tF\tC1\t1\t5\t+\n\nA\t6\t9\t2\tN\t4\tscaffold\tyes\tmap\nB\t1\t3\t1\tF\tC2\t1\t3\t+\n")
    objs = build_layers.read_agp(agp)
    assert list(objs) == ["A", "B"] and len(objs["A"]) == 2
    assert objs["A"][1] == ("6", "9", "2", "N", "4", "scaffold", "yes", "map")


# check_gaps

AGP_ROWS = [("1", "4", "1", "F", "C1", "1", "4", "+"),
            ("5", "6", "2", "N", "2", "contig", "no", "na"),
            ("7", "10", "3", "F", "C2", "11", "14", "-")]


def test_gaps_of_and_tiling():
    assert check_gaps.gaps_of(AGP_ROWS) == [(4, 6, "contig")]
    assert check_gaps.check_tiling("X", AGP_ROWS, 10) == []
    assert check_gaps.check_tiling("X", AGP_ROWS, 12) == ["X: AGP ends at 10, root length 12"]
    gapped = [AGP_ROWS[0], ("6", "6", "2", "N", "1", "contig", "no", "na")]
    assert check_gaps.check_tiling("X", gapped, 6) == ["X: row starts at 6, expected 5"]
    short = [("1", "4", "1", "F", "C1", "1", "3", "+")]
    assert check_gaps.check_tiling("X", short, 4) == ["X: component span != object span at 1"]


def test_classify_runs():
    runs = [(0, 5), (10, 20), (30, 34), (40, 50)]
    gaps = [(0, 5, "telomere"),                                   # exact
            (10, 15, "contig"), (15, 20, "scaffold"),             # adjacent gaps
            (42, 50, "contig"),                                   # gap plus component N
            (60, 70, "contig")]                                   # not all N
    not_all_n, classified = check_gaps.classify_runs(runs, gaps)
    assert not_all_n == [(60, 70, "contig")]
    assert [(s, e, k) for s, e, k, _ in classified] == [
        (0, 5, "exact"), (10, 20, "adjacent_gaps"), (30, 34, "no_gap"),
        (40, 50, "gap_plus_component_N")]
    assert classified[1][3] == ["contig", "scaffold"]


# verify_roots

@pytest.mark.parametrize("ena, grc, masked, want", [
    (100, "m", False, ("ok", "match", True)),
    (100, None, False, ("ok", "not in set", True)),
    (100, "other", True, ("ok", "differs", True)),
    (None, "m", False, ("absent", "match", False)),
    (99, "m", False, ("length 99", "match", False)),
    (100, "other", False, ("ok", "differs (UNEXPECTED)", False)),
    (100, "m", True, ("ok", "match (UNEXPECTED: masked by the GRC)", False)),
])
def test_verify_status(ena, grc, masked, want):
    assert verify_roots.status(100, "m", ena, grc, masked) == want


def test_grc_m5_reads_deflines(tmp_path):
    fa = write(tmp_path / "set.fna.gz", (
        ">chr1  AC:CM000663.2  gi:568336023  LN:248956422  rl:Chromosome  M5:6aef897c3d6ff0c78aff06ac189178dd  AS:GRCh38\n"
        "NNNN\n>chrEBV  AC:AJ507799.2  M5:6743bd63b3ff2b5b8985d8933c53290a\nACGT\n>noTags\nA\n"))
    assert verify_roots.grc_m5(fa) == {"CM000663.2": "6aef897c3d6ff0c78aff06ac189178dd",
                                       "AJ507799.2": "6743bd63b3ff2b5b8985d8933c53290a"}


# observe

def test_fasta_records(tmp_path):
    fa = write(tmp_path / "x.fa", ">a one\r\nAC\r\nGT\r\n>empty\n>b\nTT")
    assert list(observe.records(fa)) == [("a one", [b"AC", b"GT"]), ("empty", []), ("b", [b"TT"])]


def test_parse_dict():
    rows = observe.parse_dict(
        "@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:248956422\tM5:6aef897c3d6ff0c78aff06ac189178dd\tUR:file:x\n"
        "@SQ\tSN:chrM\tLN:16569\n")
    assert [(r["position"], r["name"], r["length"], r["md5"]) for r in rows] == [
        (0, "chr1", 248956422, "6aef897c3d6ff0c78aff06ac189178dd"), (1, "chrM", 16569, None)]


# lock

def test_source_url():
    assert lock.source_url(Path("ftp.ncbi.nlm.nih.gov/genomes/all/x.txt")) == \
        "https://ftp.ncbi.nlm.nih.gov/genomes/all/x.txt"
    assert lock.source_url(Path("eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.gb")) == (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        "?db=nuccore&id=AJ507799.2&rettype=gb&retmode=text")


# engine (select and name_of: the frozen Python compiler, the core's oracle)

def test_compare_is_order_free():
    got = [{"flavor": "t", "name": "a", "root_id": "A.1", "length": 3, "md5": "m1", "sha512t24u": "s1"},
           {"flavor": "t", "name": "b", "root_id": "B.1", "length": 4, "md5": "m2", "sha512t24u": "s2"}]
    obs = [{"name": "b", "position": 0, "length": 4, "md5": "m2", "sha512t24u": None, "defline_ac": None},
           {"name": "a", "position": 1, "length": 3, "md5": "m1", "sha512t24u": "s1", "defline_ac": "A.1"}]
    assert engine.compare(got, obs) == []
    assert [r["name"] for r in engine.in_observed_order(got, obs)] == ["b", "a"]
    assert engine.compare(got, [obs[0]]) != []                               # a name missing
    assert engine.compare(got, [obs[0], {**obs[1], "md5": "x"}]) != []       # a digest differs
    assert engine.compare(got, [obs[0], {**obs[1], "defline_ac": "Z.1"}]) != []  # the wrong root


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
    sel = reference_engine.select({"flavor": "t", "select": entries}, MEMBERS, ROOTS, EXTERNAL, PARENTS)
    return [s["root_id"] for s in sel]


def test_select_entry_kinds():
    assert selected([{"assembly": "GCA_1.1", "roles": ["assembled-molecule", "unplaced-scaffold"]},
                     {"roots": ["EBV.1"]},
                     {"collection": "IMGT/HLA 1", "groups": ["B"]}]) == ["C1.1", "P1.1", "EBV.1", "IMGTHLA:1:H2"]


def test_select_narrowings():
    roles = ["assembled-molecule", "alt-scaffold", "fix-patch"]
    assert selected([{"assembly": "GCA_1.1", "roles": roles, "placed_on": ["chromosome"]}]) == [
        "C1.1", "A1.1", "F1.1"]
    assert selected([{"assembly": "GCA_1.1", "roles": ["fix-patch"], "accessions": ["F2.1"]}]) == ["F2.1"]


def test_select_errors():
    with pytest.raises(SystemExit):
        selected([{"assembly": "GCA_1.1", "roles": ["assembled-molecule"]},
                  {"assembly": "GCA_1.1", "roles": ["assembled-molecule"]}])
    with pytest.raises(SystemExit):
        selected([{"assembly": "GCA_9.9", "roles": ["assembled-molecule"]}])
    with pytest.raises(SystemExit):
        selected([{"roots": ["NOPE.1"]}])
    with pytest.raises(SystemExit):
        selected([{"collection": "IMGT/HLA 1", "groups": ["Z"]}])


def test_name_of_precedence():
    rename = {"namespace": "ucsc", "by_role": {"assembled-molecule": "sequence"},
              "map": {"U1.1": "mapped"}, "template": {"GCA_1.1": "t_{accession_v}"}}
    s = {"root_id": "C1.1", "assembly": "GCA_1.1", "member": MEMBERS[0]}
    assert reference_engine.name_of({**s, "root_id": "U1.1"}, rename) == "mapped"       # map first
    assert reference_engine.name_of(s, rename) == "t_C1v1"                              # then template
    del rename["template"]
    assert reference_engine.name_of(s, rename) == "1"                                   # then by_role
    assert reference_engine.name_of({"root_id": "P1.1", "assembly": "GCA_1.1", "member": MEMBERS[2]},
                               rename) == "chrUn_P1v1"                             # then namespace
    ext = {"root_id": "IMGTHLA:1:H1", "assembly": "IMGT/HLA 1", "member": None, "external": EXTERNAL[0]}
    assert reference_engine.name_of(ext, {"namespace": "ucsc", "template": {"IMGT/HLA 1": "HLA-{name}"}}) == "HLA-A*01"
    with pytest.raises(SystemExit):
        reference_engine.name_of({"root_id": "C1.1", "assembly": "GCA_1.1", "member": {**MEMBERS[0], "refseq_accession": None}},
                            {"namespace": "refseq"})


# build_flavors


def test_flavor_facets():
    latest = {"F1.1"}
    assert build_flavors.kind("IMGTHLA:1:H1", None, latest) == "HLA allele"
    assert build_flavors.kind("C1.1", {**MEMBERS[0], "assembly_accession": "GCA_000001405.15"}, latest) == "assembled-molecule"
    assert build_flavors.kind("F2.1", {**MEMBERS[5], "assembly_accession": "GCA_000001405.28"}, latest) == "superseded fix-patch"
    assert build_flavors.kind("D1.1", {**MEMBERS[2], "assembly_accession": "GCA_000786075.2",
                                       "assembly_name": "hs38d1"}, latest) == "hs38d1 decoy"
    assert build_flavors.naming({"namespace": "genbank", "by_role": {"assembled-molecule": "ucsc"},
                                 "map": {"E.1": "chrEBV"}}) == "genbank; assembled-molecule: ucsc; E.1: chrEBV"
    recipe = {"select": [{"assembly": "GCA_1.1", "roles": ["fix-patch"], "placed_on": ["chromosome"]}]}
    assert build_flavors.excluded(recipe, MEMBERS, {"F1.1"}) == ["1 fix-patch (not placed on chromosome)"]


# layout

import layout


def test_grch38_releases():
    assert layout.RELEASES[0] == (0, "GCA_000001405.15", "GRCh38")
    assert layout.LATEST == (14, "GCA_000001405.29", "GRCh38.p14")
    raw = Path("/r")
    assert layout.release_dir(raw, 3).name == "GCA_000001405.18_GRCh38.p3"
    assert [layout.release_number(d) for d in layout.release_dirs(raw)] == list(range(15))
    assert layout.assembly_dirs(raw)[-1].name == "GCA_000786075.2_hs38d1"
    with pytest.raises(ValueError):
        layout.release_number(Path("/r/GCA_000786075.2_hs38d1"))


def test_verify_status_without_ena():
    assert verify_roots.status(100, "m", verify_roots.SKIPPED, "m", False) == ("not checked", "match", True)
    assert verify_roots.status(100, "m", verify_roots.SKIPPED, "x", False)[2] is False


# 70_export: the gate on the checks

def test_export_gate(tmp_path):
    export = step("70_export")
    build = tmp_path / "build"
    for d, name in (("10_roots", "roots.parquet"), ("20_layers", "layer_hardmask_grc.parquet")):
        (build / d).mkdir(parents=True)
        (build / d / name).write_bytes(b"data " + name.encode())
    assert export.gate(build)[1] == [f"{c}: has not run" for c in export.CHECKS]

    def record(check, passed=True, ena=None):
        out = build / f"6{export.CHECKS.index(check)}_{check}"
        out.mkdir(exist_ok=True)
        layout.record_check(build, out, check, passed, ["roots.parquet"], {"ena": ena} if ena else {})
    for c in export.CHECKS:
        record(c)
    assert export.gate(build)[1] == []
    record("check_roots", ena="skipped")
    assert export.gate(build)[1] == ["check_roots: ran without ENA (--skip-ena); rerun it, or export --development"]
    assert export.gate(build, development=True)[1] == []
    record("check_roots")
    record("check_gaps", passed=False)
    assert export.gate(build)[1] == ["check_gaps: failed"]
    record("check_gaps")
    (build / "10_roots" / "roots.parquet").write_bytes(b"rebuilt")
    assert all("roots.parquet has changed" in p for p in export.gate(build)[1])


def test_export_gate_on_locks(tmp_path):
    export = step("70_export")
    build = tmp_path / "build"
    (build / "10_roots").mkdir(parents=True)
    (build / "10_roots" / "10_roots.inputs.json").write_text('{"inputs.lock": "not the current lock"}')
    assert "10_roots: built from another inputs.lock; rerun it" in export.gate(build)[1]
    layout.record_inputs(build / "10_roots", "10_roots", layout.inputs_lock())
    assert not any("built from another" in p for p in export.gate(build)[1])


def test_lock_publisher_checks(tmp_path):
    import hashlib
    raw = tmp_path / "raw"
    (raw / "h/d").mkdir(parents=True)
    (raw / "h/d/a.txt").write_text("a")
    (raw / "h/d/b.txt").write_text("b")
    md5 = {n: hashlib.md5(n.encode()).hexdigest() for n in "ab"}
    (raw / "h/d/md5checksums.txt").write_text(f"{md5['a']}  ./a.txt\n{'0' * 32}  ./b.txt\n{'1' * 32}  ./absent.txt\n")
    files = {}
    for p in sorted(q for q in raw.rglob("*") if q.is_file()):
        sha, m = lock.digests(p)
        files[p.relative_to(raw).as_posix()] = {"md5": m, "sha256": sha}
    checked, errors = lock.publisher_checks(raw, files)
    assert checked == 2 and errors == ["h/d/b.txt: does not match h/d/md5checksums.txt"]
    known = {("h/d/b.txt", "0" * 32, md5["b"])}
    assert lock.publisher_checks(raw, files, known) == (2, [])   # a documented mismatch
    (tmp_path / "checksum_exceptions.tsv").write_text(f"path\tlisted_md5\tserved_md5\tnote\nh/d/b.txt\t{'0' * 32}\t{md5['b']}\twhy\n")
    assert lock.known_mismatches(tmp_path / "checksum_exceptions.tsv") == known


def test_lock_round_trip(tmp_path):
    entries = {"h/x": {"path": "h/x", "bytes": 3, "sha256": "s", "last_modified": "t", "url": "https://h/x"}}
    lock.write_lock(tmp_path / "t.lock", entries)
    assert lock.read_lock(tmp_path / "t.lock") == {"h/x": {k: str(v) for k, v in entries["h/x"].items()}}
    assert layout.read_lock(tmp_path / "t.lock") == lock.read_lock(tmp_path / "t.lock")
