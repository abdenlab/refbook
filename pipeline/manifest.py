"""Write a provenance manifest for everything under REGISTRY/raw.

One row per file: source URL (reconstructed from the path), size, sha256 and
mtime (wget -N sets it to the server's Last-Modified). Standard library only.

Usage: python3 manifest.py REGISTRY_DIR > manifest.tsv
"""

import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_url(rel: Path) -> str:
    # efetch results are saved under a synthetic name; the rest mirror the URL.
    parts = rel.parts
    if parts[0] == "eutils.ncbi.nlm.nih.gov":
        acc = rel.stem.removeprefix("nuccore_")
        return (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=nuccore&id={acc}&rettype=fasta&retmode=text"
        )
    return "https://" + "/".join(parts)


def main() -> None:
    raw = Path(sys.argv[1]) / "raw"
    print("url\tpath\tsize\tsha256\tmtime")
    for root, _, files in sorted(os.walk(raw)):
        for name in sorted(files):
            path = Path(root) / name
            rel = path.relative_to(raw)
            st = path.stat()
            mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
            print(f"{source_url(rel)}\t{rel}\t{st.st_size}\t{sha256(path)}\t{mtime}")


if __name__ == "__main__":
    main()
