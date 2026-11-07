"""The first pipeline's outputs, compared with this one's while both exist: the switch happens when they match.

Each comparison allows only the differences listed here, each with its reason; anything else refuses.
"""

from __future__ import annotations

import json
from pathlib import Path

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
