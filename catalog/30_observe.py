"""Observe every target: what each published file was found to contain.

For every recipe, the target is the file it is checked against (its
`observed_from`, else `published`), found in raw/ at the path its URL
gives (01_fetch_targets.sh, or 00_fetch_inputs.sh for the GRC analysis sets,
which are inputs too). The file must match its entry in its lock
(catalog/assemblies/<assembly>/locks/targets.lock or inputs.lock: size and sha256). A FASTA is observed from its bases, a
.dict from its @SQ lines (see observe.py). Writes
build/grch38/30_observe/observed/<target>.parquet, whose schema
metadata records the target's provenance: its path, URL, size, sha256 and
Last-Modified from the lock, and the evidence, `content` (digests computed
from the bases) or `dict` (MD5s as the publisher claims them).

Observing every FASTA takes a while; --reuse keeps an observation from the
step's last run when it was made from the same bytes (the same sha256).

Usage: uv run python -I catalog/30_observe.py [--reuse] [--assembly A] [--raw DIR] [--build DIR]
"""

import argparse
import shutil
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout
from observe import observe, provenance, read_provenance

STEP = "30_observe"


def target_of(recipe: dict) -> str:
    """The path under raw/ of the file a recipe is checked against."""
    return recipe.get("observed_from", recipe["published"]).split("://", 1)[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true",
                    help="keep the last run's observation of a target whose bytes are unchanged")
    args = layout.arguments(ap)
    build = args.build
    raw = args.raw
    lock = {**layout.read_lock(layout.inputs_lock(args.assembly)), **layout.read_lock(layout.targets_lock(args.assembly))}
    recipes = layout.recipes(args.assembly)
    previous = build / STEP / "observed"
    with layout.step_output(build, STEP) as out:
        (out / "observed").mkdir()
        for r in recipes:
            rel = target_of(r)
            entry = lock.get(rel)
            if entry is None:
                sys.exit(f"{r['target']}: {rel} is in no lock (run the fetch steps)")
            src, dest = raw / rel, out / "observed" / f"{r['target']}.parquet"
            if (src.stat().st_size, layout.sha256(src)) != (int(entry["bytes"]), entry["sha256"]):
                sys.exit(f"{r['target']}: {rel} does not match its lock")
            old = previous / dest.name
            if args.reuse and old.exists() and read_provenance(old).get("sha256") == entry["sha256"]:
                shutil.copy2(old, dest)
                print(f"{r['target']}: reused (same bytes)", file=sys.stderr)
                continue
            table = observe(src)
            pq.write_table(table.replace_schema_metadata(provenance(entry)), dest, compression="zstd")
            print(f"{r['target']}: observed {src.name}", file=sys.stderr)
        layout.record_inputs(out, STEP, layout.inputs_lock(args.assembly), layout.targets_lock(args.assembly))


if __name__ == "__main__":
    main()
