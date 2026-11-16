# refbook

<span>
A <b>catalog</b> of human reference genome editions.
And <b>tools</b> to identify, fetch and reconstruct them.
</span>

Refbook describes every published genome assembly sequence collection using a *recipe* applied to *root sequences*, the original sequences as their submitters deposited them. 

The set of all collections made from one genome assembly and its releases is called a *book*. The reproduced published versions reduce to a smaller number of *editions*: distinct sets of named sequences, whatever their order. 

## The catalog

<b>The <a href="https://refbook.abdenlab.org/" target="_blank" rel="noopener noreferrer">refbook web app</a></b> is the main entry point to the catalog. Browse the books and their editions, look up any sequence, identify a pasted header, and design your own edition in the Editor.

**The [hosted catalog database](https://huggingface.co/datasets/abdenlab/refbook)** is nothing but a set of Parquet tables on Hugging Face, readable with DuckDB, Polars or pyarrow, even without this library.

You can also **[build your own catalog](guides/building-the-catalog.md)** using the pipeline that reproduces every published file.

## The Python package + CLI

### Install

```sh
pip install refbook                 # the library and the `refbook`
pip install "refbook[datafusion]"   # for faster fetches from a local catalog
```

### What you can do

- Identify a sequence or edition from a BAM, CRAM, VCF, `.dict`, `.fai` header or FASTA.
- Trace a sequence to (i) its root, (ii) the operations that made it, (iii) every edition that uses it, and (iv) how it is named.
- Compare editions sequence by sequence, and get the aliases that rename one's sequences into the other's names.
- Materialize any cataloged sequence or edition as an Arrow stream.

Other features:

- A full [refget API server](guides/refget-server.md): Sequences v2 and Sequence Collections v1.
- [Decode CRAMs](guides/cram.md): Supply modified sequences that public MD5 servers don't provide.

### For more information

- The [Python guide](guides/python.md)
- The [API reference](reference/python.md)
- The [CLI reference](reference/command-line.md)

## The catalog builder

The repository's [uv](https://docs.astral.sh/uv/) workspace contains the pipeline that builds the catalog (`catalog/`) and the library (`python/`). 

```sh
git clone https://github.com/abdenlab/refbook
cd refbook
uv sync      # the library, the `refbook` command, the pipeline and dev tools
uv run refbook --help
```

See [guide](guides/building-the-catalog.md) for more details.
