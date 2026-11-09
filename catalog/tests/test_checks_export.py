"""The checks and the export's gate, on small inputs made here."""

import json

import pytest
from refbook_pipeline import Refused, checks, export


def part(n, start, end, comp=True, gap_type=None):
    if comp:
        return {"root_id": "R.1", "part_number": n, "start": start, "end": end, "component_id": "C.1",
                "component_start": 0, "component_end": end - start, "gap_type": None}
    return {"root_id": "R.1", "part_number": n, "start": start, "end": end, "component_id": None,
            "component_start": None, "component_end": None, "gap_type": gap_type}


def test_runs_are_classified_against_the_gaps():
    runs = [(10, 20), (30, 40), (50, 60), (70, 90)]
    gaps = [(10, 20, "contig"), (30, 35, "contig"), (35, 40, "scaffold"), (70, 80, "contig"), (95, 99, "contig")]
    not_all_n, classified = checks.classify_runs(runs, gaps)
    assert not_all_n == [(95, 99, "contig")]  # a gap with bases in it
    assert [c[2] for c in classified] == ["exact", "adjacent_gaps", "no_gap", "gap_plus_component_N"]


def test_tiling_wants_parts_in_order_and_to_the_end():
    ok = [part(1, 0, 10), part(2, 10, 15, comp=False, gap_type="contig"), part(3, 15, 30)]
    assert checks.check_tiling("R.1", ok, 30) == []
    assert checks.check_tiling("R.1", ok, 31) == ["R.1: AGP ends at 30, root length 31"]
    swapped = [ok[0], {**ok[2], "part_number": 2}, {**ok[1], "part_number": 3}]
    assert any("starts at" in e for e in checks.check_tiling("R.1", swapped, 30))


def test_check_gaps_passes_explained_runs_and_catches_overlaps():
    agp = [part(1, 0, 10), part(2, 10, 15, comp=False, gap_type="contig"), part(3, 15, 30)]
    members = [{"genbank_accession": "R.1", "assembly_name": "T"}]
    passed, details, report = checks.check_gaps(agp, [{"root_id": "R.1", "start": 10, "end": 15}], {"R.1": 30},
                                                members, {})
    assert passed and details["runs"] == {"exact": 1} and report == []
    passed, details, _ = checks.check_gaps(agp, [{"root_id": "R.1", "start": 10, "end": 15},
                                                 {"root_id": "R.1", "start": 12, "end": 14}], {"R.1": 30}, members, {})
    assert not passed and "overlap" in details["errors"][0]
    passed, details, _ = checks.check_gaps(agp, [], {"R.1": 30}, members, {})
    assert not passed and details["runs"] == {"gap_not_all_N": 1}  # the gap has bases


def test_a_member_of_a_release_without_structure_needs_no_agp():
    members = [{"genbank_accession": "V1.1", "assembly_name": "T-v1.0"}]
    runs = [{"root_id": "V1.1", "start": 2, "end": 4}]
    passed, details, _ = checks.check_gaps([], runs, {"V1.1": 10}, members, {})
    assert not passed and details["errors"] == ["V1.1: no AGP"]
    passed, details, report = checks.check_gaps([], runs, {"V1.1": 10}, members, {}, {"V1.1"})
    assert passed and details["no_agp_published"] == ["V1.1"] and report  # its run of N, reported unexplained


@pytest.mark.parametrize(("ena", "grc", "masked", "want"), [
    ("not checked", "m", False, ("not checked", "match", True)),
    (9, "m", False, ("ok", "match", True)),
    (None, "m", False, ("absent", "match", False)),
    (8, "m", False, ("length 8", "match", False)),
    ("not checked", "x", True, ("not checked", "differs", True)),            # the GRC masked it: must differ
    ("not checked", "x", False, ("not checked", "differs (UNEXPECTED)", False)),
    ("not checked", "m", True, ("not checked", "match (UNEXPECTED: masked by the GRC)", False)),
    ("not checked", None, False, ("not checked", "not in set", True)),
])
def test_root_status(ena, grc, masked, want):
    assert checks.root_status(9, "m", ena, grc, masked) == want


def test_a_root_absent_from_ena_passes_only_as_documented(tmp_path):
    assert checks.root_status(9, "m", None, None, False, "m") == ("absent (documented)", "not in set", True)
    assert checks.root_status(9, "m", None, None, False, "other")[2] is False      # listed with another MD5
    assert checks.root_status(9, "m", 9, None, False, "m")[0].startswith("ok (UNEXPECTED")  # ENA holds it again
    (tmp_path / "x.tsv").write_text("# a comment\nroot_id\tmd5\tchecked\twhy\nK1.1\tm\t2026-11-08\tnot in ENA\n")
    exc = checks.read_ena_exceptions(tmp_path / "x.tsv")
    assert exc == {"K1.1": "m"} and checks.read_ena_exceptions(tmp_path / "none.tsv") == {}
    roots = [{"root_id": "K1.1", "length": 9, "md5": "m"}]
    assert checks.check_roots(roots, set(), {}, "", {"m": None}, exc)[0]
    assert not checks.check_roots(roots, set(), {}, "", {"m": None}, {})[0]
    passed, details, _ = checks.check_roots([], set(), {}, "", {}, exc)  # listed, no longer a root
    assert not passed and details["failed"] == ["K1.1"]


def build(tmp_path, passed=True, ena="checked"):
    catalog = tmp_path / "build" / "catalog"
    (catalog / "roots").mkdir(parents=True)
    (catalog / "roots" / "roots.parquet").write_bytes(b"roots")
    (catalog / "roots" / "inputs.json").write_text("{}")
    out = tmp_path / "checks"
    out.mkdir(exist_ok=True)
    checks.record(out, "check_roots", passed, {"roots.parquet": catalog / "roots" / "roots.parquet"}, {"ena": ena})
    return catalog, {"check_roots": out / "check_roots.json"}


def test_the_gate_passes_a_checked_unchanged_build(tmp_path):
    catalog, c = build(tmp_path)
    assert export.gate(catalog, c, [], development=False)[1] == []


def test_the_gate_refuses(tmp_path):
    catalog, c = build(tmp_path, passed=False, ena="skipped")
    problems = export.gate(catalog, {**c, "check_gaps": tmp_path / "none.json"}, [], development=False)[1]
    assert "check_gaps: has not run" in problems and "check_roots: failed" in problems
    assert any("without ENA" in p for p in problems)
    assert not any("without ENA" in p for p in export.gate(catalog, c, [], development=True)[1])
    (catalog / "roots" / "roots.parquet").write_bytes(b"changed")
    assert any("changed since the check ran" in p for p in export.gate(catalog, c, [], development=True)[1])
    lock = tmp_path / "S.lock"
    lock.write_text("path\n")
    (catalog / "roots" / "inputs.json").write_text(json.dumps({"S.lock": "an older lock's hash"}))
    assert any("built from another S.lock" in p for p in export.gate(catalog, c, [lock], development=True)[1])


def test_a_release_is_never_overwritten(tmp_path):
    (tmp_path / "out").mkdir()
    with pytest.raises(Refused, match="never overwritten"):
        export.export(tmp_path, tmp_path / "out", "0", {}, [], [], "", True)
