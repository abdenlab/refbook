# Development

## Repository layout

| Path | Contents |
| --- | --- |
| `crates/` | The Rust crates: `refbook-core` (refget digests and canonicalization, seqcol, nucleotide operations, the recipe compiler, sequence identification; no I/O), and its bindings, `refbook-py` (pyo3, built by maturin as `refbook._core`) and `refbook-wasm` (wasm-bindgen, for `js/`) |
| `python/` | The Python package: `refbook/` (the library and the `refbook` command), `tests/` (with real ENCODE, gnomAD and GIAB headers as fixtures) |
| `js/` | The npm package `@abdenlab/refbook`: the TypeScript front end over the core's wasm bindings |
| `app/` | The web app at [refbook.abdenlab.org](https://refbook.abdenlab.org/) (Svelte 5, Vite, TypeScript): the catalog of books, editions and sequences; Identify (identify a pasted header, compare it with an edition, get aliases); and the Editor (design an edition from a book's choices, with its digests and exports). Everything is computed in the browser by the core, from the catalog on Hugging Face |
| `catalog/` | The pipeline that builds the catalog: `dodo.py` (the doit tasks), `refbook_pipeline/` (the functions they call), `sources.toml`, `locks/`, `books/<book>/`, `tests/`. See [Building the catalog](guides/building-the-catalog.md) |
| `docs/` | This site (Zensical; `zensical.toml` at the root) |

## Python and Rust

The root `pyproject.toml` is a uv workspace of the library (`python/`) and the
pipeline (`catalog/`). `uv sync` builds the core into the library with
maturin, so it needs a Rust toolchain.

```bash
uv sync
uv run pytest      # python/tests (the library) and catalog/tests (the pipeline)
cargo test         # the Rust crates
```

Tests that need a catalog read `$REFBOOK_CATALOG` (default: the build in
`catalog/output/build/catalog`; a release works too) and are skipped without
one. The wasm cross-check (`catalog/tests/test_wasm.py`) is skipped until
`js/` is built.

## JavaScript and the app

`js/` and `app/` are a pnpm workspace. Building the core's wasm bindings needs
the `wasm32-unknown-unknown` target and `wasm-bindgen-cli` at the version in
`Cargo.lock`.

```bash
pnpm install
pnpm build         # js/, then app/
pnpm test
pnpm dev           # the app on a Vite dev server
```

The dev server reads the local build in `catalog/output/build/catalog` at
`/catalog/`; `VITE_CATALOG_URL` at build time, or `?catalog=` on the page,
points the app at another catalog. The app is deployed from `main` by GitHub
Actions, as a Cloudflare Worker serving static assets (`app/wrangler.jsonc`).

## These docs

```bash
uvx --with mkdocstrings-python zensical serve           # preview, with live reload
uvx --with mkdocstrings-python zensical build --strict  # as CI builds it, into site/
```

The site is built and deployed to GitHub Pages by `.github/workflows/docs.yml`
whenever `main` changes the docs, `zensical.toml` or the Python package's
docstrings.
