"""Golden tests: the pipeline's results against release 0.1.0.

Release 0.1.0 is immutable and its files are checked against catalog.json,
so it serves as the golden output. The recipe engine, run on the build's
tables, must give the release's flavor_sequences row for row, and every
recipe must reproduce its observation. These are the conformance tests a
reimplementation of the engine has to pass.

Needs the build (REFBOOK_CATALOG) and the release (REFBOOK_RELEASE); skipped
without them.
"""

import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

BUILD = Path(os.environ.get("REFBOOK_CATALOG", "/net/common/genomes/registry/build/grch38"))
RELEASE = Path(os.environ.get("REFBOOK_RELEASE", "/net/common/genomes/registry/catalog/0.1.0"))
RECIPES = sorted((Path(__file__).resolve().parent.parent / "recipes").glob("*.json"))
pytestmark = pytest.mark.skipif(
    not (BUILD / "roots.parquet").exists() or not (RELEASE / "catalog.json").exists(),
    reason="no build or release")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def recipes() -> list[dict]:
    return [r for path in RECIPES for r in json.loads(path.read_text())["recipes"]]


def golden(name: str) -> list[dict]:
    """A table of the release, after checking it against catalog.json."""
    path = RELEASE / name
    want = json.loads((RELEASE / "catalog.json").read_text())["files"][name]["sha256"]
    assert sha256(path) == want, f"{path} does not match catalog.json"
    return pq.read_table(path).to_pylist()


@pytest.fixture(scope="module")
def engine():
    import run_recipes
    rs = recipes()
    tables = run_recipes.load_tables(BUILD, rs)
    outputs = {r["flavor"]: run_recipes.run(
        r, BUILD, tables["members"], tables["roots"], tables["rank"], tables["masks"],
        tables["iupac"], tables["first_release"], tables["parent_start"],
        tables["external"], tables["parent_types"]) for r in rs}
    return run_recipes, rs, tables, outputs


def test_recipes_give_the_release_flavor_sequences(engine):
    _, rs, _, outputs = engine
    want = {}
    for row in golden("flavor_sequences.parquet"):
        want.setdefault(row["flavor"], []).append(row)
    assert set(outputs) == set(want)
    for flavor, rows in outputs.items():
        assert rows == sorted(want[flavor], key=lambda r: r["position"]), flavor


def test_every_recipe_reproduces_its_observation(engine):
    run_recipes, rs, tables, outputs = engine
    for r in rs:
        observed = pq.read_table(BUILD / "observed" / f"{r['flavor']}.parquet").to_pylist()
        assert run_recipes.compare(r, outputs[r["flavor"]], observed, tables["lower"],
                                   tables["assembly_of"]) == [], r["flavor"]


def test_seqcol_digests_match_the_release():
    from refbook import seqcol
    seqs = {}
    for row in golden("flavor_sequences.parquet"):
        seqs.setdefault(row["flavor"], []).append(row)
    for rec in golden("recipes.parquet"):
        rows = sorted(seqs[rec["flavor"]], key=lambda r: r["position"])
        top, level1 = seqcol.digests([r["name"] for r in rows], [r["length"] for r in rows],
                                     [r["sha512t24u"] for r in rows])
        assert (top, level1["names"], level1["lengths"], level1["sequences"]) == (
            rec["seqcol_digest"], rec["seqcol_names"], rec["seqcol_lengths"],
            rec["seqcol_sequences"]), rec["flavor"]


@pytest.mark.parametrize("root", ["J01415.2", "AJ507799.2", "KN707606.1", "KI270706.1"])
def test_root_bases_match_their_digests(root):
    from refbook import Catalog, refget
    from refbook.materialize import Bases
    bases = Bases(Catalog(RELEASE)).get(root)
    want = next(r for r in golden("roots.parquet") if r["root_id"] == root)
    assert refget.digests(bytes(bases)) == (want["md5"], want["sha512t24u"])
