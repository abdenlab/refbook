"""The catalog's pipeline (doit). Run from pipeline/:

    doit                      build everything (locks, members, roots), and compare it with the first pipeline
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

import pyarrow as pa
import pyarrow.parquet as pq
from refbook_pipeline import (
    Refused,
    aliases,
    books,
    editions,
    engine,
    external,
    layers,
    layout,
    locks,
    members,
    observe,
    roots,
    sources,
    v1,
)

RAW, BUILD = layout.raw_dir(), layout.build_dir()
BUILD.mkdir(parents=True, exist_ok=True)  # doit keeps its state beside it, and doesn't make the directory
CATALOG = BUILD / "catalog"
SOURCES = sources.load(layout.SOURCES)
BOOKS = books.load(layout.BOOKS, SOURCES)

DOIT_CONFIG = {
    "default_tasks": ["lock", "members", "assembly_members", "roots", "external_roots", "layers", "catalog_layers",
                      "observe", "reproduce", "editions", "catalog_editions", "aliases", "compare_v1"],
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

        def action(book=book, reports=reports, srcs=srcs, out=out):
            with layout.output(out) as tmp:
                pq.write_table(members.members(book.name, reports), tmp / "assembly_members.parquet",
                               compression="zstd")
                layout.record_inputs(tmp, [lock_path(s.name) for s in srcs])

        dep = reads(srcs)
        yield {"name": book.name, "actions": [action], "task_dep": dep["task_dep"],
               "file_dep": reports + dep["file_dep"] + code("members"),
               "targets": [out / "assembly_members.parquet", out / "inputs.json"]}


def task_assembly_members():
    """The catalog's assembly_members: every book's, in book order."""
    parts = [BUILD / "books" / b / "members" / "assembly_members.parquet" for b in BOOKS]
    out = CATALOG / "members"

    def action():
        with layout.output(out) as tmp:
            pq.write_table(pa.concat_tables([pq.read_table(p) for p in parts]), tmp / "assembly_members.parquet",
                           compression="zstd")
    return {"actions": [action], "file_dep": parts + code("members"),
            "targets": [out / "assembly_members.parquet"]}


def task_roots():
    """Every root once, from the FASTA files the books' sources declare (see refbook_pipeline/roots.py)."""
    srcs = [s for s in books.sources_of(BOOKS, SOURCES) if s.sequences or s.loose_roots]
    table = CATALOG / "members" / "assembly_members.parquet"
    fastas = [(RAW / p, sources.url_of(p)) for s in srcs for p in s.sequences]
    loose = [(acc, RAW / record) for s in srcs for acc, record in s.loose_roots]
    out = CATALOG / "roots"

    def action():
        expected = members.lengths(pq.read_table(table))
        for acc, record in loose:
            if acc in expected:
                raise Refused(f"{acc} is declared a loose root, but an assembly report lists it")
            expected[acc] = roots.genbank_length(record)
        with layout.output(out) as tmp:
            print(roots.build(expected, fastas, tmp))
            layout.record_inputs(tmp, [lock_path(s.name) for s in srcs])

    dep = reads(srcs)
    names = ["roots", "root_blocks", "layer_softmask_ncbi", "layer_n_runs", "layer_iupac"]
    return {"actions": [action], "task_dep": dep["task_dep"],
            "file_dep": [table] + [p for p, _ in fastas] + [r for _, r in loose] + dep["file_dep"] + code("roots", "members"),
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
    paths = {"assembly_members": CATALOG / "members" / "assembly_members.parquet",
             "roots": CATALOG / "roots" / "roots.parquet", "root_blocks": CATALOG / "roots" / "root_blocks.parquet",
             "layer_iupac": CATALOG / "roots" / "layer_iupac.parquet",
             "roots_external": CATALOG / "external" / "roots_external.parquet",
             "layer_placements": CATALOG / "layers" / "layer_placements.parquet"}
    for name in {m["layer"] for r in recipes for m in r.get("mask", [])}:
        paths[f"layer_{name}"] = CATALOG / "layers" / f"layer_{name}.parquet"
    return paths


def task_reproduce():
    """Apply a book's recipes and check each against its target's observation (order-free, by name: the same
    names, lengths and digests). Writes each target's sequences in its own order; writes nothing unless every
    target reproduces."""
    for book in BOOKS.values():
        recipes = books.recipes(layout.BOOKS, book.name)
        paths = catalog_tables(recipes)
        observed = BUILD / "books" / book.name / "observed"
        out = BUILD / "books" / book.name / "reproduced"

        def action(recipes=recipes, paths=paths, observed=observed, out=out):
            t = engine.load_tables(paths, recipes)
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
            t = engine.load_tables(paths, recipes)
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
                combined[name] = pa.concat_tables(tables)
                pq.write_table(combined[name], tmp / f"{name}.parquet", compression="zstd")
            labels = combined["editions"]["edition"].to_pylist()
            if len(labels) != len(set(labels)):
                raise Refused(f"an edition label is used in two books: {sorted({x for x in labels if labels.count(x) > 1})}")
            cols = ["root_id", "length", "md5", "sha512t24u"]
            roots = {r["root_id"]: r for p in roots_paths for r in pq.read_table(p, columns=cols).to_pylist()}
            seqs, ders = editions.sequence_store(combined["manifests"].to_pylist(), roots)
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
        rows, notes = set(), []
        for book in BOOKS.values():
            releases = {layers.Release.of(RAW, SOURCES[n].base).name for n in book.releases}
            by_target = {}
            for r in pq.read_table(BUILD / "books" / book.name / "reproduced" / "reproduced.parquet").to_pylist():
                by_target.setdefault(r["target"], []).append(r)
            got, n = aliases.book_aliases(book.name, [m for m in members_all if m["book"] == book.name], releases,
                                          list(book.aliases), by_target, chromalias)
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


LAYERS = ["layer_agp", "layer_regions", "layer_placements", "layer_hardmask_grc"]


def task_layers():
    """A book's layers, from its releases' and add-ons' assembly structure (see refbook_pipeline/layers.py)."""
    for book in BOOKS.values():
        srcs = [SOURCES[n] for n in book.releases + book.addons]
        rels = [layers.Release.of(RAW, SOURCES[n].base) for n in book.releases]
        dirs = [RAW / s.base for s in srcs]
        mask = book.hardmask_grc
        mask_src = [SOURCES[mask["source"]]] if mask else []
        mask_file = RAW / SOURCES[mask["source"]].base / mask["file"] if mask else None
        table = BUILD / "books" / book.name / "members" / "assembly_members.parquet"
        lengths = CATALOG / "roots" / "roots.parquet"
        out = BUILD / "books" / book.name / "layers"

        def action(book=book, rels=rels, dirs=dirs, mask=mask, mask_file=mask_file, srcs=srcs + mask_src,
                   table=table, lengths=lengths, out=out):
            ms = pq.read_table(table).to_pylist()
            r = pq.read_table(lengths, columns=["root_id", "length"])
            length = dict(zip(r["root_id"].to_pylist(), r["length"].to_pylist()))
            with layout.output(out) as tmp:
                agp = layers.build_agp(RAW, dirs, {m["genbank_accession"] for m in ms})
                regions, spans = layers.build_regions(rels, ms, set(book.region_quirks))
                placements, notes = layers.build_placements(rels, ms, length, spans)
                tables = {"layer_agp": agp, "layer_regions": regions, "layer_placements": placements}
                if mask:
                    tables["layer_hardmask_grc"] = layers.build_hardmask_grc(mask_file, length, regions,
                                                                           mask["par_root"])
                for name, t in tables.items():
                    pq.write_table(t, tmp / f"{name}.parquet", compression="zstd")
                (tmp / "notes.json").write_text(json.dumps(notes, indent=1) + "\n")
                layout.record_inputs(tmp, [lock_path(s.name) for s in srcs])
                print({name: t.num_rows for name, t in tables.items()}, notes)

        files = [RAW / f for s in srcs for f in sources.files(s, RAW)[0]] + ([mask_file] if mask else [])
        dep = reads(srcs + mask_src)
        yield {"name": book.name, "actions": [action], "task_dep": dep["task_dep"],
               "file_dep": [table, lengths] + files + dep["file_dep"] + code("layers", "members"),
               "targets": [out / f"{n}.parquet" for n in LAYERS[:3] + (LAYERS[3:] if mask else [])]
                          + [out / "notes.json", out / "inputs.json"]}


def task_catalog_layers():
    """The catalog's layers: every book's. A root-keyed layer (AGP, hard-mask) has each root once, the same in
    every book that has it; regions and placements, numbered by release, carry their book."""
    out = CATALOG / "layers"
    parts = {b: BUILD / "books" / b / "layers" for b in BOOKS}

    def action():
        with layout.output(out) as tmp:
            for name in LAYERS:
                found = [(b, d / f"{name}.parquet") for b, d in parts.items() if (d / f"{name}.parquet").exists()]
                tables = [pq.read_table(p) for _, p in found]
                if name in ("layer_regions", "layer_placements"):
                    tables = [t.add_column(0, "book", pa.array([b] * t.num_rows, pa.string()))
                              for (b, _), t in zip(found, tables)]
                    combined = pa.concat_tables(tables)
                else:
                    combined, seen = [], {}
                    for t in tables:
                        for root, rows in sorted(_by_root(t).items()):
                            if root in seen and seen[root] != rows:
                                raise Refused(f"{name}: {root} differs between books")
                            if root not in seen:
                                seen[root] = rows
                                combined += rows
                    combined = pa.Table.from_pylist(combined, schema=tables[0].schema)
                pq.write_table(combined, tmp / f"{name}.parquet", compression="zstd")

    deps = [d / f"{n}.parquet" for b, d in parts.items() for n in LAYERS
            if n != "layer_hardmask_grc" or BOOKS[b].hardmask_grc]
    return {"actions": [action], "file_dep": deps + code("layers"),
            "targets": [out / f"{n}.parquet" for n in LAYERS]}


def _by_root(t: pa.Table) -> dict[str, list[dict]]:
    out = {}
    for row in t.to_pylist():
        out.setdefault(row["root_id"], []).append(row)
    return out


def task_compare_v1():
    """Everything built so far against the first pipeline's build (until the switch)."""
    here = BUILD / "compare_v1"
    paths = [lock_path(n) for n in SOURCES]
    old_locks = [layout.REPO / p for p in v1.V1_LOCKS]
    yield {"name": "locks", "actions": [call(v1.compare_locks, layout.REPO, paths, here / "locks.json")],
           "file_dep": paths + old_locks + code("v1", "locks"), "targets": [here / "locks.json"]}
    old = layout.REPO / v1.V1_BUILD / "10_roots"
    tables = {  # name: (where it is here, its key, the columns only this pipeline has)
        "assembly_members": (CATALOG / "members", ["book", "assembly_accession", "genbank_accession"], ("book",)),
        "roots": (CATALOG / "roots", ["root_id"], ()),
        "layer_softmask_ncbi": (CATALOG / "roots", ["root_id", "start"], ()),
        "layer_n_runs": (CATALOG / "roots", ["root_id", "start"], ()),
        "layer_iupac": (CATALOG / "roots", ["root_id", "pos"], ()),
    }
    for book in BOOKS:
        old_observed = layout.REPO / v1.V1_BUILD / "30_observe" / "observed"
        new_observed = BUILD / "books" / book / "observed"
        targets = [r["target"] for r in books.recipes(layout.BOOKS, book)]
        yield {"name": f"observed:{book}", "actions": [call(v1.compare_observed, old_observed, new_observed, targets,
                                                             here / f"observed-{book}.json")],
               "file_dep": [d / f"{t}.parquet" for t in targets for d in (old_observed, new_observed)] + code("v1"),
               "targets": [here / f"observed-{book}.json"]}
    copied = {"recipes": "catalog/assemblies/grch38/recipes", "editions.json": "catalog/assemblies/grch38/editions.json"}
    yield {"name": "book-inputs", "actions": [call(v1.compare_files, layout.REPO, copied, layout.BOOKS / "grch38",
                                                    here / "book-inputs.json")],
           "file_dep": code("v1"), "uptodate": [False], "targets": [here / "book-inputs.json"]}
    old_ext = layout.REPO / v1.V1_BUILD / "11_external_roots" / "roots_external.parquet"
    yield {"name": "roots_external",
           "actions": [call(v1.compare_table, old_ext, CATALOG / "external" / "roots_external.parquet", ["root_id"],
                            here / "roots_external.json")],
           "file_dep": [old_ext, CATALOG / "external" / "roots_external.parquet"] + code("v1"),
           "targets": [here / "roots_external.json"]}
    for book in BOOKS:
        old_rep = layout.REPO / v1.V1_BUILD / "40_recipes" / "reproduced.parquet"
        new_rep = BUILD / "books" / book / "reproduced" / "reproduced.parquet"
        yield {"name": f"reproduced:{book}",
               "actions": [call(v1.compare_table, old_rep, new_rep, ["target", "position"], here / f"reproduced-{book}.json",
                                (), True)],
               "file_dep": [old_rep, new_rep] + code("v1"), "targets": [here / f"reproduced-{book}.json"]}
    old_ed = layout.REPO / v1.V1_BUILD / "41_editions"
    edition_keys = {"editions": (["edition"], ("book",)), "manifests": (["edition", "name"], ()),
                    "targets": (["target"], ()), "target_sequences": (["target", "position"], ()),
                    "sequences": (["sha512t24u"], ()), "derivations": (["sha512t24u", "root_id"], ())}
    for name, (keys, only_new) in edition_keys.items():
        new, report = CATALOG / "editions" / f"{name}.parquet", here / f"{name}.json"
        rowwise = name in ("editions", "derivations", "targets")
        yield {"name": name, "actions": [call(v1.compare_table, old_ed / f"{name}.parquet", new, keys, report, only_new,
                                              rowwise)],
               "file_dep": [old_ed / f"{name}.parquet", new] + code("v1"), "targets": [report]}
    yield {"name": "collections",
           "actions": [call(v1.compare_dirs, old_ed / "collections", CATALOG / "editions" / "collections",
                            here / "collections.json")],
           "file_dep": [CATALOG / "editions" / "derivations.parquet"] + code("v1"), "targets": [here / "collections.json"]}
    old_al = layout.REPO / v1.V1_BUILD / "50_aliases"
    for name, keys, only_new in (("aliases", ["root_id", "namespace", "alias", "source"], ("book",)),
                                 ("sequence_aliases", ["sha512t24u", "naming_authority", "alias"], ())):
        new, report = CATALOG / "aliases" / f"{name}.parquet", here / f"{name}.json"
        yield {"name": name, "actions": [call(v1.compare_table, old_al / f"{name}.parquet", new, keys, report, only_new)],
               "file_dep": [old_al / f"{name}.parquet", new] + code("v1"), "targets": [report]}
    old_layers = layout.REPO / v1.V1_BUILD / "20_layers"
    layer_keys = {"layer_agp": (["root_id", "part_number"], ()),
                  "layer_regions": (["root_id", "region_name", "first_release", "book"], ("book",)),
                  "layer_placements": (["root_id", "first_release", "book"], ("book",)),
                  "layer_hardmask_grc": (["root_id", "start"], ())}
    for name, (keys, only_new) in layer_keys.items():
        new, report = CATALOG / "layers" / f"{name}.parquet", here / f"{name}.json"
        keys = [k for k in keys if k not in only_new]
        yield {"name": name, "actions": [call(v1.compare_table, old_layers / f"{name}.parquet", new, keys, report,
                                              only_new)],
               "file_dep": [old_layers / f"{name}.parquet", new] + code("v1"), "targets": [report]}
    for name, (where, keys, only_new) in tables.items():
        new, report = where / f"{name}.parquet", here / f"{name}.json"
        keys = [k for k in keys if k not in only_new]
        yield {"name": name, "actions": [call(v1.compare_table, old / f"{name}.parquet", new, keys, report, only_new)],
               "file_dep": [old / f"{name}.parquet", new] + code("v1"), "targets": [report]}
    yield {"name": "root_blocks",
           "actions": [call(v1.compare_blocks, old / "root_blocks.parquet", CATALOG / "roots" / "root_blocks.parquet",
                            here / "root_blocks.json")],
           "file_dep": [old / "root_blocks.parquet", CATALOG / "roots" / "root_blocks.parquet"] + code("v1"),
           "targets": [here / "root_blocks.json"]}
