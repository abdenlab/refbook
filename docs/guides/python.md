# Python package

## Usage

Everything starts from a `Catalog`, opened from a release URL or a local
build:

```python
from refbook import Catalog

cat = Catalog("https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/")
```

A remote catalog's small tables are cached in `~/.cache/refbook`
(`REFBOOK_CACHE`, or `Catalog(url, cache=...)`); bases are read with HTTP range requests as needed.

## Collections

Most functions take a **collection**, which can be:

- an edition label: `"hg38-analysis-set"`;
- a published file, which has its own order: `"UCSC_hg38.analysisSet"`;
- a seqcol digest, or a seqcol object (level 1 or 2);
- any list of `(name, digest)` pairs whose sequences the catalog holds, with
  each digest an MD5 or an `SQ.` digest. It needn't be a cataloged edition.

## Identify a header

```python
from refbook import identify, read_header

result = identify(read_header("sample.bam"), cat)
best = result.best[0]
best.verdict, [c.edition for c in result.best], best.in_order_of
```

`read_header` reads the same formats as the [command line](../reference/command-line.md).
`refbook.identify.sequences(header, cat)` says what each sequence is on its
own, as `--sequences` does.

## Resolve to a seqcol level

```python
from refbook import resolve

resolve(cat, "hg38-analysis-set", 0)   # its seqcol digest
resolve(cat, "hg38-analysis-set", 1)   # one digest per attribute
resolve(cat, "hg38-analysis-set", 2)   # names, lengths, sequence digests and the ancillary attributes
```

## Materialize sequences

`materialize` returns an Arrow stream, one row per sequence (name, description
and sequence), following the CompoSeq Sequence schema.

```python
from refbook import materialize

chrM = materialize(cat, "chm13v2.0", names=["chrM"]).read_all()
mine = materialize(cat, [("mito", "c68f52674c9fb33aef52dcf399755519"),
                         ("chr21", "974dc7aec0b755b19f031418fdedf293")]).read_all()
```

Every sequence is built from its root and checked against its MD5 and `SQ.`
digest.

## Fetch bases at intervals

```python
import pyarrow as pa
from refbook import fetch

intervals = pa.table({"chrom": ["chr1", "chr21"], "start": [1_000_000, 30_000_000],
                      "end": [1_000_020, 30_000_020], "strand": ["+", "-"]})
fetch(cat, "grch38-no-alt", intervals, strand="strand")
```

Intervals are 0-based, half-open by default, with polars-bio's column names;
`-` strands are reverse-complemented. Polars and pandas frames work too, and
polars-bio's coordinate-system metadata is honored, so its 1-based frames are
converted correctly. An interval outside its sequence is an error unless
`clip=True`. The `datafusion` extra makes fetches from a local catalog
faster.

## A sequence by its MD5

```python
from refbook import sequence_by_md5

sequence_by_md5(cat, "c68f52674c9fb33aef52dcf399755519")   # rCRS: 16,569 bases
```

## Compare two collections

`seqcol.compare` answers which attributes the two share, and how their elements overlap.

```python
from refbook import seqcol

seqcol.compare(resolve(cat, "grch38-no-alt", 2), resolve(cat, "hg38-analysis-set", 2))
```

The full list of functions is in the [API reference](../reference/python.md).
