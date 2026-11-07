"""Members and roots, on small files made here: reports parsed into members, lengths that must agree, and every way
the roots refuse (a sequence expected nowhere, another length, a non-canonical base, one missing, the same root with
other bases) or accept (the same root twice, as GRCh37 and GRCh38 both carry rCRS)."""

import gzip

import pyarrow.parquet as pq
import pytest
from refbook_pipeline import Refused, members, roots

from refbook import refget

REPORT = """\
# Assembly name:  Test.p2
# GenBank assembly accession: GCA_1.3
#
# Sequence-Name\tSequence-Role\tAssigned-Molecule\tAssigned-Molecule-Location/Type\tGenBank-Accn\tRelationship\tRefSeq-Accn\tAssembly-Unit\tSequence-Length\tUCSC-style-name
1\tassembled-molecule\t1\tChromosome\tCM1.1\t=\tNC_1.1\tPrimary Assembly\t12\tchr1
MT\tassembled-molecule\tMT\tMitochondrion\tJ1.2\t=\tna\tnon-nuclear\t8\tna
"""


def test_a_report_becomes_members_of_its_book(tmp_path):
    (tmp_path / "r.txt").write_text(REPORT)
    t = members.members("test", [tmp_path / "r.txt"])
    assert t.column_names == members.COLUMNS
    rows = t.to_pylist()
    assert rows[0] == {"book": "test", "assembly_accession": "GCA_1.3", "assembly_name": "Test.p2", "release": 2,
                       "sequence_name": "1", "role": "assembled-molecule", "assigned_molecule": "1",
                       "location_type": "Chromosome", "genbank_accession": "CM1.1", "relationship": "=",
                       "refseq_accession": "NC_1.1", "assembly_unit": "Primary Assembly", "length": 12,
                       "ucsc_name": "chr1"}
    assert rows[1]["refseq_accession"] is None and rows[1]["ucsc_name"] is None  # "na" is no value
    assert members.release_of("hs38d1") == members.release_of("GRCh38") == 0
    assert members.lengths(t) == {"CM1.1": 12, "J1.2": 8}


def test_reports_that_disagree_on_a_length_refuse(tmp_path):
    (tmp_path / "a.txt").write_text(REPORT)
    (tmp_path / "b.txt").write_text(REPORT.replace("non-nuclear\t8", "non-nuclear\t9"))
    with pytest.raises(Refused, match="J1.2: assembly reports disagree"):
        members.lengths(members.members("test", [tmp_path / "a.txt", tmp_path / "b.txt"]))


def fasta(path, records, gz=False):
    text = "".join(f">{name} some description\n{seq[:5]}\n{seq[5:]}\n" for name, seq in records)
    with gzip.open(path, "wt") if gz else open(path, "w") as f:
        f.write(text)
    return path


def build(tmp_path, expected, *files):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return roots.build(expected, [(f, f"https://x/{f.name}") for f in files], out, block_size=4), out


def test_roots_and_their_layers(tmp_path):
    a = fasta(tmp_path / "a.fa.gz", [("CM1.1", "ACGTnnNNacRT"), ("J1.2", "GATTACAG")], gz=True)
    result, out = build(tmp_path, {"CM1.1": 12, "J1.2": 8}, a)
    assert result == {"roots": 2, "read_twice": []}
    r = {x["root_id"]: x for x in pq.read_table(out / "roots.parquet").to_pylist()}
    assert r["CM1.1"]["md5"] == refget.digests(b"ACGTNNNNACRT")[0] and r["CM1.1"]["source"] == "https://x/a.fa.gz"
    assert (r["CM1.1"]["n_N"], r["CM1.1"]["n_iupac"], r["CM1.1"]["n_lower"]) == (4, 1, 4)
    blocks = pq.read_table(out / "root_blocks.parquet").to_pylist()
    assert [(b["start"], b["bases"]) for b in blocks if b["root_id"] == "CM1.1"] == [
        (0, "ACGT"), (4, "NNNN"), (8, "ACRT")]  # uppercase, IUPAC kept, in blocks of 4 here
    assert pq.read_table(out / "layer_n_runs.parquet").to_pylist() == [{"root_id": "CM1.1", "start": 4, "end": 8}]
    assert pq.read_table(out / "layer_softmask_ncbi.parquet").to_pylist() == [
        {"root_id": "CM1.1", "start": 4, "end": 6}, {"root_id": "CM1.1", "start": 8, "end": 10}]
    assert pq.read_table(out / "layer_iupac.parquet").to_pylist() == [{"root_id": "CM1.1", "pos": 10, "code": "R"}]


def test_the_same_root_twice_is_kept_once_if_its_bases_agree(tmp_path):
    a = fasta(tmp_path / "a.fa", [("J1.2", "GATTACAG")])
    b = fasta(tmp_path / "b.fa", [("J1.2", "gattacag")])  # the same bases, soft-masked: one sequence
    result, out = build(tmp_path, {"J1.2": 8}, a, b)
    assert result["read_twice"] == ["J1.2"]
    assert pq.read_table(out / "roots.parquet")["source"].to_pylist() == ["https://x/a.fa"]  # the first file's
    c = fasta(tmp_path / "c.fa", [("J1.2", "GATTACAT")])
    with pytest.raises(Refused, match="other bases in c.fa"):
        build(tmp_path, {"J1.2": 8}, a, c)


@pytest.mark.parametrize(("records", "expected", "match"), [
    ([("X9.1", "ACGT")], {}, "in no assembly report"),
    ([("J1.2", "ACGT")], {"J1.2": 8}, "length 4, but 8 expected"),
    ([("J1.2", "ACGTACG*")], {"J1.2": 8}, "J1.2 in a.fa"),
    ([("J1.2", "GATTACAG")], {"J1.2": 8, "CM1.1": 12}, "1 expected roots are in no declared FASTA"),
])
def test_roots_refuse(tmp_path, records, expected, match):
    with pytest.raises(Refused, match=match):
        build(tmp_path, expected, fasta(tmp_path / "a.fa", records))


def test_a_genbank_record_gives_a_loose_roots_length(tmp_path):
    (tmp_path / "ebv.gb").write_text("LOCUS       AJ507799             171823 bp    DNA     linear   VRL 06-DEC-2024\n")
    assert roots.genbank_length(tmp_path / "ebv.gb") == 171823
