"""Apply every recipe to the roots, and check each against its target.

A recipe defines a named sequence set: it has no order and no formatting (the
grammar is in engine.py). Reproduction is order-free: the recipe's sequences
must match the target's observation by name (same names, and for each the same
length and digests, where the observation has them). The target's order is
taken from its observation.

Writes REGISTRY/build/grch38/flavor_sequences.parquet (flavor, position, name,
root_id, length, md5, sha512t24u): each target's sequences, in the target's
observed order, from REGISTRY/build/grch38/observed/<target>.parquet (from
observe_fasta.py, or observe_dict.py, which gives only name, length and M5).
("flavor" there is still the target; build_flavors.py groups targets into
flavors.) Exits nonzero, writing nothing, if any target does not reproduce.

The output holds exactly the recipes given, so pass every recipe file.

Usage: uv run python -I pipeline/run_recipes.py REGISTRY_DIR recipes/*.json
"""

import argparse
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout
from engine import compare, in_observed_order, load_tables, run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("recipes", type=Path, nargs="+")
    args = ap.parse_args()
    build = layout.build_dir(args.registry)

    recipes = [r for path in args.recipes for r in json.loads(path.read_text())["recipes"]]
    flavors = [r["flavor"] for r in recipes]
    if len(flavors) != len(set(flavors)):
        sys.exit("a flavor is defined in more than one recipe")
    t = load_tables(build, recipes)

    rows, failed = [], []
    for recipe in recipes:
        got = run(recipe, build, t)
        observed = pq.read_table(build / "observed" / f"{recipe['flavor']}.parquet").to_pylist()
        errs = compare(got, observed)
        print(f"{recipe['flavor']}: {len(got)} sequences, "
              f"{'REPRODUCES' if not errs else f'{len(errs)} MISMATCHES'}", file=sys.stderr)
        for e in errs[:20]:
            print(f"  {e}", file=sys.stderr)
        if errs:
            failed.append(recipe["flavor"])
        else:
            rows += in_observed_order(got, observed)

    if failed:  # a flavor is cataloged only once it reproduces: write nothing
        sys.exit(f"not reproduced: {failed}")
    out = build / "flavor_sequences.parquet"
    tmp = out.with_suffix(".tmp")
    pq.write_table(pa.Table.from_pylist(rows), tmp, compression="zstd")
    tmp.replace(out)  # a new file: never rewrites one a release links to


if __name__ == "__main__":
    main()
