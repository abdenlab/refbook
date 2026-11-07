"""Locks: each source's files pinned to exact bytes, and checked against their publisher's checksums.

A lock (pipeline/locks/<source>.lock) lists every file of one source: path under raw/, size, sha256, the
server's Last-Modified (wget keeps it as the file's mtime) and source URL, tab-separated, sorted by path. It is
committed, so a build is pinned to exact bytes, and a release records the hash of every lock it was built from.

Locking a source:
1. Hashes each of its files under raw/.
2. Checks every file one of the source's own checksum lists covers: NCBI md5checksums.txt, UCSC md5sum.txt and
   GENCODE MD5SUMS (MD5), Ensembl CHECKSUMS (BSD `sum`, computed with the system's `sum`). Broad, 1000 Genomes,
   iGenomes and the GenBank records publish none, so the lock alone covers theirs. A mismatch is accepted only if
   the source's exceptions file (<source>.exceptions.tsv beside the lock) lists it exactly: the path, the listed
   MD5 and the MD5 of the file we have, with the reason.
3. Compares with the lock. With no lock yet, trusts the files on first use (after step 2) and writes it.
   Otherwise a file that is new, missing or changed refuses, unless `update`, which rewrites the lock.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from . import Refused
from .sources import url_of

FIELDS = ["path", "bytes", "sha256", "last_modified", "url"]
MD5_LISTS = {"md5checksums.txt", "md5sum.txt", "MD5SUMS"}   # "<md5>  <path>" lines
SUM_LISTS = {"CHECKSUMS"}                                   # "<sum> <blocks> <path>" lines (BSD sum)


def digests(path: Path) -> tuple[str, str]:
    """(sha256, md5) of a file, in one pass."""
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def bsd_sum(path: Path) -> tuple[int, int]:
    """(checksum, 1 KiB blocks) of a file, as BSD `sum` prints them."""
    out = subprocess.run(["sum", "-r", str(path)], capture_output=True, text=True, check=True).stdout
    checksum, blocks = out.split()[:2]
    return int(checksum), int(blocks)


def read(path: Path) -> dict[str, dict]:
    rows = [line.split("\t") for line in path.read_text().splitlines()[1:]]
    return {r[0]: dict(zip(FIELDS, r)) for r in rows}


def write(path: Path, entries: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.partial")
    with open(tmp, "w") as f:
        f.write("\t".join(FIELDS) + "\n")
        f.writelines("\t".join(str(entries[p][k]) for k in FIELDS) + "\n" for p in sorted(entries))
    tmp.replace(path)


def exceptions(path: Path) -> set[tuple[str, str, str]]:
    """(path, listed MD5, served MD5) of every documented publisher mismatch."""
    if not path.exists():
        return set()
    return {tuple(line.split("\t")[:3]) for line in path.read_text().splitlines()[1:]}


def hashed(raw: Path, rels: list[str]) -> dict[str, dict]:
    """Each file's lock row, with its MD5 for the publisher checks."""
    out = {}
    for rel in rels:
        p = raw / rel
        sha, md5 = digests(p)
        out[rel] = {"path": rel, "bytes": p.stat().st_size, "sha256": sha, "md5": md5,
                    "last_modified": datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(), "url": url_of(rel)}
    return out


def listed(raw: Path, files: dict[str, dict], extra: tuple[str, ...] = ()) -> dict[str, tuple[str, str]]:
    """The files the source's checksum lists cover (its own, and `extra` lists elsewhere under raw/):
    path -> (the list's path, its line)."""
    out = {}
    for rel in sorted(files) + list(extra):
        name = Path(rel).name
        if name not in MD5_LISTS | SUM_LISTS:
            continue
        base = Path(rel).parent
        for line in (raw / rel).read_text().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            target = (base / parts[-1].removeprefix("./")).as_posix()
            if target in files:
                out[target] = (rel, line)
    return out


def publisher_checks(raw: Path, files: dict[str, dict], known: set[tuple[str, str, str]],
                     extra: tuple[str, ...] = ()) -> tuple[int, list[str]]:
    """Check every file the source's checksum lists cover, allowing the known mismatches: (checked, errors)."""
    errors = []
    covered = listed(raw, files, extra)
    for target, (lst, line) in sorted(covered.items()):
        parts = line.split()
        if Path(lst).name in MD5_LISTS:
            ok = files[target]["md5"] == parts[0] or (target, parts[0], files[target]["md5"]) in known
        else:
            ok = bsd_sum(raw / target) == (int(parts[0]), int(parts[1]))
        if not ok:
            errors.append(f"{target}: does not match {lst}")
    return len(covered), errors


def lock(name: str, raw: Path, rels: list[str], missing: list[str], lock_path: Path, update: bool = False,
         checksums: tuple[str, ...] = ()) -> dict:
    """Lock one source (see the module's docstring). Returns what was checked; raises Refused on any problem,
    leaving the lock as it was."""
    if missing:
        raise Refused(f"{name}: {len(missing)} required files are not under {raw}, e.g. {missing[:3]} (fetch it)")
    files = hashed(raw, rels)
    gone = [c for c in checksums if not (raw / c).is_file()]
    if gone:
        raise Refused(f"{name}: checksum lists it names are not under {raw}: {gone}")
    checked, errors = publisher_checks(raw, files, exceptions(lock_path.with_name(f"{name}.exceptions.tsv")), checksums)
    if errors:
        raise Refused(f"{name}: " + "; ".join(errors[:10]))
    report = {"source": name, "files": len(files), "checked_by_publisher": checked}
    if not lock_path.exists():
        write(lock_path, files)
        return {**report, "lock": "written (trusted on first use)"}
    old = read(lock_path)
    new = sorted(set(files) - set(old))
    gone = sorted(set(old) - set(files))
    changed = sorted(p for p in set(files) & set(old)
                     if (files[p]["sha256"], str(files[p]["bytes"])) != (old[p]["sha256"], old[p]["bytes"]))
    if new or gone or changed:
        if not update:
            raise Refused(f"{name}: {len(new)} new, {len(gone)} missing, {len(changed)} changed files "
                          f"(e.g. {(changed + new + gone)[:3]}); check them, then lock again with --update")
        write(lock_path, files)
        return {**report, "lock": f"updated: {len(new)} new, {len(gone)} missing, {len(changed)} changed"}
    return {**report, "lock": "unchanged"}
