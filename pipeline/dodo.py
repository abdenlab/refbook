"""The catalog's pipeline (doit). Run from pipeline/:

    doit                      lock every source, and compare the locks with the first pipeline's
    doit lock:GRCh38.p14      lock one source
    doit lock:EBV --update    accept a source's changed files (after checking them) and rewrite its lock
    doit fetch:EBV            download one source into raw/ (never run unless asked)
    doit list                 every task; `doit info lock:EBV` why a task would run

Each task calls one function of refbook_pipeline; this file only declares what each reads and writes. doit reruns
a task when one of its file_dep's MD5 changes (the code included), and keeps its state in output/.doit.db.
"""

from refbook_pipeline import layout, locks, sources, v1

RAW, BUILD = layout.raw_dir(), layout.build_dir()
BUILD.mkdir(parents=True, exist_ok=True)  # doit keeps its state beside it, and doesn't make the directory
SOURCES = sources.load(layout.SOURCES)
CODE = [layout.PIPELINE / "refbook_pipeline" / f for f in ("__init__.py", "sources.py", "locks.py")]

DOIT_CONFIG = {
    "default_tasks": ["lock", "compare_v1"],
    "dep_file": str(BUILD.parent / ".doit.db"),
    "verbosity": 2,
}


def call(f, *args, **kwargs):
    """A doit action calling f: doit takes None, True, a str or a dict back (False fails the task), so the
    result is dropped. An exception (Refused) fails the task and every task that needs it."""
    def action():
        f(*args, **kwargs)
    return action


def lock_path(name: str):
    return layout.LOCKS / f"{name}.lock"


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
               "file_dep": [RAW / r for r in rels] + [RAW / c for c in src.checksums] + CODE + [layout.SOURCES],
               "targets": [lock_path(name)]}


def task_compare_v1():
    """The locks against the first pipeline's (until the switch)."""
    paths = [lock_path(n) for n in SOURCES]
    old = [layout.REPO / p for p in v1.V1_LOCKS]
    out = BUILD / "compare_v1" / "locks.json"
    return {"actions": [call(v1.compare_locks, layout.REPO, paths, out)],
            "file_dep": paths + old + [layout.PIPELINE / "refbook_pipeline" / "v1.py"], "targets": [out]}
