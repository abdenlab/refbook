"""Tests for seqcol digests, header parsing, identify, resolve, materialize,
fetch and the reference cache.

Most need a catalog: REFBOOK_CATALOG, by default the repository's build
(catalog/output/build/catalog); they are skipped without one. Reading a
release over HTTP is tested with the export, in catalog/tests.
"""

import gzip
import hashlib
import os
import struct
from pathlib import Path

import pytest

from refbook import seqcol
from refbook.parse import open_compressed, read_header

FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = Path(os.environ.get("REFBOOK_CATALOG",
                              Path(__file__).resolve().parents[2] / "catalog" / "output" / "build" / "catalog"))
needs_catalog = pytest.mark.skipif(not (CATALOG / "catalog.json").exists(), reason="no catalog")


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
    assert [e.sq for e in fa.entries] == ["SQ." + seqcol.sha512t24u(b) for b in (b"ACGTNNNA", b"RYA")]


def test_gzip_members_and_trailing_bytes(tmp_path):
    # bgzip-style members in sequence, then bytes that start no member (razip's index): all read, the rest ignored.
    data = b">chr1\nACGT\n" * 1000
    path = tmp_path / "x.fa.gz"
    path.write_bytes(gzip.compress(data[:5000]) + gzip.compress(data[5000:]) + b"\x01wRAZF index")
    with open_compressed(path) as f:
        assert f.read() == data
    with open_compressed(path, "rt") as f:
        assert sum(1 for line in f if line.startswith(">")) == 1000
    assert [e.length for e in read_header(path).entries] == [4] * 1000
    (tmp_path / "plain.fa").write_bytes(data)
    with open_compressed(tmp_path / "plain.fa") as f:
        assert f.read() == data
    path.write_bytes(gzip.compress(data)[:-20])  # a member cut short
    with pytest.raises(EOFError), open_compressed(path) as f:
        f.read()


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
    from refbook.catalog import Catalog
    return Catalog(CATALOG)


def run(path, cat):
    from refbook.identify import identify
    return identify(read_header(path), cat)


def rows(cat, x):
    """(name, length, md5) of a collection, in its order."""
    from refbook import collection
    c = collection(cat, x)
    return [(n, n_bp, cat.sequence[sq]["md5"]) for n, n_bp, sq in zip(c.names, c.lengths, c.sequences)]


def write_dict(path, seqs):
    path.write_text("@HD\tVN:1.6\n" + "".join(f"@SQ\tSN:{n}\tLN:{l}\tM5:{m}\n" for n, l, m in seqs))
    return path


@needs_catalog
def test_every_manifest_sequence_is_identified(cat):
    """By its MD5 or SQ. digest: the sequence, root, operations and editions (as
    store.metadata has them). By name and length: the root, with the sequence
    among its cognates, wherever the name names one root."""
    from refbook import store
    from refbook.identify import sequences
    rows = [(f, s) for f, seqs in cat.manifests.items() for s in seqs]
    by_md5 = sequences([{"name": s.name, "length": s.length, "md5": s.md5.upper()} for _, s in rows], cat)
    by_sq = sequences([{"sq": s.sha512t24u} for _, s in rows], cat)
    by_name = sequences([{"name": s.name, "length": s.length} for _, s in rows], cat)
    settled = 0
    for (edition, s), a, b, c in zip(rows, by_md5, by_sq, by_name):
        m = store.metadata(cat, s.sha512t24u)["refbook"]
        assert a["evidence"] == "digest" and not a["notes"], (edition, s.name, a["notes"])
        assert (a["sequence"], a["root_id"], a["operations"]) == (s.sha512t24u, m["root_id"], m["operations"])
        assert [{"edition": u["edition"], "name": u["name"]} for u in a["editions"]] == m["editions"]
        assert b == a
        if c["evidence"] == "name_and_length":
            settled += 1
            assert c["root_id"] == s.root_id and s.sha512t24u in c["cognates"]
            assert {"edition": edition, "name": s.name, "sequence": s.sha512t24u} in c["editions"]
        else:
            assert [n["kind"] for n in c["notes"]] == ["ambiguous_name"], (edition, s.name, c)
    assert settled > 0.99 * len(rows)


@needs_catalog
def test_identify_sequences_of_a_fasta(cat, tmp_path):
    from refbook.identify import sequences
    from refbook.materialize import Bases, sequence_bases
    sq = next(s.sha512t24u for s in cat.manifests["hg38-analysis-set"] if s.name == "chrEBV")
    bases = sequence_bases(cat, sq, Bases(cat))
    (tmp_path / "x.fa").write_bytes(b">ebv\n" + bases + b"\n>mine\nACGT\n")
    ebv, mine = sequences(read_header(tmp_path / "x.fa"), cat)
    assert (ebv["evidence"], ebv["sequence"], ebv["root_id"]) == ("digest", sq, "AJ507799.2")
    assert (mine["evidence"], [n["kind"] for n in mine["notes"]]) == ("nothing", ["unknown_digest", "unknown_digest"])


@needs_catalog
def test_a_seqcol_document_identifies(cat, tmp_path):
    import json

    from refbook import resolve
    from refbook.identify import identify
    from refbook.parse import seqcol_entries
    target = "UCSC_hg38.analysisSet"
    (tmp_path / "l2.json").write_text(json.dumps(resolve(cat, target, 2)))
    h = read_header(tmp_path / "l2.json")
    assert h.format == "seqcol" and h.has_digests and not h.has_md5
    res = identify(h, cat)
    assert [c.edition for c in res.best] == ["hg38-analysis-set"] and res.best[0].verdict == "exact"
    assert target in res.best[0].in_order_of
    assert res.seqcol_digest == cat.targets[target]["seqcol_digest"]
    (tmp_path / "l1.json").write_text(json.dumps(resolve(cat, target, 1)))
    with pytest.raises(ValueError, match="level-1"):
        read_header(tmp_path / "l1.json")
    with pytest.raises(ValueError, match="names and sequences"):
        seqcol_entries({"lengths": [1]})


@needs_catalog
def test_exact_dict_and_seqcol(cat, tmp_path):
    res = run(write_dict(tmp_path / "broad.dict", rows(cat, "Broad_Homo_sapiens_assembly38")), cat)
    assert res.best[0].verdict == "exact"
    assert [c.edition for c in res.best] == ["hs38dh"]
    assert "Broad_Homo_sapiens_assembly38" in res.best[0].in_order_of
    assert res.seqcol_digest == cat.targets["Broad_Homo_sapiens_assembly38"]["seqcol_digest"]
    assert "Broad_Homo_sapiens_assembly38" in res.seqcol_matches
    assert not res.unknown and len(res.sequences) == 3366


@needs_catalog
def test_consistent_without_md5_explains_ambiguity(cat):
    res = run(FIXTURES / "giab_HG002_GRCh38_v4.2.1.vcf", cat)
    assert res.best[0].verdict == "consistent"
    assert {"grch38-no-alt", "hg38-analysis-set"} <= {c.edition for c in res.best}
    assert any("IUPAC" in a for a in res.ambiguity)


@needs_catalog
def test_subset_and_contains(cat):
    gnomad = run(FIXTURES / "gnomad_v4.1_genomes_chr21.vcf", cat)
    assert gnomad.best[0].verdict == "subset"
    assert "grch38-no-alt" in {c.edition for c in gnomad.best}
    encode = run(FIXTURES / "encode_ENCFF462XCI.sam", cat)
    assert encode.best[0].verdict == "contains"
    assert "grch38-no-alt" in {c.edition for c in encode.best}
    assert len(encode.best[0].extra) == 1871


@needs_catalog
def test_order_is_reported_not_judged(cat, tmp_path):
    # Ensembl's names and bases in GENCODE's order: the same edition as Ensembl's
    # primary assembly, in an order no Ensembl target uses.
    def ensembl_style(name):  # chr1 -> 1, chrM -> MT; scaffolds keep their accession
        return "MT" if name == "chrM" else name.removeprefix("chr")
    reordered = [(ensembl_style(n), n_bp, m) for n, n_bp, m in rows(cat, "GENCODE50_primary_assembly")]
    res = run(write_dict(tmp_path / "reordered.dict", reordered), cat)
    assert res.best[0].edition == "ensembl-grch38-primary" and res.best[0].verdict == "exact"
    assert res.best[0].in_order_of == []
    in_order = run(write_dict(tmp_path / "ensembl.dict", rows(cat, "Ensembl116_primary_assembly")), cat)
    assert in_order.best[0].in_order_of == ["Ensembl116_primary_assembly"]


@needs_catalog
def test_renamed_by_md5_and_derivative_swap(cat, tmp_path):
    from refbook.identify import describe
    renamed = [(f"seq{i}", n_bp, m) for i, (n, n_bp, m) in enumerate(rows(cat, "grch38-no-alt"))]
    res = run(write_dict(tmp_path / "renamed.dict", renamed), cat)
    assert res.best[0].edition == "grch38-no-alt" and len(res.best[0].renamed) == 195

    ucsc_chr21 = next(m for n, _, m in rows(cat, "hg38-analysis-set") if n == "chr21")
    broad = [(n, n_bp, ucsc_chr21 if n == "chr21" else m) for n, n_bp, m in rows(cat, "hs38dh")]
    c = run(write_dict(tmp_path / "swap.dict", broad), cat).best[0]
    assert c.verdict == "partial" and len(c.different_bases) == 1
    assert any("IUPAC" in d and "chr21" in d for d in describe(c, cat))


@needs_catalog
def test_unknown_sequences_are_listed(cat, tmp_path):
    seqs = rows(cat, "grch38-no-alt")[:3] + [("spikein", 5386, "a" * 32)]
    res = run(write_dict(tmp_path / "spike.dict", seqs), cat)
    assert res.unknown == ["spikein"] and res.seqcol_digest is None and len(res.sequences) == 3


@needs_catalog
def test_a_chm13_header_finds_its_assembly(cat, tmp_path):
    # Three T2T-CHM13 names and lengths: a subset of its editions (chrM's length is rCRS's too, so not of GRCh38's).
    sizes = tmp_path / "chm13.chrom.sizes"
    sizes.write_text("chr1\t248387328\nchr2\t242696752\nchrM\t16569\n\n")
    res = run(sizes, cat)
    assert res.best[0].verdict == "subset"
    assert all(c.edition.startswith(("chm13", "ensembl-chm13")) for c in res.best if c.verdict == "subset")


@needs_catalog
def test_materialize_subset_variants_and_batches(cat):
    from refbook.materialize import SCHEMA, materialize
    md5s = {}
    for edition in ("grch38-no-alt", "hg38-analysis-set", "hg38", "ensembl-grch38-primary"):
        name = "21" if edition.startswith("ensembl") else "chr21"
        t = materialize(cat, edition, names=[name]).read_all()
        assert t.schema.equals(SCHEMA, check_metadata=False)
        assert "refbook:seqcol_digest" not in (t.schema.metadata or {})  # a subset has no edition digest
        seq = t["sequence"][0].as_py()
        assert len(seq) == 46709983 and seq == seq.upper()
        md5s[edition] = hashlib.md5(seq.encode()).hexdigest()
    # chr21 in four published versions: masked or not, IUPAC -> N or not.
    assert md5s["grch38-no-alt"] == "974dc7aec0b755b19f031418fdedf293"
    assert len(set(md5s.values())) == 3  # Ensembl and UCSC hg38 share the IUPAC -> N version
    assert md5s["hg38"] == md5s["ensembl-grch38-primary"]

    want = ["chrM", "chrEBV", "chr22"]
    # A target lists its sequences in its own order (chr22, chrM, chrEBV), an edition
    # in canonical order (chr22, chrEBV, chrM); never in request order. chr22
    # alone exceeds the batch limit.
    target = list(materialize(cat, "GRCh38_no_alt_analysis_set", names=want, max_batch_bytes=200_000))
    assert [b.column("name").to_pylist() for b in target] == [["chr22"], ["chrM", "chrEBV"]]
    edition = list(materialize(cat, "grch38-no-alt", names=want, max_batch_bytes=200_000))
    assert [b.column("name").to_pylist() for b in edition] == [["chr22"], ["chrEBV", "chrM"]]


@needs_catalog
def test_resolve_levels_and_uncataloged_collections(cat):
    from refbook import resolve
    from refbook.resolve import UnknownSequences
    target = "Broad_Homo_sapiens_assembly38"
    digest = cat.targets[target]["seqcol_digest"]
    assert resolve(cat, target, 0) == digest
    level2 = resolve(cat, digest, 2)            # by digest, through the collection store
    assert resolve(cat, level2, 0) == digest
    assert resolve(cat, resolve(cat, target, 1), 0) == digest
    assert resolve(cat, target, 1)["sorted_named_sequences"] == cat.editions["hs38dh"]["id"]
    # Any named sequence set the store can resolve, cataloged or not.
    pairs = [("mito", "c68f52674c9fb33aef52dcf399755519"), ("chr21_masked", "974dc7aec0b755b19f031418fdedf293")]
    t = resolve(cat, pairs, 3).read_all()
    assert t["name"].to_pylist() == ["chr21_masked", "mito"]       # canonical order
    assert hashlib.md5(t["sequence"][1].as_py().encode()).hexdigest() == pairs[0][1]
    with pytest.raises(UnknownSequences):
        resolve(cat, [("x", "0" * 32)], 2)


@needs_catalog
def test_materialize_external_hla(cat):
    from refbook.materialize import materialize
    t = materialize(cat, "hs38dh", names=["HLA-A*01:01:01:01"]).read_all()
    seq = t["sequence"][0].as_py()
    assert len(seq) == 3503 and hashlib.md5(seq.encode()).hexdigest() == "01cd0df602495b044b2c214d69a60aa2"


def _revcomp(s: str) -> str:
    return s.translate(str.maketrans("ACGTRYKMBDHVSWN", "TGCAYRMKVHDBSWN"))[::-1]


@needs_catalog
def test_fetch_matches_materialize(cat):
    import random

    import pyarrow as pa

    from refbook import fetch
    from refbook.fetch import _have_datafusion
    from refbook.materialize import materialize
    # DataFusion is an optional extra: compare the engines when it is installed.
    engines = ("pyarrow", "datafusion") if _have_datafusion() else ("pyarrow",)
    rng = random.Random(7)
    for edition in ("grch38-no-alt", "hg38-analysis-set", "ensembl-grch38-primary"):
        names = ["21", "Y", "1"] if edition.startswith("ensembl") else ["chr21", "chrY", "chr1"]
        full = {n: s for n, s in zip(*materialize(cat, edition, names=names).read_all()
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
        for engine in engines:
            got = fetch(cat, edition, iv, strand="strand", engine=engine)
            for (n, a, b, st), seq in zip(rows, got["sequence"].to_pylist()):
                want = full[n][a:b]
                assert seq == (_revcomp(want) if st == "-" else want), (engine, edition, n, a, b, st)
        if "datafusion" not in engines:
            continue
        few = iv.slice(0, 3)  # few blocks per sequence: the per-sequence IN-list path
        assert (fetch(cat, edition, few, strand="strand", engine="datafusion")["sequence"].to_pylist()
                == fetch(cat, edition, few, strand="strand", engine="pyarrow")["sequence"].to_pylist())


@needs_catalog
def test_fetch_coordinates_bounds_and_names(cat):
    import pyarrow as pa

    from refbook import fetch
    zero = fetch(cat, "grch38-no-alt", pa.table({"chrom": ["chr1"], "start": [99], "end": [110]}))
    one = pa.table({"chrom": ["chr1"], "start": [100], "end": [110]}).replace_schema_metadata(
        {b"bio.coordinate_system_zero_based": b"false"})           # polars-bio's 1-based closed
    assert fetch(cat, "grch38-no-alt", one)["sequence"][0] == zero["sequence"][0]
    with pytest.raises(ValueError, match="contradicts|say"):
        fetch(cat, "grch38-no-alt", one, zero_based=True)
    past = pa.table({"chrom": ["chrM"], "start": [16560], "end": [16600]})
    with pytest.raises(ValueError, match="outside"):
        fetch(cat, "grch38-no-alt", past)
    assert len(fetch(cat, "grch38-no-alt", past, clip=True)["sequence"][0].as_py()) == 9
    with pytest.raises(KeyError, match="no sequence named"):
        fetch(cat, "grch38-no-alt", pa.table({"chrom": ["1"], "start": [0], "end": [1]}))
    hla = fetch(cat, "hs38dh",
                pa.table({"chrom": ["HLA-A*01:01:01:01"], "start": [0], "end": [3503]}))
    assert hashlib.md5(hla["sequence"][0].as_py().encode()).hexdigest() == "01cd0df602495b044b2c214d69a60aa2"


@needs_catalog
def test_sequence_by_md5_and_unknown(cat, tmp_path):
    from refbook import populate_ref_cache, sequence_by_md5
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

    from refbook import populate_ref_cache, sequence_by_md5
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


def test_catalog_refuses_another_format(tmp_path):
    import json

    from refbook import Catalog
    (tmp_path / "catalog.json").write_text(json.dumps({"version": "0.1.0", "files": {}}))
    with pytest.raises(ValueError, match="format 1"):
        Catalog(tmp_path)
