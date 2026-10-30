"""Materialize every reproduced flavor in full and check it from the bases.

run_recipes.py reuses a root's stored digest when a recipe leaves its bases
unchanged. This builds every sequence of every flavor from root_blocks (and
the IMGT/HLA release for external roots), applies the recipe's masks and
alphabet, and re-digests it (MD5 and SQ.) against flavor_sequences. It also
checks the stream itself: schema, row count, batch sizes, and that the
seqcol digest recomputed from the materialized bases equals the catalog's.

Usage: uv run python -I pipeline/check_materialize.py REGISTRY_DIR [FLAVOR ...]
"""

import hashlib
import sys
import time
from pathlib import Path

from ref_registry import Catalog, materialize
from ref_registry.materialize import SCHEMA, Bases
from ref_registry.seqcol import digests, sha512t24u


def main() -> None:
    registry = Path(sys.argv[1])
    cat = Catalog(registry / "build" / "grch38")
    flavors = sys.argv[2:] or sorted(cat.flavors)
    bases = Bases(cat)
    failed = []
    for f in flavors:
        t0 = time.time()
        names, lengths, sqs, batches, biggest = [], [], [], 0, 0
        try:
            reader = materialize(cat, f, bases=bases)
            if not reader.schema.equals(SCHEMA, check_metadata=False):
                raise ValueError(f"schema {reader.schema}")
            for batch in reader:
                batches += 1
                size = 0
                for name, seq in zip(batch.column("name").to_pylist(), batch.column("sequence")):
                    b = seq.as_py().encode("ascii")
                    names.append(name)
                    lengths.append(len(b))
                    sqs.append("SQ." + sha512t24u(b))
                    size += len(b)
                biggest = max(biggest, size)
            if len(names) != len(cat.flavors[f]):
                raise ValueError(f"{len(names)} rows, flavor has {len(cat.flavors[f])}")
            top, _ = digests(names, lengths, sqs)
            if top != cat.recipes[f]["seqcol_digest"]:
                raise ValueError(f"seqcol {top} != catalog {cat.recipes[f]['seqcol_digest']}")
            print(f"OK   {f}: {len(names)} sequences, {sum(lengths):,} bp, {batches} batches "
                  f"(largest {biggest:,} bp), seqcol {top}, {time.time() - t0:.0f} s", flush=True)
        except Exception as e:  # report every flavor, then fail
            failed.append(f)
            print(f"FAIL {f}: {e}", flush=True)
    if failed:
        sys.exit(f"failed: {failed}")


if __name__ == "__main__":
    main()
