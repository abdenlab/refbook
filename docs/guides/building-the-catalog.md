# Building the catalog

The pipeline in `catalog/` builds one catalog from every book's original
downloads. It needs about 15 GB of downloads, and it runs on one machine. It
is a set of [doit](https://pydoit.org) tasks (`catalog/dodo.py`), each calling
plain functions in `catalog/refbook_pipeline/`; doit reruns a task only when
the bytes of something it reads, its code included, have changed. Each
module's docstring says what it reads, writes and checks.

```bash
cd catalog
mkdir -p output && ln -s /path/to/a/mirror output/raw   # optional: share the downloads between checkouts
uv run doit fetch:GRCh38.p14         # download a source into output/raw/ (each is fetched only when asked)
uv run doit                          # lock every source, build the catalog, run the checks
uv run doit list                     # every task; `uv run doit info <task>` says why one would run
```

## What it is built from

What the catalog is built from is data:

- **Sources.** `catalog/sources.toml` declares every source: a set of files
  from one publisher (an NCBI assembly directory, files on a host, GenBank
  records, a GitHub tree), what it's used for (an input, a reproduction target,
  or both), which of its files hold sequences, and any external collection.
- **Books.** `catalog/books/<book>/` holds a [book](../concepts/model.md#books):
  `book.toml` declares the assembly, its releases and add-ons, and what is
  particular to it (accepted disagreements between assembly reports, where its
  hard-masks are defined or read from, where names come from beyond the
  assembly reports, the checks' choices); `recipes/` holds the recipes that
  reproduce its published files, one file per publisher; `editions.json`
  gives the editions their labels.
- **Locks.** `catalog/locks/<source>.lock` pins each source to exact bytes:
  every file's size, sha256, Last-Modified and URL. Locking checks each file
  against its publisher's checksum list, where there is one, and against the
  lock. Anything new or changed is refused until you accept it with
  `uv run doit lock:<source> --update`. On the first run there is no lock, so
  the files are trusted and the lock is written. Publisher checksums that
  disagree with what the publisher serves are listed, with the reason, in
  `<source>.exceptions.tsv` beside the lock. A task reads a source only after
  its lock passes, and records the locks it read.

## What it builds

The build goes to `catalog/output/build/` (gitignored; `REFBOOK_RAW` and
`REFBOOK_BUILD` override the paths):

- `books/<book>/`: what is built per book;
- `catalog/`: the shared catalog, one directory per task, each written whole or
  not at all, with `catalog/catalog.json` indexing it, so
  `Catalog("catalog/output/build/catalog")` opens a build directly;
- `checks/`: the checks' results.

The checks run on the tables the catalog publishes, and record the hash of
each.

## Releasing

```bash
uv run doit check_roots_ena                     # check every root against ENA's refget server (one request per root)
uv run doit export --version 0.2.0 --out DIR    # write the release
```

`export` refuses unless every check passed on exactly the files it ships,
every task read the current locks, and the root check consulted ENA (a
development export, `--development`, accepts a root check without ENA).
