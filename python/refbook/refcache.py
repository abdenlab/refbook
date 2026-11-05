"""Serve sequences by MD5, and fill htslib's REF_CACHE with them.

CRAM stores reads as differences from a reference that it names only by MD5
(the @SQ M5 tag). htslib finds those sequences in REF_CACHE, then REF_PATH
(EBI's MD5 server by default). Any sequence in the catalog's sequence store
can be served by its MD5 here, including derived ones (masked, IUPAC -> N)
that no public MD5 server holds.

- `sequence_by_md5(cat, md5)`: the bases, uppercase, as one bytes object:
  exactly what the MD5 covers.
- `populate_ref_cache(cat, md5s, root)`: write them in htslib's cache layout,
  root/aa/bb/<rest of the MD5>, file contents the bases with no newline (as
  samtools' seq_cache_populate.pl writes them). Use it with
  REF_CACHE=root/%2s/%2s/%s.
"""

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from refbook.catalog import Catalog
from refbook.materialize import Bases, sequence_bases


def sequence_by_md5(cat: Catalog, md5: str, bases: Bases | None = None) -> bytes:
    sq = cat.sq_by_md5.get(md5.lower())
    if sq is None:
        raise KeyError(f"{md5}: no sequence with this MD5 in the catalog")
    return sequence_bases(cat, sq, bases or Bases(cat))


def cache_path(root: str | Path, md5: str, subdirs: int = 2) -> Path:
    parts = [md5[2 * i:2 * i + 2] for i in range(subdirs)]
    return Path(root, *parts, md5[2 * subdirs:])


def populate_ref_cache(cat: Catalog, md5s: Iterable[str], root: str | Path, subdirs: int = 2,
                       bases: Bases | None = None) -> dict[str, list[str]]:
    """Write every known MD5's sequence into the cache; report written, present and unknown."""
    report = {"written": [], "present": [], "unknown": []}
    bases = bases or Bases(cat)
    for md5 in dict.fromkeys(m.lower() for m in md5s):
        sq = cat.sq_by_md5.get(md5)
        if sq is None:
            report["unknown"].append(md5)
            continue
        path = cache_path(root, md5, subdirs)
        if path.exists() and path.stat().st_size == cat.sequence[sq]["length"]:
            report["present"].append(md5)
            continue
        b = sequence_bases(cat, sq, bases)   # MD5-verified as it is built
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(b)
        os.replace(tmp, path)
        report["written"].append(md5)
    return report
