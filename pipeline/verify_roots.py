"""Check the root digests against two independent sources.

1. ENA's refget server (its own copy of INSDC): GET /sequence/{md5}/metadata
   must exist and report the same length.
2. GRC analysis-set FASTA deflines, which carry `AC:<accession.version>` and
   `M5:<md5>` per sequence. For sequences the GRC did not mask, M5 must equal
   our MD5; for the ones it masks (the roots in layer_hardmask_grc: chr5, 14,
   19, 21, 22, Y) it must differ. Pass a *_plus_hs38d1_analysis_set to also
   cover the decoys and EBV.

Writes REGISTRY/build/grch38/verify_roots.tsv and prints a summary. Exits
nonzero if any root is absent from ENA or has another length there, or if
any GRC M5 is unexpected.

Usage: uv run python -I pipeline/verify_roots.py REGISTRY_DIR ANALYSIS_SET_FNA_GZ
"""

import gzip
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq

from refbook.remote import USER_AGENT

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout

ENA = "https://www.ebi.ac.uk/ena/cram/sequence/{}/metadata"


def ena_length(md5: str) -> int | None:
    req = urllib.request.Request(ENA.format(md5), headers={"User-Agent": USER_AGENT})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                meta = json.load(r)["metadata"]
                return meta.get("length")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError):
            pass
    raise RuntimeError(f"ENA unreachable for {md5}")


def grc_m5(path: Path) -> dict[str, str]:
    out = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith(">"):
                ac = re.search(r"\bAC:(\S+)", line)
                m5 = re.search(r"\bM5:([0-9a-f]{32})", line)
                if ac and m5:
                    out[ac.group(1)] = m5.group(1)
    return out


def status(length: int, md5: str, ena_length: int | None, grc_md5: str | None,
           masked: bool) -> tuple[str, str, bool]:
    """(ENA result, GRC result, passed) for one root. ENA must hold our MD5 at
    our length; the GRC's M5 must equal ours unless the GRC masks the root, and
    then it must differ. A root not in the analysis set passes on ENA alone."""
    ena = "absent" if ena_length is None else ("ok" if ena_length == length else f"length {ena_length}")
    if grc_md5 is None:
        grc = "not in set"
    elif grc_md5 == md5:
        grc = "match" + (" (UNEXPECTED: masked by the GRC)" if masked else "")
    else:
        grc = "differs" + ("" if masked else " (UNEXPECTED)")
    return ena, grc, ena == "ok" and "UNEXPECTED" not in grc


def main() -> None:
    registry, analysis = Path(sys.argv[1]), Path(sys.argv[2])
    build = layout.build_dir(registry)
    roots = pq.read_table(build / "roots.parquet").to_pylist()

    with ThreadPoolExecutor(8) as pool:
        ena = dict(zip((r["root_id"] for r in roots),
                       pool.map(ena_length, (r["md5"] for r in roots))))
    grc = grc_m5(analysis)
    masked = set(pq.read_table(build / "layer_hardmask_grc.parquet", columns=["root_id"])
                 ["root_id"].to_pylist())

    counts, failed = {}, []
    tsv = build / "verify_roots.tsv"
    tmp = tsv.with_suffix(".tmp")
    with open(tmp, "w") as out:
        out.write("root_id\tlength\tmd5\tena\tgrc_analysis_set\n")
        for r in roots:
            acc = r["root_id"]
            ena_s, grc_s, ok = status(r["length"], r["md5"], ena[acc], grc.get(acc), acc in masked)
            for k in (f"ena:{ena_s}", f"grc:{grc_s}"):
                counts[k] = counts.get(k, 0) + 1
            out.write(f"{acc}\t{r['length']}\t{r['md5']}\t{ena_s}\t{grc_s}\n")
            if not ok:
                failed.append(acc)
    tmp.replace(tsv)  # a new file: never rewrites one a release links to
    for k, v in sorted(counts.items()):
        print(f"{v:5d}  {k}")
    if failed:
        sys.exit(f"{len(failed)} roots failed verification, e.g. {failed[:5]}")


if __name__ == "__main__":
    main()
