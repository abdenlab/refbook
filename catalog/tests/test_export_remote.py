"""A release made by the export, served over HTTP and read by the library:
the same answers as reading it locally, with few requests.

Needs a catalog (REFBOOK_CATALOG, else the repository's build; see under_test.py).
"""

from pathlib import Path

from refbook_pipeline import export, layout
from under_test import needs_catalog, published

from refbook.parse import read_header

FIXTURES = layout.REPO / "python" / "tests" / "fixtures"


def release_from_build(out: Path) -> Path:
    """A format-2 release of the catalog, by symlink: the export's file list and
    a catalog.json with real hashes, without copying the bases."""
    import json

    files = {}
    for name, src in published().items():
        role = export.role(name)
        for f in ([src] if src.is_file() else sorted(src.glob("*"))):
            rel = f"{name}/{f.name}" if src.is_dir() else name
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).symlink_to(f)
            files[rel] = {"bytes": f.stat().st_size, "sha256": export.sha256(f), "role": role}
    (out / "catalog.json").write_text(json.dumps({"name": "refbook", "format": export.FORMAT,
                                                  "version": "test", "files": files}))
    return out


@needs_catalog
def test_remote_catalog_over_http(tmp_path):
    """Open a release by URL from a local Range-honoring server; compare with local."""
    import threading

    import pyarrow as pa

    from refbook import Catalog, fetch, identify
    from refbook._serve import serve
    release = release_from_build(tmp_path / "release")
    server = serve(str(release), port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        remote, local = Catalog(url, cache=tmp_path / "cache"), Catalog(release)
        assert remote.manifest["version"] == local.manifest["version"] == "test"
        assert not (tmp_path / "cache" / "catalog" / "test" / "root_blocks.parquet").exists()
        res = identify(read_header(FIXTURES / "giab_HG002_GRCh38_v4.2.1.vcf"), remote)
        assert res.best[0].verdict == "consistent"
        iv = pa.table({"chrom": ["chr1", "chrY", "chrM"], "start": [1_000_000, 10_000, 0],
                       "end": [1_000_100, 10_050, 16569]})
        got = fetch(remote, "grch38-no-alt", iv)  # auto -> pyarrow over plain http
        want = fetch(local, "grch38-no-alt", iv, engine="pyarrow")
        assert got["sequence"].to_pylist() == want["sequence"].to_pylist()
        assert 0 < remote.blocks_http.requests < 20
    finally:
        server.shutdown()
