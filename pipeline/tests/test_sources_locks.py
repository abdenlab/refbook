"""Sources and locks, on a small raw/ tree made here: what each kind of declaration selects, and every way a lock
refuses (a publisher's checksum, a changed, new or missing file), accepts (first use, an exception, --update), or
stays put."""

import hashlib
import textwrap

import pytest
from refbook_pipeline import Refused, locks, sources

NCBI = "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_1.1_Test"


def write(raw, rel, text):
    p = raw / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def md5(text):
    return hashlib.md5(text.encode()).hexdigest()


@pytest.fixture
def declared(tmp_path):
    toml = tmp_path / "sources.toml"
    toml.write_text(textwrap.dedent(f"""
        [[source]]
        name = "Test"
        roles = ["input"]
        ncbi_assembly = "{NCBI}"
        also = ["GCA_1.1_Test_genomic.fna.gz"]

        [[source]]
        name = "Sub"
        roles = ["input", "target"]
        base = "{NCBI}/sub"
        files = ["a.txt"]
        checksums = ["{NCBI}/md5checksums.txt"]

        [[source]]
        name = "EBV"
        roles = ["input"]
        efetch = {{ accessions = ["AJ507799.2"], rettypes = ["fasta", "gb"] }}

        [[source]]
        name = "HLA"
        roles = ["input"]
        base = "raw.githubusercontent.com/o/r/1"
        files = ["LICENSE.md"]
        github_tree = {{ repo = "o/r", ref = "1", prefix = "fasta/", suffix = "_gen.fasta" }}
    """))
    return sources.load(toml)


@pytest.fixture
def raw(tmp_path):
    raw = tmp_path / "raw"
    report, fna, sub = "report\r\n", "fna", "sub file"
    write(raw, f"{NCBI}/GCA_1.1_Test_assembly_report.txt", report)
    write(raw, f"{NCBI}/GCA_1.1_Test_genomic.fna.gz", fna)
    write(raw, f"{NCBI}/GCA_1.1_Test_assembly_structure/Primary_Assembly/x.agp.gz", "agp")
    write(raw, f"{NCBI}/GCA_1.1_Test_assembly_structure/Primary_Assembly/x.fna.gz", "skipped: sequence")
    write(raw, f"{NCBI}/GCA_1.1_Test_assembly_structure/index.html", "skipped: a listing")
    write(raw, f"{NCBI}/md5checksums.txt",
          f"{md5(report)}  ./GCA_1.1_Test_assembly_report.txt\n{md5(fna)}  ./GCA_1.1_Test_genomic.fna.gz\n"
          f"{md5(sub)}  ./sub/a.txt\n")
    write(raw, f"{NCBI}/sub/a.txt", sub)
    write(raw, "eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.fasta", ">EBV\nACGT\n")
    write(raw, "eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.gb", "LOCUS")
    write(raw, "raw.githubusercontent.com/o/r/1/LICENSE.md", "licence")
    write(raw, "raw.githubusercontent.com/o/r/1/fasta/A_gen.fasta", ">A")
    write(raw, "raw.githubusercontent.com/o/r/1/fasta/A_nuc.fasta", "not a _gen file")
    return raw


def test_each_kind_of_declaration_selects_its_files(declared, raw):
    rels, missing = sources.files(declared["Test"], raw)
    assert missing == []
    assert [r.removeprefix(NCBI + "/") for r in rels] == [
        "GCA_1.1_Test_assembly_report.txt", "GCA_1.1_Test_assembly_structure/Primary_Assembly/x.agp.gz",
        "GCA_1.1_Test_genomic.fna.gz", "md5checksums.txt"]  # optional files it lacks are simply absent
    assert sources.files(declared["EBV"], raw) == (
        ["eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.fasta",
         "eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.gb"], [])
    assert sources.files(declared["HLA"], raw)[0] == [
        "raw.githubusercontent.com/o/r/1/LICENSE.md", "raw.githubusercontent.com/o/r/1/fasta/A_gen.fasta"]
    (raw / "eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.gb").unlink()
    assert sources.files(declared["EBV"], raw)[1] == ["eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.gb"]


def test_urls_are_paths_and_efetch_records_their_query():
    assert sources.url_of(f"{NCBI}/x.txt") == f"https://{NCBI}/x.txt"
    assert sources.url_of("eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.gb") == (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id=AJ507799.2&rettype=gb&retmode=text")


def test_fetch_commands_mirror_the_declaration(declared):
    cmds = sources.commands(declared["Test"])
    urls = [(c[-1], may_fail) for c, may_fail in cmds]
    assert (f"https://{NCBI}/GCA_1.1_Test_genomic.fna.gz", False) in urls  # required
    assert (f"https://{NCBI}/GCA_1.1_Test_assembly_regions.txt", True) in urls  # optional: may 404
    tree = next(c for c, _ in cmds if "--recursive" in c)
    assert tree[tree.index("--reject") + 1] == "index.html*,*.fna.gz,*.fa.gz"
    assert [c[-1] for c, _ in sources.commands(declared["HLA"], ["fasta/A_gen.fasta"])][-1] == (
        "https://raw.githubusercontent.com/o/r/1/fasta/A_gen.fasta")


def lock_of(declared, raw, name, tmp_path, **kw):
    src = declared[name]
    rels, missing = sources.files(src, raw)
    return locks.lock(name, raw, rels, missing, tmp_path / f"{name}.lock", checksums=src.checksums, **kw)


def test_first_use_writes_then_unchanged_stays(declared, raw, tmp_path):
    first = lock_of(declared, raw, "Test", tmp_path)
    assert first["lock"].startswith("written") and first["checked_by_publisher"] == 2
    before = (tmp_path / "Test.lock").read_text()
    assert lock_of(declared, raw, "Test", tmp_path)["lock"] == "unchanged"
    assert (tmp_path / "Test.lock").read_text() == before
    row = locks.read(tmp_path / "Test.lock")[f"{NCBI}/GCA_1.1_Test_genomic.fna.gz"]
    assert row["bytes"] == "3" and row["url"] == f"https://{NCBI}/GCA_1.1_Test_genomic.fna.gz"


def test_a_publisher_mismatch_refuses_unless_documented(declared, raw, tmp_path):
    write(raw, f"{NCBI}/GCA_1.1_Test_assembly_report.txt", "served otherwise")
    with pytest.raises(Refused, match="does not match"):
        lock_of(declared, raw, "Test", tmp_path)
    assert not (tmp_path / "Test.lock").exists()
    (tmp_path / "Test.exceptions.tsv").write_text(
        "path\tlisted_md5\tserved_md5\tnote\n"
        f"{NCBI}/GCA_1.1_Test_assembly_report.txt\t{md5('report' + chr(13) + chr(10))}\t{md5('served otherwise')}\tchecked\n")
    assert lock_of(declared, raw, "Test", tmp_path)["lock"].startswith("written")


def test_a_list_elsewhere_covers_a_subdirectory_source(declared, raw, tmp_path):
    assert lock_of(declared, raw, "Sub", tmp_path)["checked_by_publisher"] == 1
    write(raw, f"{NCBI}/sub/a.txt", "changed")
    with pytest.raises(Refused, match="does not match"):
        lock_of(declared, raw, "Sub", tmp_path)


def test_a_changed_new_or_missing_file_refuses_and_keeps_the_lock(declared, raw, tmp_path):
    lock_of(declared, raw, "EBV", tmp_path)  # no publisher list: the lock alone covers these
    before = (tmp_path / "EBV.lock").read_text()
    write(raw, "eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.gb", "LOCUS changed")
    for _ in range(2):  # and again: the lock is still the old one, so it still refuses
        with pytest.raises(Refused, match="1 changed"):
            lock_of(declared, raw, "EBV", tmp_path)
        assert (tmp_path / "EBV.lock").read_text() == before
    assert lock_of(declared, raw, "EBV", tmp_path, update=True)["lock"].startswith("updated: 0 new, 0 missing, 1 changed")
    assert lock_of(declared, raw, "EBV", tmp_path)["lock"] == "unchanged"
    (raw / "eutils.ncbi.nlm.nih.gov/efetch/nuccore_AJ507799.2.gb").unlink()
    with pytest.raises(Refused, match="required files are not under"):
        lock_of(declared, raw, "EBV", tmp_path)


def test_declarations_must_be_unique_and_have_roles(tmp_path):
    bad = tmp_path / "s.toml"
    bad.write_text('[[source]]\nname = "A"\nroles = ["input"]\n[[source]]\nname = "A"\nroles = ["input"]\n')
    with pytest.raises(Refused, match="declared twice"):
        sources.load(bad)
    bad.write_text('[[source]]\nname = "A"\nroles = ["output"]\n')
    with pytest.raises(Refused, match="roles"):
        sources.load(bad)
