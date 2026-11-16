# refbook

**A catalog of human reference genome editions, and a library to identify,
fetch and reconstruct them.**

"GRCh38" names dozens of different FASTA files, and "hg19" or "T2T" as many
again: each publisher includes different sequences, names and orders them
differently, and masks or rewrites some bases. refbook describes every
published file as a recipe applied to the original deposited sequences, checks
each by rebuilding the file, and answers practical questions on top of that
catalog:

- **Which reference is this?** Identify a BAM, CRAM, VCF, `.dict`, `.fai` or
  FASTA from its header.
- **Give me its sequence.** Materialize any cataloged edition as an Arrow
  stream, or fetch the bases at a table of intervals.
- **Decode this CRAM.** Fill htslib's `REF_CACHE`, including masked or
  IUPAC-rewritten sequences that no public MD5 server holds.
- **Serve it.** Run a GA4GH refget server (Sequences v2, Sequence Collections
  v1) over the catalog.

```
$ refbook identify Homo_sapiens_assembly38.dict
Homo_sapiens_assembly38.dict
  dict, 3366 sequences, with digests
  EXACT: hs38dh
```

```python
from refbook import Catalog, identify, read_header

cat = Catalog("https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/")
identify(read_header("sample.bam"), cat).best
```

The catalog is read from Hugging Face
([abdenlab/refbook](https://huggingface.co/datasets/abdenlab/refbook)): only the
small tables, about 1.3 MB, are cached, and bases are read with HTTP range
requests as needed.

## Install

Not yet on PyPI. From a clone of
[abdenlab/refbook](https://github.com/abdenlab/refbook), with a Rust toolchain,
since the core is compiled into the package:

```bash
pip install ./python                 # the library and the `refbook` command
pip install "./python[datafusion]"   # also DataFusion, for faster fetches from a local catalog
```

## Documentation

[abdenlab.org/refbook](https://abdenlab.org/refbook/): getting started, the
model behind the catalog, guides to the command line and Python, and the API
reference.
