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

import pyarrow as pa
import pyarrow.parquet as pq
from refbook_pipeline import books, layout, locks, members, roots, sources, v1

RAW, BUILD = layout.raw_dir(), layout.build_dir()
BUILD.mkdir(parents=True, exist_ok=True)  # doit keeps its state beside it, and doesn't make the directory
CATALOG = BUILD / "catalog"
SOURCES = sources.load(layout.SOURCES)
BOOKS = books.load(layout.BOOKS, SOURCES)

DOIT_CONFIG = {
    "default_tasks": ["lock", "members", "assembly_members", "roots", "compare_v1"],
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
                raise roots.Refused(f"{acc} is declared a loose root, but an assembly report lists it")
            expected[acc] = roots.genbank_length(record)
        with layout.output(out) as tmp:
            print(roots.build(expected, fastas, tmp))
            layout.record_inputs(tmp, [lock_path(s.name) for s in srcs])

    dep = reads(srcs)
    names = ["roots", "root_blocks", "layer_softmask_ncbi", "layer_n_runs", "layer_iupac"]
    return {"actions": [action], "task_dep": dep["task_dep"],
            "file_dep": [table] + [p for p, _ in fastas] + [r for _, r in loose] + dep["file_dep"] + code("roots", "members"),
            "targets": [out / f"{n}.parquet" for n in names] + [out / "inputs.json"]}


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
