<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/refbook-mark-dark.svg">
  <img src="docs/assets/refbook-mark.svg" alt="refbook's mark: a shelf of book spines banded like chromosomes" width="72" height="72">
</picture>

# refbook

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24268815.svg)](https://doi.org/10.5281/zenodo.24268815)

**A catalog of human reference genome editions, and tools to identify, fetch and reconstruct them.**

Naming a genome assembly like "GRCh38", even a specific release, doesn't pin the sequences people actually use for analysis. Several authorities publish their own versions, with different sequences included, different names and order, and some bases masked or rewritten.

refbook describes every such published version as a **recipe** applied to the same **roots**, the original sequences as deposited, and checks each recipe by rebuilding the published files sequence by sequence.

## Links

- **Web app:** [refbook.abdenlab.org](https://refbook.abdenlab.org/)
- **Docs:** [abdenlab.org/refbook](https://abdenlab.org/refbook/)
- **Raw catalog:** [abdenlab/refbook](https://huggingface.co/datasets/abdenlab/refbook) on Hugging Face: plain Parquet, readable without this library

## Quick start

```python
from refbook import Catalog, identify, read_header

cat = Catalog("https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/")
identify(read_header("sample.bam"), cat).best
```

See the guides to the [command line](https://abdenlab.org/refbook/guides/command-line/)
and [Python](https://abdenlab.org/refbook/guides/python/).

## Repository

| Path | Contents |
| --- | --- |
| `crates/` | The Rust core (digests, seqcol, operations, the recipe compiler) and its Python and wasm bindings |
| `python/` | The Python library and the `refbook` command |
| `js/`, `app/` | The npm package `@abdenlab/refbook` and the web app |
| `catalog/` | The pipeline that builds the catalog, with every book's recipes |
| `docs/` | The documentation site |

[Development](https://abdenlab.org/refbook/development/) covers building and testing each part.

## License

The code is released under the [MIT License](LICENSE). The catalog data is CC-BY-4.0.
