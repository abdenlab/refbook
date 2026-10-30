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
