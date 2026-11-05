"""Lock the raw downloads: check them against their publishers' checksums and a lock.

A lock (catalog/assemblies/<assembly>/locks/inputs.lock and targets.lock) lists every
file the build uses from some hosts under raw/: path, size, sha256, the server's
Last-Modified (wget -N keeps it as the file's mtime) and source URL. It is
committed, so a build is pinned to exact bytes, and a release records the
hashes of the locks it was built from.

Every run:
1. Hashes every file under raw/<host> for each host given.
2. Checks every file a publisher's checksum list covers: NCBI md5checksums.txt,
   UCSC md5sum.txt and GENCODE MD5SUMS (MD5), Ensembl CHECKSUMS (BSD `sum`,
   computed with the system's `sum`). Broad and iGenomes publish theirs only
   in response headers, which wget doesn't keep, so their files are covered
   by the lock alone.
   A mismatch is accepted only if checksum_exceptions.tsv, next to the lock,
   lists it
   exactly (the path, the listed MD5 and the MD5 of the file we have), with
   the reason: a publisher serving a file its own list disagrees with.
3. Compares with the lock. With no lock yet, trusts the files on first use
   (after step 2) and writes it. Otherwise a file that is new, missing or
   changed is an error, unless --update, which rewrites the lock and lists
   what changed.

Exits nonzero on any error. Run by 00_fetch_inputs.sh and 01_fetch_targets.sh.

Usage: uv run python -I catalog/lock.py LOCK HOST... [--raw DIR] [--update]
"""

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout

FIELDS = ["path", "bytes", "sha256", "last_modified", "url"]
MD5_LISTS = {"md5checksums.txt", "md5sum.txt", "MD5SUMS"}   # "<md5>  <path>" lines
SUM_LISTS = {"CHECKSUMS"}                                   # "<sum> <blocks> <path>" lines (BSD sum)


def source_url(rel: Path) -> str:
    """A file's source URL from its path under raw/: efetch results are saved as
    nuccore_<acc>.<rettype>; everything else mirrors its URL."""
    parts = rel.parts
    if parts[0] == "eutils.ncbi.nlm.nih.gov":
        acc = rel.stem.removeprefix("nuccore_")
        return ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                f"?db=nuccore&id={acc}&rettype={rel.suffix[1:]}&retmode=text")
    return "https://" + "/".join(parts)


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


def read_lock(path: Path) -> dict[str, dict]:
    rows = [line.rstrip("\n").split("\t") for line in path.read_text().splitlines()[1:]]
    return {r[0]: dict(zip(FIELDS, r)) for r in rows}


def write_lock(path: Path, entries: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    with open(tmp, "w") as f:
        f.write("\t".join(FIELDS) + "\n")
        f.writelines("\t".join(str(entries[p][k]) for k in FIELDS) + "\n" for p in sorted(entries))
    tmp.replace(path)


def known_mismatches(exceptions: Path) -> set[tuple[str, str, str]]:
    """(path, listed MD5, served MD5) of every documented publisher mismatch."""
    if not exceptions.exists():
        return set()
    rows = [line.split("\t") for line in exceptions.read_text().splitlines()[1:]]
    return {(r[0], r[1], r[2]) for r in rows}


def publisher_checks(raw: Path, files: dict[str, dict],
                     known: set[tuple[str, str, str]] = frozenset()) -> tuple[int, list[str]]:
    """Check every file a publisher's checksum list covers, allowing the known
    mismatches; return (checked, errors)."""
    checked, errors = 0, []
    for rel in sorted(files):
        name = Path(rel).name
        if name not in MD5_LISTS | SUM_LISTS:
            continue
        base = Path(rel).parent
        for line in (raw / rel).read_text().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            target = (base / parts[-1].removeprefix("./")).as_posix()
            if target not in files:
                continue   # listed, but not something we fetch
            if name in MD5_LISTS:
                ok = files[target]["md5"] == parts[0] or (target, parts[0], files[target]["md5"]) in known
            else:
                ok = bsd_sum(raw / target) == (int(parts[0]), int(parts[1]))
            checked += 1
            if not ok:
                errors.append(f"{target}: does not match {rel}")
    return checked, errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lock", type=Path)
    ap.add_argument("hosts", nargs="+")
    ap.add_argument("--update", action="store_true", help="accept changes and rewrite the lock")
    ap.add_argument("--raw", type=Path, help="the downloads (default: catalog/output/raw, or $REFBOOK_RAW)")
    args = ap.parse_args()
    raw = layout.raw_dir(args.raw)

    missing = [h for h in args.hosts if not (raw / h).is_dir()]
    if missing:
        sys.exit(f"no {', '.join(missing)} under {raw}: is that the raw downloads directory?")
    files = {}
    for host in args.hosts:
        for path in sorted(p for p in (raw / host).rglob("*") if p.is_file()):
            rel = path.relative_to(raw)
            sha, md5 = digests(path)
            mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
            files[rel.as_posix()] = {"path": rel.as_posix(), "bytes": path.stat().st_size,
                                     "sha256": sha, "md5": md5, "last_modified": mtime,
                                     "url": source_url(rel)}
    checked, errors = publisher_checks(raw, files, known_mismatches(args.lock.with_name("checksum_exceptions.tsv")))
    print(f"{len(files)} files under {', '.join(args.hosts)}; {checked} checked against "
          "their publishers' checksums", file=sys.stderr)

    if not args.lock.exists():
        if errors:
            sys.exit("\n".join(errors))
        write_lock(args.lock, files)
        print(f"no lock yet: trusted on first use, wrote {args.lock}", file=sys.stderr)
        return
    locked = read_lock(args.lock)
    new = sorted(set(files) - set(locked))
    gone = sorted(set(locked) - set(files))
    changed = sorted(p for p in set(files) & set(locked)
                     if (files[p]["sha256"], str(files[p]["bytes"])) != (locked[p]["sha256"], locked[p]["bytes"]))
    for label, paths in (("new", new), ("missing", gone), ("changed", changed)):
        for p in paths[:20]:
            print(f"  {label}: {p}", file=sys.stderr)
        if len(paths) > 20:
            print(f"  ... {len(paths) - 20} more {label}", file=sys.stderr)
    if errors:
        sys.exit("\n".join(errors))
    if new or gone or changed:
        if not args.update:
            sys.exit(f"{args.lock}: {len(new)} new, {len(gone)} missing, {len(changed)} changed "
                     "files; check them, then rerun with --update to accept")
        write_lock(args.lock, files)
        print(f"updated {args.lock}", file=sys.stderr)
    else:
        print(f"every file matches {args.lock}", file=sys.stderr)


if __name__ == "__main__":
    os.umask(0o022)
    main()
