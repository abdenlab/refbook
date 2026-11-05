"""Observe every target: what each published file was found to contain.

For every recipe, the target is the file it is checked against (its
`observed_from`, else `published`), found in REGISTRY/raw at the path its URL
gives (01_fetch_targets.sh). A FASTA is observed from its bases, a .dict from
its @SQ lines (see observe.py). Writes REGISTRY/build/grch38/30_observe/observed/
<target>.parquet. Observing every FASTA takes a while; --reuse copies the
observations of the step's last run instead, for targets whose files have not
changed since.

Usage: uv run python -I pipeline/30_observe.py REGISTRY_DIR recipes/*.json [--reuse] [--assembly grch38]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout
from observe import observe

STEP = "30_observe"


def target_path(raw: Path, recipe: dict) -> Path:
    url = recipe.get("observed_from", recipe["published"])
    return raw / url.split("://", 1)[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("recipes", type=Path, nargs="+")
    ap.add_argument("--reuse", action="store_true",
                    help="copy the last run's observations instead of observing again")
    ap.add_argument("--assembly", default=layout.ASSEMBLY)
    args = ap.parse_args()
    build = layout.build_dir(args.registry, args.assembly)
    raw = layout.raw_dir(args.registry)
    recipes = [r for p in args.recipes for r in json.loads(p.read_text())["recipes"]]
    previous = build / STEP / "observed"
    with layout.step_output(build, STEP) as out:
        (out / "observed").mkdir()
        for r in recipes:
            dest = out / "observed" / f"{r['flavor']}.parquet"
            if args.reuse and (previous / dest.name).exists():
                shutil.copy2(previous / dest.name, dest)
                print(f"{r['flavor']}: reused", file=sys.stderr)
                continue
            src = target_path(raw, r)
            pq.write_table(observe(src), dest, compression="zstd")
            print(f"{r['flavor']}: observed {src.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
