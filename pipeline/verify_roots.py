"""Check the GRCh38 root digests against two independent sources.

1. ENA's refget server (its own copy of INSDC): GET /sequence/{md5}/metadata
   must exist and report the same length.
2. GRC analysis-set FASTA deflines, which carry `AC:<accession.version>` and
   `M5:<md5>` per sequence. For sequences the GRC did not mask, M5 must equal
   our MD5; for the ones it documents as masked (chr5, 14, 19, 21, 22, Y) it
   must differ.

Writes REGISTRY/build/grch38/verify_roots.tsv and prints a summary.

Usage: uv run --with pyarrow python verify_roots.py REGISTRY_DIR ANALYSIS_SET_FNA_GZ
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

ENA = "https://www.ebi.ac.uk/ena/cram/sequence/{}/metadata"
GRC_MASKED = {"CM000667.2", "CM000676.2", "CM000681.2", "CM000683.2",
              "CM000684.2", "CM000686.2"}  # chr5, 14, 19, 21, 22, Y


def ena_length(md5: str) -> int | None:
    req = urllib.request.Request(ENA.format(md5), headers={"User-Agent": "composeq-assembly-registry"})
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


def main() -> None:
    registry, analysis = Path(sys.argv[1]), Path(sys.argv[2])
    build = registry / "build" / "grch38"
    roots = pq.read_table(build / "roots.parquet").to_pylist()

    with ThreadPoolExecutor(8) as pool:
        ena = dict(zip((r["root_id"] for r in roots),
                       pool.map(ena_length, (r["md5"] for r in roots))))
    grc = grc_m5(analysis)

    counts = {}
    with open(build / "verify_roots.tsv", "w") as out:
        out.write("root_id\tlength\tmd5\tena\tgrc_analysis_set\n")
        for r in roots:
            acc = r["root_id"]
            e = ena[acc]
            ena_s = "absent" if e is None else ("ok" if e == r["length"] else f"length {e}")
            if acc not in grc:
                grc_s = "not in set"
            elif grc[acc] == r["md5"]:
                grc_s = "match" + (" (UNEXPECTED: documented as masked)" if acc in GRC_MASKED else "")
            else:
                grc_s = "differs" + ("" if acc in GRC_MASKED else " (UNEXPECTED)")
            for k in (f"ena:{ena_s}", f"grc:{grc_s}"):
                counts[k] = counts.get(k, 0) + 1
            out.write(f"{acc}\t{r['length']}\t{r['md5']}\t{ena_s}\t{grc_s}\n")
    for k, v in sorted(counts.items()):
        print(f"{v:5d}  {k}")


if __name__ == "__main__":
    main()
