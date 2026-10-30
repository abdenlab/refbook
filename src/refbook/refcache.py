"""Serve sequences by MD5, and fill htslib's REF_CACHE with them.

CRAM stores reads as differences from a reference that it names only by MD5
(the @SQ M5 tag). htslib finds those sequences in REF_CACHE, then REF_PATH
(EBI's MD5 server by default). Any sequence of a reproduced flavor can be
served by its MD5 here, including derived ones (masked, IUPAC -> N) that no
public MD5 server holds.

- `sequence_by_md5(cat, md5)`: the bases, uppercase, as one bytes object:
  exactly what the MD5 covers.
- `populate_ref_cache(cat, md5s, root)`: write them in htslib's cache layout,
  root/aa/bb/<rest of the MD5>, file contents the bases with no newline (as
  samtools' seq_cache_populate.pl writes them). Use it with
  REF_CACHE=root/%2s/%2s/%s.
"""

import os
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from refbook.catalog import Catalog
from refbook.materialize import Bases, sequences


def _locate(cat: Catalog, md5s: Iterable[str]) -> tuple[dict[str, list[tuple[str, str]]], list[str]]:
    """flavor -> [(sequence name, md5)] covering every known MD5 once; and the unknown ones."""
    plan, unknown = defaultdict(list), []
    for md5 in dict.fromkeys(m.lower() for m in md5s):
        flavors = sorted(cat.flavors_with_md5.get(md5, ()))
        if not flavors:
            unknown.append(md5)
            continue
        f = flavors[0]
        name = next(s.name for s in cat.flavors[f] if s.md5 == md5)
        plan[f].append((name, md5))
    return plan, unknown


def sequence_by_md5(cat: Catalog, md5: str, bases: Bases | None = None) -> bytes:
    plan, unknown = _locate(cat, [md5])
    if unknown:
        raise KeyError(f"{md5}: no sequence with this MD5 in the catalog")
    (flavor, [(name, _)]), = plan.items()
    (_, b), = sequences(cat, flavor, [name], bases)
    return b


def cache_path(root: str | Path, md5: str, subdirs: int = 2) -> Path:
    parts = [md5[2 * i:2 * i + 2] for i in range(subdirs)]
    return Path(root, *parts, md5[2 * subdirs:])


def populate_ref_cache(cat: Catalog, md5s: Iterable[str], root: str | Path, subdirs: int = 2,
                       bases: Bases | None = None) -> dict[str, list[str]]:
    """Write every known MD5's sequence into the cache; report written, present and unknown."""
    plan, unknown = _locate(cat, md5s)
    report = {"written": [], "present": [], "unknown": unknown}
    bases = bases or Bases(cat)
    for flavor, wanted in plan.items():
        todo = {name: md5 for name, md5 in wanted}
        for name, md5 in list(todo.items()):
            path = cache_path(root, md5, subdirs)
            if path.exists() and path.stat().st_size == next(
                    s.length for s in cat.flavors[flavor] if s.name == name):
                report["present"].append(md5)
                del todo[name]
        if not todo:
            continue
        for name, b in sequences(cat, flavor, list(todo), bases):   # MD5-verified as it is built
            path = cache_path(root, todo[name], subdirs)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            with os.fdopen(fd, "wb") as f:
                f.write(b)
            os.replace(tmp, path)
            report["written"].append(todo[name])
    return report
