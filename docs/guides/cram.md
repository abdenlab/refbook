# Decoding CRAMs

A CRAM stores reads as differences from a reference, so decoding one needs the
exact reference sequences it was written against. The file names each one by
MD5 but doesn't say where to get it. refbook can supply any sequence it
catalogs, including masked and IUPAC-rewritten ones that no public server
holds.

## What a CRAM carries

- Each `@SQ` line has `SN`, `LN` and `M5`: the MD5 of the whole sequence,
  uppercased, with no newlines.
- Records carry only a reference index and a position.
- Each slice header carries the MD5 of the span of reference it covers, so a
  decoder can check it used the right bases.
- `UR` is optional, and is usually a path on the machine that wrote the file.
  Since htslib 1.22, a `UR` that points to a remote location is an error.

## How htslib finds a reference sequence

1. An explicit reference (`-T`/`--reference`), looked up by name. A wrong
   reference is caught by the slice MD5s.
2. Otherwise `REF_CACHE`, by `M5`.
3. Then `REF_PATH`: a colon-separated list of directory or URL templates
   (`%s` is the MD5, `%2s` the next two characters of it). For a URL, htslib
   fetches the whole sequence with a plain GET.
4. Then a local `UR` path.

**htslib 1.22 (May 2025) removed the defaults.** Up to 1.21, an unset
`REF_PATH` meant the EBI's server, with a cache in `~/.cache/hts-ref` turned on
automatically. Now neither is set, and a CRAM opened without `-T` and without
configuration fails to decode. EBI's server, in any case, holds only INSDC
sequences: a CRAM aligned to UCSC or Ensembl hg38, whose sequences have IUPAC
codes rewritten as `N`, can't be decoded from it.

## Filling the cache ahead of time

```
refbook populate-ref-cache sample.cram --root ~/refcache
REF_CACHE=~/refcache/%2s/%2s/%s samtools view sample.cram
```

`populate-ref-cache` reads the CRAM's `@SQ` MD5s, builds each sequence the
catalog knows from its root, checks its MD5, and writes it into the cache: one
file per sequence, named by MD5, raw uppercase bases with no header or
newlines, as htslib expects. Sequences already present are skipped, and
sequences unknown to the catalog are reported; htslib falls back to `REF_PATH`
for those. A whole human edition takes about 3 GB on disk, less what editions
share, since a sequence several editions use is stored once.

It also takes BAM and SAM headers, `.dict` files, or bare MD5s. In Python:

```python
from refbook import Catalog, populate_ref_cache

cat = Catalog("https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/")
populate_ref_cache(cat, md5s, "/data/refcache")   # md5s: the MD5s to write
```

## Serving sequences on request

Alternatively, run [`refbook serve`](refget-server.md) and point htslib at it:

```
REF_PATH=http://localhost:8000/sequence/%s
```

The server builds each sequence from its root when htslib asks for it.
