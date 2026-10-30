"""Command line: `ref-registry identify FILE... [--catalog DIR] [--json]`."""

import argparse
import json
import os
import sys

from ref_registry.catalog import Catalog
from ref_registry.identify import describe, identify
from ref_registry.parse import read_header

DEFAULT_CATALOG = "/net/common/genomes/registry/build/grch38"


def report(path: str, cat: Catalog, as_json: bool) -> dict:
    header = read_header(path)
    res = identify(header, cat)
    out = {
        "file": path, "format": header.format, "sequences": len(header.entries),
        "has_md5": header.has_md5,
        "matches": [{"flavor": c.flavor, "verdict": c.verdict, "score": round(c.score, 4),
                     "published": cat.recipes[c.flavor]["published"],
                     "differences": describe(c, cat)} for c in res.best],
        "seqcol_digest": res.seqcol_digest, "seqcol_flavors": res.seqcol_flavors,
        "ambiguity": res.ambiguity,
        "runners_up": [{"flavor": c.flavor, "score": round(c.score, 4)}
                       for c in res.ranked[len(res.best):len(res.best) + 3]],
    }
    if as_json:
        return out
    print(f"{path}\n  {header.format}, {len(header.entries)} sequences, "
          f"{'with' if header.has_md5 else 'without'} MD5s")
    verdict = res.best[0].verdict if res.best else "none"
    if verdict == "exact":
        print(f"  EXACT: {', '.join(c.flavor for c in res.best)}")
    elif verdict == "consistent":
        print(f"  CONSISTENT (names, lengths and order; no MD5s to check bases): "
              f"{', '.join(c.flavor for c in res.best)}")
        for a in res.ambiguity:
            print(f"    {a}")
    elif verdict == "contains":
        c = res.best[0]
        print(f"  CONTAINS {', '.join(x.flavor for x in res.best)} (all {c.matched} sequences, unchanged), "
              f"plus {len(c.extra)} others")
        for d in describe(c, cat):
            print(f"    - {d}")
    elif verdict == "subset":
        names = [x.flavor for x in res.best]
        shown = ", ".join(names[:6]) + (f", and {len(names) - 6} more" if len(names) > 6 else "")
        print(f"  SUBSET of {len(names)} flavors (every sequence unchanged, in order): {shown}")
        print(f"    smallest: {names[0]}, which also has: "
              + "; ".join(d for d in describe(res.best[0], cat) if d.startswith("not in header"))[15:])
        if not header.has_md5:
            print("    (no MD5s: sequences are matched by name and length only)")
    else:
        c = res.best[0]
        label = "CLOSEST" if c.matched * 2 >= len(header.entries) else "NO GOOD MATCH; closest"
        print(f"  {label}: {c.flavor} ({c.matched} of {len(header.entries)} sequences match, "
              f"score {c.score:.3f})")
        if not header.has_md5:
            print("    (no MD5s: sequences are matched by name and length only)")
        for d in describe(c, cat):
            print(f"    - {d}")
    if res.seqcol_digest:
        also = f" = {', '.join(res.seqcol_flavors)}" if res.seqcol_flavors else ""
        print(f"  seqcol digest: {res.seqcol_digest}{also}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="ref-registry")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("identify", help="identify a .fai, .dict/SAM header, BAM, VCF or FASTA")
    p.add_argument("files", nargs="+")
    p.add_argument("--catalog", default=os.environ.get("REF_REGISTRY_CATALOG", DEFAULT_CATALOG))
    p.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cat = Catalog(args.catalog)
    results = []
    for f in args.files:
        try:
            results.append(report(f, cat, args.json))
        except (ValueError, OSError) as e:
            print(f"{f}: {e}", file=sys.stderr)
    if args.json:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
