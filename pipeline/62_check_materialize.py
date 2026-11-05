"""Check, from the bases, that the library builds every sequence and collection.

40_recipes.py reuses a root's stored digest when a recipe leaves its bases
unchanged, so this rebuilds from root_blocks (and the IMGT/HLA release for
external roots) through the library, independently of the recipe engine:

1. Every derivation in the sequence store: each root's bases are read once,
   every known way of making a sequence from it is applied
   (refbook.materialize.apply_operations), and the result must have that
   sequence's MD5 and SQ. digests.
2. Every flavor and target: resolved through the library, each name must be a
   known sequence, and the seqcol digest computed from the store's digests
   must equal the catalog's.
3. One collection, streamed in full (--stream, default grch38-no-alt; or
   --stream-all for every flavor and target): schema, batches, and the seqcol
   digest recomputed from the materialized bases.

Step 1 covers every sequence of every collection, since collections are made
of the store's sequences; step 3 covers the stream.

Writes REGISTRY/build/grch38/62_check_materialize/check_materialize.json (the
result, with the sha256 of each input) and exits nonzero, after recording it,
on any failure.

Usage: uv run python -I pipeline/62_check_materialize.py REGISTRY_DIR [--stream NAME] [--stream-all] [--assembly grch38]
"""

import argparse
import hashlib
import sys
import time
from collections import defaultdict
from pathlib import Path

from refbook import Catalog, collection, materialize
from refbook.materialize import SCHEMA, Bases, apply_operations
from refbook.seqcol import digests, sha512t24u

STEP = "62_check_materialize"
INPUTS = ["sequences.parquet", "derivations.parquet", "flavors.parquet", "manifests.parquet",
          "targets.parquet", "target_sequences.parquet", "roots.parquet", "roots_external.parquet",
          "root_blocks.parquet", "layer_hardmask_grc.parquet", "collections"]

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout


def check_derivations(cat: Catalog, bases: Bases) -> list[str]:
    errors = []
    by_root = defaultdict(list)
    for sq, ways in cat.derivations.items():
        for d in ways:
            by_root[d["root_id"]].append((sq, d["operations"]))
    for root, ways in sorted(by_root.items()):
        raw = bytes(bases.get(root))
        for sq, ops in ways:
            b = apply_operations(cat, root, ops, bytearray(raw))
            rec = cat.sequence[sq]
            if (hashlib.md5(b).hexdigest(), "SQ." + sha512t24u(b), len(b)) != (rec["md5"], sq, rec["length"]):
                errors.append(f"{root} {ops}: does not give {sq}")
    return errors


def check_collections(cat: Catalog) -> list[str]:
    errors = []
    for name, want in [*((f, r["seqcol_digest"]) for f, r in cat.flavors.items()),
                       *((t, r["seqcol_digest"]) for t, r in cat.targets.items())]:
        try:
            if collection(cat, name).digest != want:
                errors.append(f"{name}: seqcol digest is not the catalog's {want}")
        except Exception as e:  # noqa: BLE001 - report every collection, then fail
            errors.append(f"{name}: {e}")
    return errors


def stream(cat: Catalog, name: str, want: str, bases: Bases) -> str:
    names, lengths, sqs, batches = [], [], [], 0
    reader = materialize(cat, name, bases=bases)
    if not reader.schema.equals(SCHEMA, check_metadata=False):
        raise ValueError(f"schema {reader.schema}")
    for batch in reader:
        batches += 1
        for n, seq in zip(batch.column("name").to_pylist(), batch.column("sequence")):
            b = seq.as_py().encode("ascii")
            names.append(n)
            lengths.append(len(b))
            sqs.append("SQ." + sha512t24u(b))
    top, _ = digests(names, lengths, sqs)
    if top != want:
        raise ValueError(f"seqcol {top} != catalog {want}")
    return f"{len(names)} sequences, {sum(lengths):,} bp, {batches} batches, seqcol {top}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("--stream", default="grch38-no-alt")
    ap.add_argument("--stream-all", action="store_true")
    ap.add_argument("--assembly", default=layout.ASSEMBLY)
    args = ap.parse_args()
    build = layout.build_dir(args.registry, args.assembly)
    with layout.step_output(build, STEP) as out:
        errors = run(build, out, args.stream, args.stream_all)
    if errors:
        sys.exit(f"{len(errors)} failures")


def run(build: Path, out: Path, stream_one: str, stream_all: bool) -> list[str]:
    cat = Catalog(build)
    bases = Bases(cat)
    want = {**{f: r["seqcol_digest"] for f, r in cat.flavors.items()},
            **{t: r["seqcol_digest"] for t, r in cat.targets.items()}}

    t0 = time.time()
    errors = check_derivations(cat, bases)
    n = sum(len(v) for v in cat.derivations.values())
    print(f"{'OK  ' if not errors else 'FAIL'} {n} derivations of {len(cat.sequence)} sequences "
          f"rebuilt, {time.time() - t0:.0f} s", flush=True)
    t0 = time.time()
    bad = check_collections(cat)
    print(f"{'OK  ' if not bad else 'FAIL'} {len(want)} collections (flavors and targets) resolve to "
          f"their seqcol digests, {time.time() - t0:.0f} s", flush=True)
    errors += bad
    for name in (sorted(want) if stream_all else [stream_one]):
        t0 = time.time()
        try:
            print(f"OK   streamed {name}: {stream(cat, name, want[name], bases)}, "
                  f"{time.time() - t0:.0f} s", flush=True)
        except Exception as e:  # noqa: BLE001 - report every collection, then fail
            errors.append(f"{name}: {e}")
            print(f"FAIL streamed {name}: {e}", flush=True)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    layout.record_check(build, out, "check_materialize", not errors, INPUTS,
                        {"errors": errors[:100], "derivations": n, "collections": len(want),
                         "streamed": sorted(want) if stream_all else [stream_one]})
    return errors


if __name__ == "__main__":
    main()
