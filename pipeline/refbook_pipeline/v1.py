"""The first pipeline's outputs, compared with this one's while both exist: the switch happens when they match.

Each comparison allows only the differences listed here, each with its reason; anything else refuses.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from . import Refused, locks

V1_LOCKS = ["catalog/assemblies/grch38/locks/inputs.lock", "catalog/assemblies/grch38/locks/targets.lock"]
# In the first pipeline's inputs.lock but declared by no source here: that lock hashed every file under a host.
NOT_DECLARED = {
    "raw.githubusercontent.com/ANHIG/IMGTHLA/3170/": "IMGT/HLA 3.17.0, fetched while finding the release hs38DH uses",
    "raw.githubusercontent.com/ANHIG/IMGTHLA/3190/": "IMGT/HLA 3.19.0, likewise",
    "raw.githubusercontent.com/ANHIG/IMGTHLA/3200/": "IMGT/HLA 3.20.0, likewise",
}


def compare_locks(repo: Path, lock_paths: list[Path], out: Path) -> None:
    """Every row of the first pipeline's two locks must be in exactly one lock here, field for field (bytes,
    sha256, Last-Modified, URL), but for the files NOT_DECLARED; and every row here must be one of theirs."""
    old = {}
    for rel in V1_LOCKS:
        old.update(locks.read(repo / rel))
    new, twice = {}, []
    for p in lock_paths:
        for path, row in locks.read(p).items():
            (twice.append(path) if path in new else None)
            new[path] = row
    skipped = {p for p in old if any(p.startswith(pre) for pre in NOT_DECLARED)}
    only_old = sorted(set(old) - set(new) - skipped)
    only_new = sorted(set(new) - set(old))
    differ = sorted(p for p in set(old) & set(new) if old[p] != new[p])
    result = {"v1_rows": len(old), "rows": len(new), "not_declared": len(skipped),
              "not_declared_why": NOT_DECLARED, "only_v1": only_old[:20], "only_here": only_new[:20],
              "differ": differ[:20], "in_two_locks": twice[:20],
              "matches": not (only_old or only_new or differ or twice)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    if not result["matches"]:
        raise Refused(f"the locks differ from the first pipeline's: {len(only_old)} only there, {len(only_new)} "
                      f"only here, {len(differ)} differ, {len(twice)} in two locks (see {out})")


V1_BUILD = "catalog/output/build/grch38"


def compare_table(old: Path, new: Path, keys: list[str], out: Path, only_new: tuple[str, ...] = ()) -> None:
    """A table here against the first pipeline's: the same columns (but for `only_new`, this pipeline's
    additions) and the same rows, in any order (both sorted by `keys`)."""
    a, b = pq.read_table(old), pq.read_table(new).drop_columns(list(only_new))
    result = {"v1": str(old), "here": str(new), "v1_rows": a.num_rows, "rows": b.num_rows,
              "only_new_columns": list(only_new), "columns_v1": a.column_names, "columns": b.column_names}
    if a.column_names == b.column_names:
        sort = [(k, "ascending") for k in keys]
        a, b = a.sort_by(sort), b.sort_by(sort).cast(a.schema)
        result["matches"] = a.equals(b)
        if not result["matches"]:
            ra, rb = a.to_pylist(), b.to_pylist()
            result["first_differences"] = [{"v1": x, "here": y} for x, y in zip(ra, rb) if x != y][:5]
    else:
        result["matches"] = False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n")
    if not result["matches"]:
        raise Refused(f"{new.name} differs from the first pipeline's (see {out})")


def compare_blocks(old: Path, new: Path, out: Path) -> None:
    """root_blocks here against the first pipeline's: for every root, the same blocks (starts) and the same bases.
    Row groups may come in another order (the roots are read in another order); each root's are compared whole."""
    def per_root(path: Path) -> dict[str, tuple[list[int], str]]:
        f = pq.ParquetFile(path)
        h, starts = {}, {}
        for i in range(f.num_row_groups):
            t = f.read_row_group(i, columns=["root_id", "start", "bases"])
            for root, start, bases in zip(t["root_id"].to_pylist(), t["start"].to_pylist(), t["bases"].to_pylist()):
                h.setdefault(root, hashlib.sha256()).update(bases.encode())
                starts.setdefault(root, []).append(start)
        return {r: (starts[r], h[r].hexdigest()) for r in h}
    a, b = per_root(old), per_root(new)
    differ = sorted(r for r in set(a) & set(b) if a[r] != b[r])
    result = {"v1_roots": len(a), "roots": len(b), "only_v1": sorted(set(a) - set(b))[:10],
              "only_here": sorted(set(b) - set(a))[:10], "differ": differ[:10]}
    result["matches"] = not (result["only_v1"] or result["only_here"] or differ)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    if not result["matches"]:
        raise Refused(f"root_blocks differs from the first pipeline's (see {out})")
