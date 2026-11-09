"""The wasm build of the core (js/) against the Python build of the same core.

Runs js/test/oracle.ts under Node on the same inputs given to refbook._core:
random sequences, every stored collection (digests, levels, and every pair
compared), every recipe on the build's tables, and identify on every
manifest sequence. Skipped without Node or a built js/pkg (pnpm build).
"""

import base64
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest
from refbook_pipeline import books, engine, layout
from under_test import CATALOG as BUILD
from under_test import file, published

from refbook import _core

JS = layout.REPO / "js"
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (JS / "pkg" / "refbook_wasm_bg.wasm").exists(),
    reason="no node or no wasm build")


def run_wasm(tmp_path: Path, request: dict) -> dict:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    out = subprocess.run(["node", str(JS / "test" / "oracle.ts"), str(path)],
                         capture_output=True, check=True, cwd=JS)
    return json.loads(out.stdout)


def random_sequences(n: int, seed: int = 13):
    rng = random.Random(seed)
    alphabet = b"ACGTNacgtnRYKMSWBDHVrykmswbdhv \n" + bytes(range(0, 128, 9))
    for _ in range(n):
        yield bytes(rng.choice(alphabet) for _ in range(rng.randrange(0, 200)))


@pytest.mark.skipif(not (BUILD / "catalog.json").exists(), reason="no build")
def test_wasm_agrees_on_sequences_and_collections(tmp_path):
    seqs = [_core.remove_whitespace(s) for s in random_sequences(1000)]
    collections = [json.loads(p.read_text()) for p in sorted(
        file("collections").glob("*.json"))]
    collections = [{k: c[k] for k in ("names", "lengths", "sequences")} for c in collections]
    collections.append({"names": ["chr1", "é\"x"], "lengths": [1, 2], "sequences": ["SQ.a", "SQ.b"]})
    got = run_wasm(tmp_path, {"sequences": [base64.b64encode(s).decode() for s in seqs],
                              "collections": collections, "tables": None, "recipes": []})
    for seq, w in zip(seqs, got["scans"]):
        try:
            p = _core.scan(seq)
        except ValueError as e:
            assert w == {"error": str(e)}, seq
            continue
        w = w["ok"]
        assert w["bases"].encode("latin1") == p["bases"]
        assert (w["md5"], w["sha512t24u"]) == (p["md5"], p["sha512t24u"]) == tuple(w["digests"])
        assert [tuple(x) for x in w["lower"]] == p["lower"]
        assert [tuple(x) for x in w["n_runs"]] == p["n_runs"]
        assert [tuple(x) for x in w["iupac"]] == p["iupac"]
    for c, w in zip(collections, got["collections"]):
        top, level1 = _core.seqcol_digests(c["names"], c["lengths"], c["sequences"])
        assert (w["digest"], w["level1"]) == (top, level1)
        assert w["ancillary"] == _core.seqcol_ancillary(c["names"], c["lengths"], c["sequences"])
        assert w["named_set"] == _core.named_set_digest(c["names"], c["sequences"])
        assert w["level1_attributes"] == _core.seqcol_level1(c["names"], c["lengths"], c["sequences"])
        assert w["level2"] == _core.seqcol_level2(c["names"], c["lengths"], c["sequences"])
    for a, row in zip(got["collections"], got["comparisons"]):
        for b, w in zip(got["collections"], row):
            assert w == json.loads(_core.seqcol_compare(a["level2"], b["level2"]))


@pytest.mark.skipif(not (BUILD / "catalog.json").exists(), reason="no build")
@pytest.mark.parametrize("book", ["grch37", "grch38", "t2t-chm13"])
def test_wasm_compiles_every_recipe_like_python(tmp_path, book):
    rs = books.recipes(layout.BOOKS, book)
    t = engine.load_tables(engine.table_paths(published(), rs), rs, book)
    tables = {
        "members": t["members"], "roots": list(t["roots"]),
        "iupac": [acc for acc, r in t["roots"].items() if r["n_iupac"]],
        "layers": {name: list(by_root) for name, by_root in t["spans"].items()},
        "external": t["external"],
        "placements": [{"root_id": acc, "parent_type": p} for acc, ps in t["parent_types"].items() for p in ps],
        "padding": [{"root_id": acc, "revised": p["revised"], "orientation": p["orientation"]}
                    for acc, p in t["padding"].items()],
    }
    got = run_wasm(tmp_path, {"sequences": [], "collections": [], "tables": tables, "recipes": rs})
    assert len(got["compiled"]) == len(rs) > 0
    for r in rs:
        want = [{"name": n, "root_id": acc, "operations": ops} for n, acc, ops in engine.compile(r, t)]
        assert got["compiled"][r["target"]] == {"ok": want}, r["target"]


@pytest.mark.skipif(not (BUILD / "catalog.json").exists(), reason="no build")
def test_wasm_identifies_like_python(tmp_path):
    import pyarrow.parquet as pq

    from refbook import Catalog
    cat = Catalog(BUILD)
    aliases = pq.read_table(cat.file("aliases.parquet"), columns=["root_id", "alias"]).to_pylist()
    tables = {
        "sequences": [{"sha512t24u": sq, **{k: r[k] for k in ("md5", "length", "root_id", "operations")}}
                      for sq, r in cat.sequence.items()],
        "roots": [{"root_id": r, "length": n} for r, n in cat.root_length.items()],
        "aliases": aliases,
        "manifests": [{"edition": f, "name": s.name, "sha512t24u": s.sha512t24u}
                      for f, seqs in cat.manifests.items() for s in seqs],
    }
    seqs = [s for seqs in cat.manifests.values() for s in seqs]
    entries = ([{"name": s.name, "length": s.length} for s in seqs] +
               [{"md5": s.md5, "name": s.name} for s in seqs[:500]] +
               [{"name": "chr1", "length": 5}, {"sq": "SQ.unknown"}, {}])
    got = run_wasm(tmp_path, {"sequences": [], "collections": [], "tables": None, "recipes": [],
                              "identify": {"tables": tables, "entries": entries}})
    rows = [(e.get("name"), e.get("length"), e.get("md5"), e.get("sq")) for e in entries]
    assert got["identified"] == json.loads(_core.identify_sequences(rows, cat.identify_tables()))


def test_wasm_pads_like_python(tmp_path):
    rng = random.Random(29)
    pads = []
    for _ in range(300):
        n = rng.randrange(0, 60)
        p = (rng.randrange(0, 40), n, rng.randrange(0, 40), rng.random() < 0.5)
        total = sum(p[:3])
        start = rng.randrange(0, total + 1)
        end = rng.randrange(start, total + 1)
        a, z = _core.pad_root_range(start, end, p)
        bases = bytes(rng.choice(b"ACGTNRYKMSWBDHV") for _ in range(z - a))
        pads.append({"bases": base64.b64encode(bases).decode(), "start": start, "end": end,
                     "padding": dict(zip(("before", "root_length", "after", "reverse"), p))})
    pads.append({**pads[0], "bases": base64.b64encode(b"ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTA").decode()})
    got = run_wasm(tmp_path, {"sequences": [], "collections": [], "tables": None, "recipes": [], "pads": pads})
    for q, w in zip(pads, got["pads"]):
        p = tuple(q["padding"][k] for k in ("before", "root_length", "after", "reverse"))
        try:
            want = _core.pad(base64.b64decode(q["bases"]), q["start"], q["end"], p)
        except ValueError as e:
            assert "error" in w and str(e) == w["error"]
            continue
        assert tuple(w["ok"]["range"]) == _core.pad_root_range(q["start"], q["end"], p)
        assert w["ok"]["bases"].encode("latin1") == want
