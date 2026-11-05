"""Command line: `refbook identify FILE...`, `refbook populate-ref-cache FILE... --root DIR`, `refbook serve`."""

import argparse
import json
import os
import sys
from pathlib import Path

from refbook.catalog import Catalog
from refbook.identify import describe, identify
from refbook.parse import read_header
from refbook.refcache import populate_ref_cache

# The published release; set REFBOOK_CATALOG (or --catalog) to a local copy or another release.
DEFAULT_CATALOG = "https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/"


def report(path: str, cat: Catalog, as_json: bool) -> dict:
    header = read_header(path)
    res = identify(header, cat)
    out = {
        "file": path, "format": header.format, "sequences": len(header.entries),
        "has_md5": header.has_md5,
        "matches": [{"flavor": c.flavor, "verdict": c.verdict, "score": round(c.score, 4),
                     "in_order_of": [{"target": t, "publisher": cat.targets[t]["publisher"],
                                      "alias": cat.targets[t]["alias"],
                                      "published": cat.targets[t]["published"]} for t in c.in_order_of],
                     "differences": describe(c, cat)} for c in res.best],
        "unknown_sequences": res.unknown,
        "seqcol_digest": res.seqcol_digest, "seqcol_matches": res.seqcol_matches,
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
        _orders(res, cat)
    elif verdict == "consistent":
        print(f"  CONSISTENT (names and lengths; no MD5s to check bases): "
              f"{', '.join(c.flavor for c in res.best)}")
        for a in res.ambiguity:
            print(f"    {a}")
        _orders(res, cat)
    elif verdict == "contains":
        c = res.best[0]
        print(f"  CONTAINS {', '.join(x.flavor for x in res.best)} (all {c.matched} sequences, unchanged), "
              f"plus {len(c.extra)} others")
        for d in describe(c, cat):
            print(f"    - {d}")
    elif verdict == "subset":
        names = [x.flavor for x in res.best]
        shown = ", ".join(names[:6]) + (f", and {len(names) - 6} more" if len(names) > 6 else "")
        print(f"  SUBSET of {len(names)} flavors (every sequence unchanged): {shown}")
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
    if res.unknown:
        print(f"  {len(res.unknown)} sequences unknown to the catalog, e.g. {', '.join(res.unknown[:3])}")
    if res.seqcol_digest:
        also = f" = {', '.join(res.seqcol_matches)}" if res.seqcol_matches else ""
        print(f"  seqcol digest: {res.seqcol_digest}{also}")
    return out


def _orders(res, cat: Catalog) -> None:
    """Which targets' order the header follows, per matching flavor."""
    for c in res.best:
        if c.in_order_of:
            ts = "; ".join(f"{cat.targets[t]['publisher']} {cat.targets[t]['alias']}" for t in c.in_order_of)
            print(f"    {c.flavor}: in the order of {ts}")
        else:
            print(f"    {c.flavor}: in an order none of its targets uses")


def main() -> None:
    ap = argparse.ArgumentParser(prog="refbook")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("identify", help="identify a .fai, .dict/SAM header, BAM, VCF or FASTA")
    p.add_argument("files", nargs="+")
    p.add_argument("--catalog", default=os.environ.get("REFBOOK_CATALOG", DEFAULT_CATALOG))
    p.add_argument("--json", action="store_true")
    q = sub.add_parser("populate-ref-cache",
                       help="fill htslib's REF_CACHE with the sequences a CRAM/BAM/SAM header names by M5")
    q.add_argument("files", nargs="+", help="CRAM, BAM, SAM header or .dict files, or bare MD5s")
    q.add_argument("--root", required=True, help="cache root; then use REF_CACHE=ROOT/%%2s/%%2s/%%s")
    q.add_argument("--catalog", default=os.environ.get("REFBOOK_CATALOG", DEFAULT_CATALOG))
    s = sub.add_parser("serve", help="serve the catalog over refget Sequences v2 and Sequence Collections v1")
    s.add_argument("--catalog", default=os.environ.get("REFBOOK_CATALOG", DEFAULT_CATALOG))
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--collections", nargs="*", default=[], metavar="JSON",
                   help="extra level-2 collections to serve (seqcol endpoints only), e.g. test data")
    args = ap.parse_args()
    cat = Catalog(args.catalog)
    if args.cmd == "serve":
        from refbook.service import Service, serve
        extra = [json.loads(Path(f).read_text()) for f in args.collections]
        server = serve(Service(cat, extra), args.host, args.port)
        print(f"serving {args.catalog} on http://{args.host}:{server.server_port}/", file=sys.stderr)
        server.serve_forever()
        return
    if args.cmd == "populate-ref-cache":
        md5s = []
        for f in args.files:
            if len(f) == 32 and all(c in "0123456789abcdefABCDEF" for c in f) and not os.path.exists(f):
                md5s.append(f)
                continue
            header = read_header(f)
            missing = [e.name for e in header.entries if not e.md5]
            if missing:
                print(f"{f}: {len(missing)} sequences have no M5, e.g. {missing[0]}", file=sys.stderr)
            md5s += [e.md5 for e in header.entries if e.md5]
        r = populate_ref_cache(cat, md5s, args.root)
        print(f"wrote {len(r['written'])}, already present {len(r['present'])}, "
              f"unknown to the catalog {len(r['unknown'])}" +
              (f" (e.g. {r['unknown'][0]}; htslib falls back to REF_PATH for these)" if r["unknown"] else ""))
        print(f"use: REF_CACHE={args.root}/%2s/%2s/%s")
        return
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
