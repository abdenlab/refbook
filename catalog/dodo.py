"""The catalog's pipeline (doit). Run from catalog/, as `uv run doit ...`:

    doit                      build everything: lock the sources, build the catalog, run the checks
    doit roots                build the roots and what they need
    doit lock:GRCh38.p14      lock one source
    doit lock:EBV --update    accept a source's changed files (after checking them) and rewrite its lock
    doit fetch:EBV            download one source into raw/ (never run unless asked)
    doit list                 every task; `doit info roots` why a task would run

Each task calls functions of refbook_pipeline; this file only declares what each reads and writes. doit reruns a
task when one of its file_dep's MD5 changes (the code it runs included), and keeps its state in output/.doit.db.
A task that reads a source runs after that source's lock, so a file that changed refuses before anything is built
from it.

The build: output/build/books/<book>/ for what is built per book, output/build/catalog/ for the shared catalog
(one directory per task, written whole or not at all).
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from refbook_pipeline import (
    Refused,
    aliases,
    books,
    checks,
    editions,
    engine,
    export,
    external,
    layers,
    layout,
    locks,
    members,
    observe,
    roots,
    sources,
)

RAW, BUILD = layout.raw_dir(), layout.build_dir()
BUILD.mkdir(parents=True, exist_ok=True)  # doit keeps its state beside it, and doesn't make the directory
CATALOG = BUILD / "catalog"
SOURCES = sources.load(layout.SOURCES)
BOOKS = books.load(layout.BOOKS, SOURCES)
# The mask layers books derive from published masked files (book.toml derived_masks): published as layer_<name>.
DERIVED = tuple(sorted({m["layer"] for b in BOOKS.values() for m in b.derived_masks}))

DOIT_CONFIG = {
    "default_tasks": ["lock", "members", "assembly_members", "roots", "external_roots", "layers", "catalog_layers",
                      "observe", "reproduce", "editions", "catalog_editions", "aliases", "index", "check_gaps",
                      "check_roots", "check_materialize"],
    "dep_file": str(BUILD.parent / ".doit.db"),
    "verbosity": 2,
}


def code(*modules: str) -> list:
    """The code a task runs, as file_dep: doit tracks files, not the functions an action calls."""
    names = ("__init__", "layout", "sources", "books", *modules)
    return [layout.PIPELINE / "refbook_pipeline" / f"{m}.py" for m in names] + [layout.SOURCES]


def call(f, *args, **kwargs):
    """A doit action calling f: doit takes None, True, a str or a dict back (False fails the task), so the
    result is printed instead. An exception (Refused) fails the task and every task that needs it."""
    def action():
        result = f(*args, **kwargs)
        if result is not None:
            print(result)
    return action


def lock_path(name: str):
    return layout.LOCKS / f"{name}.lock"


def reads(srcs) -> dict:
    """What a task that reads these sources declares: their locks as file_dep, their lock tasks first."""
    return {"file_dep": [lock_path(s.name) for s in srcs], "task_dep": [f"lock:{s.name}" for s in srcs]}


def task_fetch():
    """Download a source into raw/ (only when asked: `doit fetch:<source>`)."""
    for name, src in SOURCES.items():
        yield {"name": name, "actions": [call(sources.fetch, src, RAW)], "uptodate": [False], "verbosity": 2}


def task_lock():
    """Lock a source: its files against its publisher's checksums and its lock (see refbook_pipeline/locks.py)."""
    for name, src in SOURCES.items():
        rels, missing = sources.files(src, RAW)

        def action(update, name=name, rels=rels, missing=missing, src=src):
            print(locks.lock(name, RAW, rels, missing, lock_path(name), update=update, checksums=src.checksums))

        yield {"name": name, "actions": [action],
               "params": [{"name": "update", "long": "update", "type": bool, "default": False,
                           "help": "accept new, missing and changed files and rewrite the lock"}],
               "file_dep": [RAW / r for r in rels] + [RAW / c for c in src.checksums] + code("locks"),
               "targets": [lock_path(name)]}


def task_members():
    """A book's assembly members, from the reports of its NCBI assemblies (add-ons included)."""
    for book in BOOKS.values():
        srcs = [SOURCES[n] for n in book.sources if sources.reports(SOURCES[n])]
        reports = [RAW / r for s in srcs for r in sources.reports(s)]
        out = BUILD / "books" / book.name / "members"

        order = books.release_order(book, SOURCES, RAW)

        def action(book=book, reports=reports, srcs=srcs, out=out, order=order):
            with layout.output(out) as tmp:
                pq.write_table(members.members(book.name, reports, order), tmp / "assembly_members.parquet",
                               compression="zstd")
                layout.record_inputs(tmp, [lock_path(s.name) for s in srcs])

        dep = reads(srcs)
        yield {"name": book.name, "actions": [action], "task_dep": dep["task_dep"],
               "file_dep": reports + dep["file_dep"] + code("members"),
               "targets": [out / "assembly_members.parquet", out / "inputs.json"]}


def task_assembly_members():
    """The catalog's assembly_members: every book's, in book order; and books.parquet: each book's assembly, its
    releases (p0 first; a member's `release` is its place here) and those with no assembly structure published."""
    parts = [BUILD / "books" / b / "members" / "assembly_members.parquet" for b in BOOKS]
    out = CATALOG / "members"
    rows = [{"book": b.name, "assembly": b.assembly,
             "releases": [r.name for r in books.releases(b, SOURCES, RAW)],
             "releases_without_structure": [r.name for r in books.releases(b, SOURCES, RAW) if r.structure is None]}
            for b in BOOKS.values()]

    def action():
        with layout.output(out) as tmp:
            pq.write_table(pa.concat_tables([pq.read_table(p) for p in parts]), tmp / "assembly_members.parquet",
                           compression="zstd")
            pq.write_table(pa.Table.from_pylist(rows), tmp / "books.parquet", compression="zstd")
    return {"actions": [action], "file_dep": parts + code("members") + [layout.BOOKS / b / "book.toml" for b in BOOKS],
            "targets": [out / "assembly_members.parquet", out / "books.parquet"]}


def task_roots():
    """Every root once, from the FASTA files the books' sources declare (see refbook_pipeline/roots.py)."""
    srcs = [s for s in books.sources_of(BOOKS, SOURCES) if s.sequences or s.loose_roots or s.minted_roots]
    table = CATALOG / "members" / "assembly_members.parquet"
    fastas = [(RAW / p, sources.url_of(p)) for s in srcs for p in s.sequences]
    loose = [(acc, RAW / record) for s in srcs for acc, record in s.loose_roots]
    minted = [m for s in srcs for m in s.minted_roots]
    renames = {RAW / p: {m["name"]: m["root_id"] for m in s.minted_roots} for s in srcs if s.minted_roots
               for p in s.sequences}
    out = CATALOG / "roots"

    def action():
        expected = members.lengths(pq.read_table(table))
        for acc, record in loose:
            if acc in expected:
                raise Refused(f"{acc} is declared a loose root, but an assembly report lists it")
            expected[acc] = roots.genbank_length(record)
        for m in minted:
            if m["root_id"] in expected:
                raise Refused(f"{m['root_id']}: minted twice, or also an accession")
            expected[m["root_id"]] = sources.fai_length(RAW / m["fai"], m["name"])
        with layout.output(out) as tmp:
            print(roots.build(expected, fastas, tmp, minted=renames))
            layout.record_inputs(tmp, [lock_path(s.name) for s in srcs])

    dep = reads(srcs)
    names = ["roots", "root_blocks", "layer_softmask_ncbi", "layer_n_runs", "layer_iupac"]
    return {"actions": [action], "task_dep": dep["task_dep"],
            "file_dep": [table] + [p for p, _ in fastas] + [r for _, r in loose] + [RAW / m["fai"] for m in minted]
                        + dep["file_dep"] + code("roots", "members"),
            "targets": [out / f"{n}.parquet" for n in names] + [out / "inputs.json"]}


def task_observe():
    """What each target (a published file a recipe reproduces) was found to contain, per sequence: from its FASTA
    (digests computed) or its .dict (MD5s as published), with the locked file's provenance (observe.py)."""
    for book in BOOKS.values():
        srcs = [SOURCES[n] for n in book.sources]
        owner = {rel: s for s in srcs for rel in sources.files(s, RAW)[0]}
        for r in books.recipes(layout.BOOKS, book.name):
            rel = books.target_of(r)
            if rel not in owner:
                raise Refused(f"{r['target']}: {rel} is in none of {book.name}'s sources")
            src, out = owner[rel], BUILD / "books" / book.name / "observed" / f"{r['target']}.parquet"

            def action(rel=rel, src=src, out=out, target=r["target"]):
                entry = locks.read(lock_path(src.name))[rel]
                # The lock task has just checked the bytes (it runs first); this guards the size only.
                if (RAW / rel).stat().st_size != int(entry["bytes"]):
                    raise Refused(f"{target}: {rel} does not match its lock")
                table = observe.observe(RAW / rel)
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_name(f".{out.name}.partial")
                pq.write_table(table.replace_schema_metadata(observe.provenance(entry)), tmp, compression="zstd")
                tmp.replace(out)
                print(f"{target}: {table.num_rows} sequences from {(RAW / rel).name}")

            yield {"name": r["target"], "actions": [action], "task_dep": [f"lock:{src.name}"],
                   "file_dep": [RAW / rel, lock_path(src.name)] + code("observe"), "targets": [out]}


def task_external_roots():
    """External roots: the sources that declare them (see refbook_pipeline/external.py)."""
    srcs = [s for s in books.sources_of(BOOKS, SOURCES) if s.external]
    out = CATALOG / "external"

    def action():
        rows = []
        for s in srcs:
            if s.external["format"] != "imgt_hla":
                raise Refused(f"{s.name}: no reader for external format {s.external['format']!r}")
            files = [f for f in sources.files(s, RAW)[0] if f.endswith(s.github_tree.get("suffix", ""))
                     and f.startswith(f"{s.base}/{s.github_tree.get('prefix', '')}")]
            rows += external.imgt_hla(s.external["collection"], s.external["prefix"],
                                      [(RAW / f, sources.url_of(f)) for f in files])
        with layout.output(out) as tmp:
            pq.write_table(external.table(rows), tmp / "roots_external.parquet", compression="zstd")
            layout.record_inputs(tmp, [lock_path(s.name) for s in srcs])
            print(f"{len(rows)} external roots")

    dep = reads(srcs)
    return {"actions": [action], "task_dep": dep["task_dep"],
            "file_dep": [RAW / f for s in srcs for f in sources.files(s, RAW)[0]] + dep["file_dep"] + code("external"),
            "targets": [out / "roots_external.parquet", out / "inputs.json"]}


def catalog_tables(recipes: list[dict]) -> dict:
    """The catalog tables the recipe engine reads, by name (engine.load_tables)."""
    return engine.table_paths(export.published(CATALOG, DERIVED), recipes)


def task_reproduce():
    """Apply a book's recipes and check each against its target's observation (order-free, by name: the same
    names, lengths and digests). Writes each target's sequences in its own order; writes nothing unless every
    target reproduces."""
    for book in BOOKS.values():
        recipes = books.recipes(layout.BOOKS, book.name)
        paths = catalog_tables(recipes)
        observed = BUILD / "books" / book.name / "observed"
        out = BUILD / "books" / book.name / "reproduced"

        def action(recipes=recipes, paths=paths, observed=observed, out=out, book=book.name):
            t = engine.load_tables(paths, recipes, book)
            rows, failed = [], []
            for recipe in recipes:
                got = engine.run(recipe, t)
                seen = pq.read_table(observed / f"{recipe['target']}.parquet").to_pylist()
                errs = engine.compare(got, seen)
                print(f"{recipe['target']}: {len(got)} sequences, "
                      f"{'REPRODUCES' if not errs else f'{len(errs)} MISMATCHES: ' + '; '.join(errs[:5])}")
                (failed.append(recipe["target"]) if errs else rows.extend(engine.in_observed_order(got, seen)))
            if failed:
                raise Refused(f"not reproduced: {failed}")
            with layout.output(out) as tmp:
                pq.write_table(pa.Table.from_pylist(rows), tmp / "reproduced.parquet", compression="zstd")

        recipe_files = sorted((layout.BOOKS / book.name / "recipes").glob("*.json"))
        yield {"name": book.name, "actions": [action],
               "file_dep": list(paths.values()) + [observed / f"{r['target']}.parquet" for r in recipes]
                           + recipe_files + code("engine"),
               "targets": [out / "reproduced.parquet"]}


EDITION_TABLES = ["editions", "manifests", "targets", "target_sequences"]


def task_editions():
    """A book's editions, manifests, targets and their seqcol collections (see refbook_pipeline/editions.py)."""
    for book in BOOKS.values():
        recipes = books.recipes(layout.BOOKS, book.name)
        paths = catalog_tables(recipes)
        here = BUILD / "books" / book.name
        labels = layout.BOOKS / book.name / "editions.json"
        loose = {acc: s.name for s in (SOURCES[n] for n in book.sources) for acc, _ in s.loose_roots}
        out = here / "editions"

        def action(book=book, recipes=recipes, paths=paths, here=here, labels=labels, loose=loose, out=out):
            t = engine.load_tables(paths, recipes, book.name)
            prov = {r["target"]: observe.read_provenance(here / "observed" / f"{r['target']}.parquet") for r in recipes}
            releases = {layers.Release.of(RAW, SOURCES[n].base).name for n in book.releases}
            with layout.output(out) as tmp:
                tables = editions.build(book.assembly, recipes, json.loads(labels.read_text())["editions"],
                                        pq.read_table(here / "reproduced" / "reproduced.parquet").to_pylist(),
                                        t, prov, releases, loose, tmp)
                for name, rows in tables.items():
                    pq.write_table(pa.Table.from_pylist(rows), tmp / f"{name}.parquet", compression="zstd")
                print(f"{len(tables['editions'])} editions, {len(tables['targets'])} targets")

        yield {"name": book.name, "actions": [action],
               "file_dep": list(paths.values()) + [here / "reproduced" / "reproduced.parquet", labels]
                           + [here / "observed" / f"{r['target']}.parquet" for r in recipes]
                           + code("editions", "engine", "observe", "layers"),
               "targets": [out / f"{n}.parquet" for n in EDITION_TABLES]}


def task_catalog_editions():
    """The catalog's editions, manifests, targets and collections, every book's (editions with their book), and
    the sequence store made from every manifest and every root (editions.sequence_store)."""
    out = CATALOG / "editions"
    parts = {b: BUILD / "books" / b / "editions" for b in BOOKS}
    roots_paths = [CATALOG / "roots" / "roots.parquet", CATALOG / "external" / "roots_external.parquet"]

    def action():
        with layout.output(out) as tmp:
            combined = {}
            for name in EDITION_TABLES:
                tables = [pq.read_table(d / f"{name}.parquet") for d in parts.values()]
                if name == "editions":
                    tables = [t.add_column(0, "book", pa.array([b] * t.num_rows, pa.string()))
                              for b, t in zip(parts, tables)]
                # Permissive: a column a book leaves empty (no edition excludes anything) has no element type.
                combined[name] = pa.concat_tables(tables, promote_options="permissive")
                pq.write_table(combined[name], tmp / f"{name}.parquet", compression="zstd")
            labels = combined["editions"]["edition"].to_pylist()
            if len(labels) != len(set(labels)):
                raise Refused(f"an edition label is used in two books: {sorted({x for x in labels if labels.count(x) > 1})}")
            cols = ["root_id", "length", "md5", "sha512t24u"]
            roots = {r["root_id"]: r for p in roots_paths for r in pq.read_table(p, columns=cols).to_pylist()}
            book_of = dict(zip(combined["editions"]["edition"].to_pylist(), combined["editions"]["book"].to_pylist()))
            seqs, ders = editions.sequence_store(combined["manifests"].to_pylist(), roots, book_of)
            pq.write_table(pa.Table.from_pylist(seqs), tmp / "sequences.parquet", compression="zstd")
            pq.write_table(pa.Table.from_pylist(ders), tmp / "derivations.parquet", compression="zstd")
            (tmp / "collections").mkdir()
            for d in parts.values():
                for f in (d / "collections").iterdir():
                    dest = tmp / "collections" / f.name
                    if dest.exists() and dest.read_bytes() != f.read_bytes():
                        raise Refused(f"collection {f.name}: two books wrote it differently")
                    dest.write_bytes(f.read_bytes())

    return {"actions": [action],
            "file_dep": [d / f"{n}.parquet" for d in parts.values() for n in EDITION_TABLES] + roots_paths
                        + code("editions"),
            "targets": [out / f"{n}.parquet" for n in EDITION_TABLES + ["sequences", "derivations"]]}


def task_aliases():
    """Every root's names, by book where a name's meaning depends on it, and every stored sequence's refget aliases
    (see refbook_pipeline/aliases.py)."""
    out = CATALOG / "aliases"
    chromalias = {f"{d['chromalias']['source']}/{d['chromalias']['file']}":
                  RAW / SOURCES[d["chromalias"]["source"]].base / d["chromalias"]["file"]
                  for b in BOOKS.values() for d in b.aliases if "chromalias" in d}
    srcs = sorted({k.split("/", 1)[0] for k in chromalias})
    reproduced = [BUILD / "books" / b / "reproduced" / "reproduced.parquet" for b in BOOKS]
    tables = [CATALOG / "members" / "assembly_members.parquet", CATALOG / "roots" / "roots.parquet",
              CATALOG / "external" / "roots_external.parquet", CATALOG / "editions" / "manifests.parquet",
              CATALOG / "editions" / "sequences.parquet"]

    def action():
        members_all = pq.read_table(tables[0]).to_pylist()
        roots_all = set(pq.read_table(tables[1], columns=["root_id"])["root_id"].to_pylist())
        roots_all |= set(pq.read_table(tables[2], columns=["root_id"])["root_id"].to_pylist())
        rows, notes = set(), []
        for book in BOOKS.values():
            releases = {layers.Release.of(RAW, SOURCES[n].base).name for n in book.releases}
            by_target = {}
            for r in pq.read_table(BUILD / "books" / book.name / "reproduced" / "reproduced.parquet").to_pylist():
                by_target.setdefault(r["target"], []).append(r)
            got, n = aliases.book_aliases(book.name, [m for m in members_all if m["book"] == book.name], releases,
                                          list(book.aliases), by_target, chromalias, roots_all)
            rows |= got
            notes += n
        rows |= aliases.global_aliases(pq.read_table(tables[1], columns=["root_id", "source"]).to_pylist(),
                                       pq.read_table(tables[2]).to_pylist())
        seq = aliases.sequence_aliases(rows, pq.read_table(tables[3], columns=["name", "sha512t24u"]).to_pylist(),
                                       pq.read_table(tables[4], columns=["sha512t24u", "root_id", "operations"]).to_pylist())
        key = lambda r: tuple("" if x is None else x for x in r)
        with layout.output(out) as tmp:
            pq.write_table(pa.Table.from_pylist(
                [dict(zip(("book", "root_id", "namespace", "alias", "source"), r)) for r in sorted(rows, key=key)],
                schema=pa.schema([(c, pa.string()) for c in ("book", "root_id", "namespace", "alias", "source")])),
                tmp / "aliases.parquet", compression="zstd")
            pq.write_table(pa.Table.from_pylist(
                [dict(zip(("sha512t24u", "naming_authority", "alias"), r)) for r in sorted(seq)]),
                tmp / "sequence_aliases.parquet", compression="zstd")
            (tmp / "notes.json").write_text(json.dumps(notes, indent=1) + "\n")
            layout.record_inputs(tmp, [lock_path(s) for s in srcs])
            print(f"{len(rows)} aliases, {len(seq)} sequence aliases", notes)

    dep = reads([SOURCES[s] for s in srcs])
    return {"actions": [action], "task_dep": dep["task_dep"],
            "file_dep": tables + reproduced + list(chromalias.values()) + dep["file_dep"]
                        + [layout.BOOKS / b / "book.toml" for b in BOOKS] + code("aliases", "layers"),
            "targets": [out / "aliases.parquet", out / "sequence_aliases.parquet", out / "notes.json"]}


CHECKS = BUILD / "checks"
ENA_EXCEPTIONS = layout.PIPELINE / "roots_ena_exceptions.tsv"
PUBLISHED = export.published(CATALOG, DERIVED)


def task_index():
    """The build's catalog.json: every published table by its release name (refbook.Catalog opens the build)."""
    files = [p for name, p in PUBLISHED.items() if name != "collections"]
    return {"actions": [call(export.write_index, CATALOG, DERIVED)], "file_dep": files + code("export"),
            "targets": [CATALOG / "catalog.json"]}


def task_check_gaps():
    """Every run of N explained by the published AGP, and the GRC's genomic_gaps.txt agreeing (checks.py)."""
    out = CHECKS / "gaps"
    names = ["layer_agp.parquet", "layer_n_runs.parquet", "roots.parquet", "assembly_members.parquet", "books.parquet"]
    releases = [layers.Release.of(RAW, SOURCES[n].base) for b in BOOKS.values() for n in b.releases]
    gg = {r.name: r.directory / f"{r.directory.name}_genomic_gaps.txt.gz" for r in releases
          if (r.directory / f"{r.directory.name}_genomic_gaps.txt.gz").exists()}

    def action():
        t = {n: pq.read_table(PUBLISHED[n]) for n in names}
        lengths = dict(zip(t["roots.parquet"]["root_id"].to_pylist(), t["roots.parquet"]["length"].to_pylist()))
        ms = t["assembly_members.parquet"].to_pylist()
        bare = {(b["book"], r) for b in pq.read_table(PUBLISHED["books.parquet"]).to_pylist()
                for r in b["releases_without_structure"]}
        elsewhere = {m["genbank_accession"] for m in ms if (m["book"], m["assembly_name"]) not in bare}
        no_agp = {m["genbank_accession"] for m in ms if (m["book"], m["assembly_name"]) in bare} - elsewhere
        passed, details, report = checks.check_gaps(t["layer_agp.parquet"].to_pylist(),
                                                    t["layer_n_runs.parquet"].to_pylist(), lengths, ms, gg, no_agp)
        details["genomic_gaps_releases"] = sorted(gg)
        with layout.output(out) as tmp:
            (tmp / "check_gaps.tsv").write_text("root_id\tstart\tend\tkind\tgap_types\n"
                                                + "".join("\t".join(map(str, r)) + "\n" for r in report))
            checks.record(tmp, "check_gaps", passed, {n: PUBLISHED[n] for n in names}, details)
        print("PASSED" if passed else "FAILED", details)
        if not passed:
            raise Refused(f"check_gaps failed: {details['errors'][:3]}")

    return {"actions": [action], "file_dep": [PUBLISHED[n] for n in names] + list(gg.values()) + code("checks"),
            "targets": [out / "check_gaps.json", out / "check_gaps.tsv"]}


def roots_check(ena: bool):
    out = CHECKS / ("roots_ena" if ena else "roots")
    names = ["roots.parquet", "layer_hardmask_grc.parquet", "layer_par_y.parquet"]
    sets = [(b.checks["analysis_set"]["source"], b.checks["analysis_set"]["file"]) for b in BOOKS.values()
            if b.checks and "analysis_set" in b.checks]
    files = [RAW / SOURCES[s].base / f for s, f in sets]

    def action():
        roots_ = pq.read_table(PUBLISHED["roots.parquet"]).to_pylist()
        # What the analysis sets mask: the GRC hard-mask (GRCh38), and chrY's PARs (GRCh37's mask only those).
        masked = {r for n in names[1:] for r in pq.read_table(PUBLISHED[n], columns=["root_id"])["root_id"].to_pylist()}
        m5 = {}
        for f in files:
            m5.update(checks.grc_m5(f))
        lengths = checks.ena_lengths([r["md5"] for r in roots_]) if ena else None
        exceptions = checks.read_ena_exceptions(ENA_EXCEPTIONS) if ena else {}
        passed, details, rows = checks.check_roots(roots_, masked, m5, ", ".join(f.name for f in files), lengths,
                                                   exceptions)
        with layout.output(out) as tmp:
            (tmp / "verify_roots.tsv").write_text("root_id\tlength\tmd5\tena\tgrc_analysis_set\n"
                                                  + "".join("\t".join(map(str, r)) + "\n" for r in rows))
            checks.record(tmp, "check_roots", passed, {n: PUBLISHED[n] for n in names}, details)
        print("PASSED" if passed else "FAILED", details["counts"])
        if not passed:
            raise Refused(f"check_roots failed: {details['failed'][:5]}")

    exc = [ENA_EXCEPTIONS] if ena and ENA_EXCEPTIONS.exists() else []
    return {"actions": [action], "file_dep": [PUBLISHED[n] for n in names] + files + exc + code("checks"),
            "targets": [out / "check_roots.json", out / "verify_roots.tsv"]}


def task_check_roots():
    """The roots' MD5s against the GRC analysis set's deflines (ENA not consulted: see check_roots_ena)."""
    return roots_check(ena=False)


def task_check_roots_ena():
    """check_roots, consulting ENA's refget server too (3,097 requests; a release needs it; never run unless asked,
    or by an export)."""
    return roots_check(ena=True)


def task_check_materialize():
    """From the bases, through the library: every derivation, every collection's digest, one stream (checks.py)."""
    out = CHECKS / "materialize"
    names = ["sequences.parquet", "derivations.parquet", "editions.parquet", "manifests.parquet", "targets.parquet",
             "target_sequences.parquet", "roots.parquet", "roots_external.parquet", "root_blocks.parquet",
             "layer_hardmask_grc.parquet", "collections"]
    stream = [b.checks["stream"] for b in BOOKS.values() if b.checks and "stream" in b.checks]

    def action():
        passed, details, log = checks.check_materialize(CATALOG, stream)
        with layout.output(out) as tmp:
            checks.record(tmp, "check_materialize", passed, {n: PUBLISHED[n] for n in names}, details)
        print("PASSED" if passed else "FAILED", *log, sep="\n  ")
        if not passed:
            raise Refused(f"check_materialize failed: {details['errors'][:3]}")

    return {"actions": [action], "task_dep": ["index"],
            "file_dep": [PUBLISHED[n] for n in names if n != "collections"] + [CATALOG / "catalog.json"]
                        + [layout.BOOKS / b / "book.toml" for b in BOOKS] + code("checks"),
            "targets": [out / "check_materialize.json"]}


def task_export():
    """A release: `doit export --version 0.2.0 --out DIR` (a development export: add --development, which accepts a
    root check without ENA). Never run unless asked. See refbook_pipeline/export.py."""
    def action(version, out, development):
        if not version or not out:
            raise Refused("export needs --version and --out")
        roots_json = CHECKS / ("roots" if development and not (CHECKS / "roots_ena").exists() else "roots_ena")
        checks_ = {"check_gaps": CHECKS / "gaps" / "check_gaps.json", "check_roots": roots_json / "check_roots.json",
                   "check_materialize": CHECKS / "materialize" / "check_materialize.json"}
        locks_ = sorted(layout.LOCKS.glob("*.lock")) + sorted(layout.LOCKS.glob("*.exceptions.tsv"))
        evidence_extra = [(ENA_EXCEPTIONS, f"evidence/{ENA_EXCEPTIONS.name}")] if ENA_EXCEPTIONS.exists() else []
        evidence = [(p, f"evidence/observed/{p.name}") for b in BOOKS for p in
                    sorted((BUILD / "books" / b / "observed").glob("*.parquet"))]
        evidence += [(roots_json / "verify_roots.tsv", "evidence/verify_roots.tsv"),
                     (CHECKS / "gaps" / "check_gaps.tsv", "evidence/check_gaps.tsv")]
        evidence += [(p, f"evidence/{p.name}") for p in checks_.values()]
        evidence += [(p, f"evidence/locks/{p.name}") for p in locks_] + evidence_extra
        books_ = {b.name: (b.assembly, [layers.Release.of(RAW, SOURCES[n].base).name for n in b.releases])
                  for b in BOOKS.values()}
        text = export.card(layout.PIPELINE / "catalog_card.md", CATALOG, version, books_)
        print(export.export(CATALOG, Path(out), version, checks_, evidence,
                            sorted(layout.LOCKS.glob("*.lock")), text, development, DERIVED))

    return {"actions": [action], "uptodate": [False], "verbosity": 2,
            "task_dep": ["check_gaps", "check_roots", "check_materialize"],
            "params": [{"name": "version", "long": "version", "default": "", "help": "the release's version"},
                       {"name": "out", "long": "out", "default": "", "help": "the directory to create"},
                       {"name": "development", "long": "development", "type": bool, "default": False,
                        "help": "accept a root check that didn't consult ENA (not a release)"}]}


LAYERS = ["layer_agp", "layer_regions", "layer_placements", "layer_par_y", "layer_padding", "layer_hardmask_grc"]
# Layers whose rows mean something only within a book: numbered by release, or (padding) a placement on a parent
# that is the book's (GRCh37's novel patches are GRCh38's alts, on other chromosome versions).
BOOK_KEYED = ("layer_regions", "layer_placements", "layer_padding")


def task_layers():
    """A book's layers, from its releases' and add-ons' assembly structure (see refbook_pipeline/layers.py)."""
    for book in BOOKS.values():
        srcs = [SOURCES[n] for n in book.releases + book.addons]
        if book.structure_archive:
            srcs.append(SOURCES[book.structure_archive])
        rels = books.releases(book, SOURCES, RAW)
        dirs = [r.structure for r in rels if r.structure] + [layers.structure_of(RAW / SOURCES[n].base)
                                                            for n in book.addons]
        bare = {r.name for r in rels if r.structure is None}
        mask = book.hardmask_grc
        mask_src = [SOURCES[mask["source"]]] if mask else []
        mask_file = RAW / SOURCES[mask["source"]].base / mask["file"] if mask else None
        table = BUILD / "books" / book.name / "members" / "assembly_members.parquet"
        lengths = CATALOG / "roots" / "roots.parquet"
        out = BUILD / "books" / book.name / "layers"
        bed_srcs = [SOURCES[n] for n in book.sources if any("agp_bed" in m for m in SOURCES[n].minted_roots)]
        beds = [m for s in bed_srcs for m in s.minted_roots if "agp_bed" in m]
        derived = [(m, RAW / SOURCES[m["source"]].base / m["file"]) for m in book.derived_masks]
        derived_srcs = list({m["source"]: SOURCES[m["source"]] for m, _ in derived}.values())
        blocks = CATALOG / "roots" / "root_blocks.parquet"

        def action(book=book, rels=rels, dirs=dirs, mask=mask, mask_file=mask_file,
                   srcs=srcs + mask_src + bed_srcs + derived_srcs, table=table, lengths=lengths, out=out, beds=beds,
                   bare=bare, derived=derived, blocks=blocks):
            ms = pq.read_table(table).to_pylist()
            r = pq.read_table(lengths, columns=["root_id", "length"])
            length = dict(zip(r["root_id"].to_pylist(), r["length"].to_pylist()))
            with layout.output(out) as tmp:
                extra = [r for m in beds for r in layers.build_agp_bed(
                    RAW / m["agp_bed"], sources.url_of(m["agp_bed"]), m["name"], m["root_id"], length[m["root_id"]])]
                agp_notes = []
                # An AGP for every member of a release whose structure is published (or of an add-on).
                structured = {m["genbank_accession"] for m in ms if m["assembly_name"] not in bare}
                agp = layers.build_agp(RAW, dirs, structured, extra, agp_notes,
                                       {root for _, root in book.agp_revisions})
                regions, spans = layers.build_regions(rels, ms, set(book.region_quirks))
                placements, notes = layers.build_placements(rels, ms, length, spans)
                notes = agp_notes + notes
                tables = {"layer_agp": agp, "layer_regions": regions, "layer_placements": placements,
                          "layer_par_y": layers.build_par_y(regions, ms),
                          "layer_padding": layers.build_padding(placements, length)}
                if mask:
                    tables["layer_hardmask_grc"] = layers.build_hardmask_grc(mask_file, length, regions,
                                                                           mask["par_root"])
                    hm = {(r["start"], r["end"]) for r in tables["layer_hardmask_grc"].to_pylist()
                          if r["root_id"] == mask["par_root"]}
                    par = {(r["start"], r["end"]) for r in tables["layer_par_y"].to_pylist()
                           if r["root_id"] == mask["par_root"]}
                    if hm != par:
                        raise Refused(f"layer_par_y's spans on {mask['par_root']} {sorted(par)} != the GRC "
                                      f"hard-mask's {sorted(hm)}")
                # Derived masks: chromosome names in the file -> roots, by the latest release's UCSC names.
                ucsc = {m["ucsc_name"]: m["genbank_accession"] for m in ms
                        if m["assembly_name"] == rels[-1].name and m["ucsc_name"]}
                for m, path in derived:
                    missing = [c for c in m["chromosomes"] if c not in ucsc]
                    if missing:
                        raise Refused(f"derived mask {m['layer']}: no root named {missing} in {rels[-1].name}")
                    tables[f"layer_{m['layer']}"] = layers.build_derived_mask(
                        path, sources.url_of(path.relative_to(RAW).as_posix()), {c: ucsc[c] for c in m["chromosomes"]},
                        lambda root: engine.root_bases(blocks, root))
                for name, t in tables.items():
                    pq.write_table(t, tmp / f"{name}.parquet", compression="zstd")
                (tmp / "notes.json").write_text(json.dumps(notes, indent=1) + "\n")
                layout.record_inputs(tmp, [lock_path(s.name) for s in srcs])
                print({name: t.num_rows for name, t in tables.items()}, notes)

        files = [RAW / f for s in srcs for f in sources.files(s, RAW)[0]] + ([mask_file] if mask else [])
        files += [RAW / m["agp_bed"] for m in beds] + [path for _, path in derived]
        dep = reads(srcs + mask_src + bed_srcs + derived_srcs)
        yield {"name": book.name, "actions": [action], "task_dep": dep["task_dep"],
               "file_dep": [table, lengths] + files + dep["file_dep"] + ([blocks] if derived else [])
                           + code("layers", "members", "engine"),
               "targets": [out / f"{n}.parquet" for n in LAYERS[:5] + (LAYERS[5:] if mask else [])]
                          + [out / f"layer_{m['layer']}.parquet" for m, _ in derived]
                          + [out / "notes.json", out / "inputs.json"]}


def task_catalog_layers():
    """The catalog's layers: every book's. A root-keyed layer (AGP, hard-mask) has each root once, the same in
    every book that has it, and taken from the latest assembly's book (books newest first: grch38 before grch37).
    An AGP may differ between books only where it was found (source, object_rank: GL000194.1 is chr4's in GRCh37,
    chr14's in GRCh38) and in annotation (layers.agp_parts). The book-keyed layers (BOOK_KEYED) carry their book."""
    out = CATALOG / "layers"
    parts = {b: BUILD / "books" / b / "layers" for b in sorted(BOOKS, reverse=True)}

    def same(name, a, b):
        if name != "layer_agp":
            return a == b
        layout_ = [{k: v for k, v in r.items() if k not in ("source", "object_rank", "component_type", "gap_type",
                                                             "linkage", "linkage_evidence")} for r in a]
        return layout_ == [{k: v for k, v in r.items() if k not in ("source", "object_rank", "component_type",
                                                                    "gap_type", "linkage", "linkage_evidence")}
                           for r in b] and [r["component_id"] is None for r in a] == [r["component_id"] is None
                                                                                      for r in b]

    def action():
        with layout.output(out) as tmp:
            for name in LAYERS + [f"layer_{n}" for n in DERIVED]:
                found = [(b, d / f"{name}.parquet") for b, d in parts.items() if (d / f"{name}.parquet").exists()]
                tables = [pq.read_table(p) for _, p in found]
                if name in BOOK_KEYED:
                    tables = [t.add_column(0, "book", pa.array([b] * t.num_rows, pa.string()))
                              for (b, _), t in sorted(zip(found, tables))]
                    # Permissive: a book with no rows (T2T-CHM13 places nothing) has untyped columns.
                    combined = pa.concat_tables(tables, promote_options="permissive")
                else:
                    combined, seen = [], {}
                    for t in tables:
                        for root, rows in sorted(_by_root(t).items()):
                            if root in seen and not same(name, seen[root], rows):
                                raise Refused(f"{name}: {root} differs between books")
                            if root not in seen:
                                seen[root] = rows
                                combined += rows
                    combined.sort(key=lambda r: r["root_id"])  # stable: each root's rows keep their order
                    # One schema for every book's: a column a book leaves empty (T2T-CHM13's AGP has no gaps) has
                    # no type of its own.
                    schema = pa.unify_schemas([t.schema for t in tables], promote_options="permissive")
                    combined = pa.Table.from_pylist(combined, schema=schema)
                pq.write_table(combined, tmp / f"{name}.parquet", compression="zstd")

    deps = [d / f"{n}.parquet" for b, d in parts.items() for n in LAYERS
            if n != "layer_hardmask_grc" or BOOKS[b].hardmask_grc]
    deps += [d / f"layer_{m['layer']}.parquet" for b, d in parts.items() for m in BOOKS[b].derived_masks]
    return {"actions": [action], "file_dep": deps + code("layers"),
            "targets": [out / f"{n}.parquet" for n in LAYERS] + [out / f"layer_{n}.parquet" for n in DERIVED]}


def _by_root(t: pa.Table) -> dict[str, list[dict]]:
    out = {}
    for row in t.to_pylist():
        out.setdefault(row["root_id"], []).append(row)
    return out
