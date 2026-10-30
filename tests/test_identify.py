"""Tests for seqcol digests, header parsing and identify.

Identify tests need the catalog (REGISTRY/build/grch38); they are skipped
when it is not there. Set REF_REGISTRY_CATALOG to point elsewhere.
"""

import gzip
import hashlib
import os
import struct
from pathlib import Path

import pytest

from ref_registry import seqcol
from ref_registry.parse import read_header

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = Path(os.environ.get("REF_REGISTRY_CATALOG", "/net/common/genomes/registry/build/grch38"))
needs_catalog = pytest.mark.skipif(not (CATALOG / "recipes.parquet").exists(), reason="no catalog")


def test_seqcol_spec_example():
    top, level1 = seqcol.digests(
        ["chr1", "chr2", "chr3"], [248956422, 242193529, 198295559],
        ["SQ.2YnepKM7OkBoOrKmvHbGqguVfF9amCST", "SQ.lwDyBi432Py-7xnAISyQlnlhWDEaBPv2",
         "SQ.Eqk6_SvMMDCc6C-uEfickOUWTatLMDQZ"])
    assert level1 == {"lengths": "5K4odB173rjao1Cnbk5BnvLt9V7aPAa2",
                      "names": "g04lKdxiYtG3dOGeUC5AdKEifw65G0Wp",
                      "sequences": "rD29ZKmEqwwHRXjiQ36p6UMZQ5hemmsb"}
    assert top == "sjNNwm4zov3Dl0FRWbRTcZwzqrTQKIqL"


def test_parse_formats(tmp_path):
    (tmp_path / "x.fai").write_text("chr1\t10\t6\t10\t11\nchr2\t5\t30\t5\t6\n")
    (tmp_path / "x.dict").write_text("@HD\tVN:1.6\n@SQ\tSN:chr1\tLN:10\tM5:ABC\n")
    (tmp_path / "x.vcf").write_text('##fileformat=VCFv4.2\n##contig=<ID=chr1,length=10,md5="abc">\n#CHROM\n')
    (tmp_path / "x.fa").write_text(">chr1 desc\nACgtn\nNNA\n>chr2\nRYA\n")
    assert [(e.name, e.length) for e in read_header(tmp_path / "x.fai").entries] == [("chr1", 10), ("chr2", 5)]
    assert read_header(tmp_path / "x.dict").entries[0].md5 == "abc"
    assert read_header(tmp_path / "x.vcf").entries[0].md5 == "abc"
    fa = read_header(tmp_path / "x.fa")
    assert [(e.name, e.length) for e in fa.entries] == [("chr1", 8), ("chr2", 3)]
    assert fa.entries[0].md5 == hashlib.md5(b"ACGTNNNA").hexdigest()  # uppercased, lines joined
    assert fa.entries[1].md5 == hashlib.md5(b"RYA").hexdigest()        # IUPAC codes kept


def test_parse_bam_binary_reference_list(tmp_path):
    refs = [(b"chr1", 248956422), (b"chrM", 16569)]
    body = b"BAM\x01" + struct.pack("<i", 0) + struct.pack("<i", len(refs))
    for name, n in refs:
        body += struct.pack("<i", len(name) + 1) + name + b"\0" + struct.pack("<i", n)
    path = tmp_path / "x.bam"
    with gzip.open(path, "wb") as f:
        f.write(body)
    assert [(e.name, e.length) for e in read_header(path).entries] == [("chr1", 248956422), ("chrM", 16569)]


def test_real_headers_parse():
    assert len(read_header(FIXTURES / "encode_ENCFF462XCI.sam").entries) == 2066
    assert len(read_header(FIXTURES / "gnomad_v4.1_genomes_chr21.vcf").entries) == 24
    assert len(read_header(FIXTURES / "giab_HG002_GRCh38_v4.2.1.vcf").entries) == 195


@pytest.fixture(scope="module")
def cat():
    from ref_registry.catalog import Catalog
    return Catalog(CATALOG)


def run(path, cat):
    from ref_registry.identify import identify
    return identify(read_header(path), cat)


def write_dict(path, seqs):
    path.write_text("@HD\tVN:1.6\n" + "".join(f"@SQ\tSN:{n}\tLN:{l}\tM5:{m}\n" for n, l, m in seqs))
    return path


@needs_catalog
def test_exact_dict_and_seqcol(cat, tmp_path):
    seqs = [(s.name, s.length, s.md5) for s in cat.flavors["Broad_Homo_sapiens_assembly38"]]
    res = run(write_dict(tmp_path / "broad.dict", seqs), cat)
    assert res.best[0].verdict == "exact"
    assert {c.flavor for c in res.best} == {"Broad_Homo_sapiens_assembly38", "iGenomes_GATK_GRCh38",
                                           "1000G_GRCh38_full_analysis_set_plus_decoy_hla"}
    assert res.seqcol_digest == cat.recipes["Broad_Homo_sapiens_assembly38"]["seqcol_digest"]


@needs_catalog
def test_consistent_without_md5_explains_ambiguity(cat):
    res = run(FIXTURES / "giab_HG002_GRCh38_v4.2.1.vcf", cat)
    assert res.best[0].verdict == "consistent"
    assert "GRCh38_no_alt_analysis_set" in {c.flavor for c in res.best}
    assert "UCSC_hg38.analysisSet" in {c.flavor for c in res.best}
    assert any("IUPAC" in a for a in res.ambiguity)


@needs_catalog
def test_subset_and_contains(cat):
    gnomad = run(FIXTURES / "gnomad_v4.1_genomes_chr21.vcf", cat)
    assert gnomad.best[0].verdict == "subset"
    assert "GRCh38_no_alt_analysis_set" in {c.flavor for c in gnomad.best}
    encode = run(FIXTURES / "encode_ENCFF462XCI.sam", cat)
    assert encode.best[0].verdict == "contains"
    assert "GRCh38_no_alt_analysis_set" in {c.flavor for c in encode.best}
    assert len(encode.best[0].extra) == 1871


@needs_catalog
def test_renamed_by_md5_and_variant_swap(cat, tmp_path):
    def ensembl_style(name):  # chr1 -> 1, chrM -> MT; scaffolds keep their accession
        return "MT" if name == "chrM" else name.removeprefix("chr")
    renamed = [(ensembl_style(s.name), s.length, s.md5) for s in cat.flavors["GENCODE50_primary_assembly"]]
    res = run(write_dict(tmp_path / "renamed.dict", renamed), cat)
    assert res.best[0].flavor == "Ensembl116_primary_assembly"
    assert res.best[0].matched == 194 and res.best[0].order_differs

    from ref_registry.identify import describe
    ucsc_chr21 = next(s.md5 for s in cat.flavors["UCSC_hg38.analysisSet"] if s.name == "chr21")
    broad = [(s.name, s.length, ucsc_chr21 if s.name == "chr21" else s.md5)
             for s in cat.flavors["Broad_Homo_sapiens_assembly38"]]
    res = run(write_dict(tmp_path / "swap.dict", broad), cat)
    c = res.best[0]
    assert c.verdict == "partial" and len(c.different_bases) == 1
    assert any("IUPAC" in d and "chr21" in d for d in describe(c, cat))


@needs_catalog
def test_other_assembly_is_no_good_match(cat, tmp_path):
    sizes = tmp_path / "chm13.chrom.sizes"
    sizes.write_text("chr1\t248387328\nchr2\t242696752\nchrM\t16569\n\n")
    res = run(sizes, cat)
    assert res.best[0].verdict == "partial"
    assert res.best[0].matched * 2 < 3


@needs_catalog
def test_materialize_subset_variants_and_batches(cat):
    from ref_registry.materialize import SCHEMA, materialize
    variants = {}
    for flavor in ("GRCh38_no_alt_analysis_set", "UCSC_hg38.analysisSet", "UCSC_hg38", "Ensembl116_primary_assembly"):
        name = "21" if flavor.startswith("Ensembl") else "chr21"
        t = materialize(cat, flavor, names=[name]).read_all()
        assert t.schema.equals(SCHEMA, check_metadata=False)
        assert "ref_registry:seqcol_digest" not in (t.schema.metadata or {})  # a subset has no flavor digest
        seq = t["sequence"][0].as_py()
        assert len(seq) == 46709983 and seq == seq.upper()
        variants[flavor] = hashlib.md5(seq.encode()).hexdigest()
    # chr21 in four published versions: masked or not, IUPAC -> N or not.
    assert variants["GRCh38_no_alt_analysis_set"] == "974dc7aec0b755b19f031418fdedf293"
    assert len(set(variants.values())) == 3  # Ensembl and UCSC hg38 share the IUPAC -> N version
    assert variants["UCSC_hg38"] == variants["Ensembl116_primary_assembly"]

    batches = list(materialize(cat, "GRCh38_no_alt_analysis_set", names=["chrM", "chrEBV", "chr22"],
                               max_batch_bytes=200_000))
    # Flavor order (chr22, chrM, chrEBV), not request order; chr22 alone exceeds the limit.
    assert [b.column("name").to_pylist() for b in batches] == [["chr22"], ["chrM", "chrEBV"]]


@needs_catalog
def test_materialize_external_hla(cat):
    from ref_registry.materialize import materialize
    t = materialize(cat, "Broad_Homo_sapiens_assembly38", names=["HLA-A*01:01:01:01"]).read_all()
    seq = t["sequence"][0].as_py()
    assert len(seq) == 3503 and hashlib.md5(seq.encode()).hexdigest() == "01cd0df602495b044b2c214d69a60aa2"


def _revcomp(s: str) -> str:
    return s.translate(str.maketrans("ACGTRYKMBDHVSWN", "TGCAYRMKVHDBSWN"))[::-1]


@needs_catalog
def test_fetch_matches_materialize(cat):
    import random
    import pyarrow as pa
    from ref_registry import fetch
    from ref_registry.materialize import materialize
    rng = random.Random(7)
    for flavor in ("GRCh38_no_alt_analysis_set", "UCSC_hg38.analysisSet", "Ensembl116_primary_assembly"):
        names = ["21", "Y", "1"] if flavor.startswith("Ensembl") else ["chr21", "chrY", "chr1"]
        full = {n: s for n, s in zip(*materialize(cat, flavor, names=names).read_all()
                                     .select(["name", "sequence"]).to_pydict().values())}
        rows = []
        for n, s in full.items():
            L = len(s)
            rows += [(n, a, a + w, st) for a, w, st in
                     [(rng.randrange(L - 5000), rng.choice([1, 100, 5000]), rng.choice(["+", "-", None]))
                      for _ in range(30)]]
            rows += [(n, 65536 - 7, 65536 + 7, "+"),                  # across a block boundary
                     (n, 32 * 65536 - 3, 32 * 65536 + 3, "-"),        # across a row-group boundary
                     (n, L - 10, L, None), (n, 5, 5, "+")]            # the end, and an empty interval
        iv = pa.table({"chrom": [r[0] for r in rows], "start": [r[1] for r in rows],
                       "end": [r[2] for r in rows], "strand": [r[3] for r in rows]})
        for engine in ("pyarrow", "datafusion"):
            got = fetch(cat, flavor, iv, strand="strand", engine=engine)
            for (n, a, b, st), seq in zip(rows, got["sequence"].to_pylist()):
                want = full[n][a:b]
                assert seq == (_revcomp(want) if st == "-" else want), (engine, flavor, n, a, b, st)
        few = iv.slice(0, 3)  # few blocks per sequence: the per-sequence IN-list path
        assert (fetch(cat, flavor, few, strand="strand", engine="datafusion")["sequence"].to_pylist()
                == fetch(cat, flavor, few, strand="strand", engine="pyarrow")["sequence"].to_pylist())


@needs_catalog
def test_fetch_coordinates_bounds_and_names(cat):
    import pyarrow as pa
    from ref_registry import fetch
    zero = fetch(cat, "GRCh38_no_alt_analysis_set", pa.table({"chrom": ["chr1"], "start": [99], "end": [110]}))
    one = pa.table({"chrom": ["chr1"], "start": [100], "end": [110]}).replace_schema_metadata(
        {b"bio.coordinate_system_zero_based": b"false"})           # polars-bio's 1-based closed
    assert fetch(cat, "GRCh38_no_alt_analysis_set", one)["sequence"][0] == zero["sequence"][0]
    with pytest.raises(ValueError, match="contradicts|say"):
        fetch(cat, "GRCh38_no_alt_analysis_set", one, zero_based=True)
    past = pa.table({"chrom": ["chrM"], "start": [16560], "end": [16600]})
    with pytest.raises(ValueError, match="outside"):
        fetch(cat, "GRCh38_no_alt_analysis_set", past)
    assert len(fetch(cat, "GRCh38_no_alt_analysis_set", past, clip=True)["sequence"][0].as_py()) == 9
    with pytest.raises(KeyError, match="no sequence named"):
        fetch(cat, "GRCh38_no_alt_analysis_set", pa.table({"chrom": ["1"], "start": [0], "end": [1]}))
    hla = fetch(cat, "Broad_Homo_sapiens_assembly38",
                pa.table({"chrom": ["HLA-A*01:01:01:01"], "start": [0], "end": [3503]}))
    assert hashlib.md5(hla["sequence"][0].as_py().encode()).hexdigest() == "01cd0df602495b044b2c214d69a60aa2"


@needs_catalog
def test_sequence_by_md5_and_unknown(cat, tmp_path):
    from ref_registry import populate_ref_cache, sequence_by_md5
    chrM = sequence_by_md5(cat, "c68f52674c9fb33aef52dcf399755519")
    assert len(chrM) == 16569 and hashlib.md5(chrM).hexdigest() == "c68f52674c9fb33aef52dcf399755519"
    r = populate_ref_cache(cat, ["c68f52674c9fb33aef52dcf399755519", "0" * 32], tmp_path)
    assert r["written"] == ["c68f52674c9fb33aef52dcf399755519"] and r["unknown"] == ["0" * 32]
    assert (tmp_path / "c6" / "8f" / "52674c9fb33aef52dcf399755519").read_bytes() == chrM
    again = populate_ref_cache(cat, ["c68f52674c9fb33aef52dcf399755519"], tmp_path)
    assert again["present"] == ["c68f52674c9fb33aef52dcf399755519"] and not again["written"]


@needs_catalog
@pytest.mark.skipif(not __import__("shutil").which("samtools"), reason="no samtools")
def test_cram_round_trip_through_ref_cache(cat, tmp_path):
    """Write a CRAM against chrM, delete the reference, decode it through a filled REF_CACHE."""
    import subprocess
    from ref_registry import populate_ref_cache, sequence_by_md5
    chrM = sequence_by_md5(cat, "c68f52674c9fb33aef52dcf399755519").decode()
    (tmp_path / "ref.fa").write_text(">chrM\n" + chrM + "\n")      # samtools needs a FASTA to write CRAM
    read = chrM[1000:1050]
    (tmp_path / "x.sam").write_text("@HD\tVN:1.6\n@SQ\tSN:chrM\tLN:16569\n"
                                    f"r1\t0\tchrM\t1001\t60\t50M\t*\t0\t0\t{read}\t{'I' * 50}\n")
    subprocess.run(["samtools", "faidx", "ref.fa"], cwd=tmp_path, check=True)
    subprocess.run(["samtools", "view", "-C", "-T", "ref.fa", "-o", "x.cram", "x.sam"], cwd=tmp_path, check=True)
    (tmp_path / "ref.fa").unlink(); (tmp_path / "ref.fa.fai").unlink()

    header = read_header(tmp_path / "x.cram")
    assert header.format == "cram" and header.entries[0].md5 == "c68f52674c9fb33aef52dcf399755519"
    populate_ref_cache(cat, [e.md5 for e in header.entries], tmp_path / "cache")
    env = {**os.environ, "REF_PATH": "/nonexistent", "REF_CACHE": f"{tmp_path}/cache/%2s/%2s/%s"}
    out = subprocess.run(["samtools", "view", "x.cram"], cwd=tmp_path, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert out.split("\t")[9] == read


RELEASE = Path(os.environ.get("REF_REGISTRY_RELEASE", "/net/common/genomes/registry/catalog/0.1.0"))


@pytest.mark.skipif(not (RELEASE / "catalog.json").exists(), reason="no exported catalog release")
def test_remote_catalog_over_http(tmp_path):
    """Open an exported release by URL from a local Range-honoring server; compare with local."""
    import threading
    import pyarrow as pa
    from ref_registry import Catalog, fetch, identify
    from ref_registry._serve import serve
    server = serve(str(RELEASE), port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        remote, local = Catalog(url, cache=tmp_path), Catalog(RELEASE)
        assert remote.manifest["version"] == local.manifest["version"]
        assert not (tmp_path / "catalog" / remote.manifest["version"] / "root_blocks.parquet").exists()
        res = identify(read_header(FIXTURES / "giab_HG002_GRCh38_v4.2.1.vcf"), remote)
        assert res.best[0].verdict == "consistent"
        iv = pa.table({"chrom": ["chr1", "chrY", "chrM"], "start": [1_000_000, 10_000, 0],
                       "end": [1_000_100, 10_050, 16569]})
        got = fetch(remote, "GRCh38_no_alt_analysis_set", iv)  # auto -> pyarrow over plain http
        want = fetch(local, "GRCh38_no_alt_analysis_set", iv, engine="pyarrow")
        assert got["sequence"].to_pylist() == want["sequence"].to_pylist()
        assert 0 < remote.blocks_http.requests < 20
    finally:
        server.shutdown()
