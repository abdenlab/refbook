"""The registry's layout and the GRCh38 releases, defined once for every step.

A registry directory holds raw/ (downloads, at raw/<host>/<url path>) and
build/<assembly>/ (the steps' outputs).
"""

import hashlib
import json
import shutil
from contextlib import contextmanager
from pathlib import Path

ASSEMBLY = "grch38"
NCBI = "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405"
HS38D1 = "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/786/075/GCA_000786075.2_hs38d1"
GRCH38 = "GCA_000001405."   # GenBank assembly accession prefix of every GRCh38 release

# GRCh38 p0..p14: (patch number, GenBank assembly accession.version, assembly name).
# p0 is the major release, officially just "GRCh38".
RELEASES = [(n, f"{GRCH38}{15 + n}", "GRCh38" if n == 0 else f"GRCh38.p{n}") for n in range(15)]
LATEST = RELEASES[-1]


def raw_dir(registry: Path) -> Path:
    return registry / "raw"


def build_dir(registry: Path, assembly: str = ASSEMBLY) -> Path:
    return registry / "build" / assembly


def release_dir(raw: Path, n: int) -> Path:
    """The NCBI directory of GRCh38 patch release n under raw/."""
    _, accession, name = RELEASES[n]
    return raw / NCBI / f"{accession}_{name}"


def release_dirs(raw: Path) -> list[Path]:
    """Every GRCh38 release directory, p0 to p14."""
    return [release_dir(raw, n) for n, _, _ in RELEASES]


def assembly_dirs(raw: Path) -> list[Path]:
    """Every assembly directory with a report: GRCh38 p0-p14, then hs38d1."""
    return release_dirs(raw) + [raw / HS38D1]


def release_number(release: Path) -> int:
    """The patch number of a GRCh38 release directory: 0 for GCA_000001405.15_GRCh38."""
    accession = release.name.split("_")[0] + "_" + release.name.split("_")[1]
    for n, acc, _ in RELEASES:
        if acc == accession:
            return n
    raise ValueError(f"{release}: not a GRCh38 release directory")


# Steps. Each numbered step writes its own directory, build/<assembly>/<NN_name>/,
# and later steps find a table by name in whichever step directory has it. The
# build index (build/<assembly>/catalog.json) maps every name to its step
# directory, so refbook.Catalog can open a build without copying anything.

INDEX = "catalog.json"
CATALOG_FORMAT = 2  # the catalog format these steps write (refbook.catalog.FORMAT reads it)


def step_dirs(build: Path) -> list[Path]:
    return sorted(p for p in build.glob("[0-9][0-9]_*") if p.is_dir())


def path(build: Path, name: str) -> Path:
    """Where a step put the table (or directory) `name`, e.g. "roots.parquet"."""
    for d in step_dirs(build):
        if (d / name).exists():
            return d / name
    raise FileNotFoundError(f"{name}: no step under {build} has written it")


@contextmanager
def step_output(build: Path, step: str):
    """The output directory of a step, assembled under a temporary name and
    renamed into place only if the step finishes, replacing its last run."""
    out, tmp = build / step, build / f".{step}.partial"
    if tmp.exists():
        shutil.rmtree(tmp)  # left by an interrupted run
    tmp.mkdir(parents=True)
    try:
        yield tmp
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    write_index(build)


def write_index(build: Path) -> None:
    """build/<assembly>/catalog.json: every file any step wrote, by the name a
    release gives it, with the step directory it is in."""
    files = {}
    for d in step_dirs(build):
        for f in sorted(p for p in d.rglob("*") if p.is_file()):
            name = f.relative_to(d).as_posix()
            if name in files:
                raise ValueError(f"{name}: written by both {files[name]['path']} and {d.name}")
            files[name] = {"path": f"{d.name}/{name}", "bytes": f.stat().st_size}
    tmp = build / f".{INDEX}.partial"
    index = {"name": "refbook", "format": CATALOG_FORMAT, "version": f"build-{build.name}",
             "build": True, "files": files}
    tmp.write_text(json.dumps(index, indent=1) + "\n")
    tmp.replace(build / INDEX)


def sha256(p: Path) -> str:
    """sha256 of a file, or of a directory's files (names and contents, in order)."""
    h = hashlib.sha256()
    for f in sorted(q for q in p.rglob("*") if q.is_file()) if p.is_dir() else [p]:
        if p.is_dir():
            h.update(f.relative_to(p).as_posix().encode() + b"\0")
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
    return h.hexdigest()


def record_check(build: Path, out: Path, check: str, passed: bool, inputs: list[str],
                 details: dict | None = None) -> None:
    """A check's result, out/<check>.json: whether it passed, and the sha256 of
    every table it read, so a release can require a pass on exactly its files."""
    result = {"check": check, "passed": passed, "details": details or {},
              "inputs": {name: sha256(path(build, name)) for name in inputs}}
    (out / f"{check}.json").write_text(json.dumps(result, indent=1) + "\n")
