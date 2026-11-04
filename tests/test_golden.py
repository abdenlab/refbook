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
    outputs = {r["flavor"]: run_recipes.run(r, BUILD, tables) for r in rs}
    return run_recipes, rs, tables, outputs


def observed(target: str) -> list[dict]:
    return pq.read_table(BUILD / "observed" / f"{target}.parquet").to_pylist()


def test_recipes_give_the_release_flavor_sequences(engine):
    """The recipes, in each target's observed order, give the release's rows."""
    run_recipes, rs, _, outputs = engine
    want = {}
    for row in golden("flavor_sequences.parquet"):
        want.setdefault(row["flavor"], []).append(row)
    assert set(outputs) == set(want)
    for flavor, rows in outputs.items():
        assert run_recipes.in_observed_order(rows, observed(flavor)) == sorted(
            want[flavor], key=lambda r: r["position"]), flavor


def test_every_recipe_reproduces_its_observation(engine):
    run_recipes, rs, tables, outputs = engine
    for r in rs:
        assert run_recipes.compare(outputs[r["flavor"]], observed(r["flavor"])) == [], r["flavor"]


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


# The flavor model (build_flavors.py) against the release's targets.

def table(name: str) -> list[dict]:
    return pq.read_table(BUILD / name).to_pylist()


needs_flavors = pytest.mark.skipif(not (BUILD / "flavors.parquet").exists(), reason="no flavors.parquet")


@needs_flavors
def test_targets_are_their_flavors_in_some_order():
    """Each release target, as a named sequence set, is its flavor's manifest."""
    from refbook import seqcol
    manifest = {}
    for r in table("manifests.parquet"):
        manifest.setdefault(r["flavor"], set()).add((r["name"], r["root_id"], r["length"], r["md5"], r["sha512t24u"]))
    target_rows = {}
    for r in golden("flavor_sequences.parquet"):
        target_rows.setdefault(r["flavor"], []).append(r)
    targets = {t["target"]: t for t in table("targets.parquet")}
    assert set(targets) == set(target_rows)
    for t, rows in target_rows.items():
        as_set = {(r["name"], r["root_id"], r["length"], r["md5"], r["sha512t24u"]) for r in rows}
        assert as_set == manifest[targets[t]["flavor"]], t
    for f in table("flavors.parquet"):
        rows = [r for r in table("manifests.parquet") if r["flavor"] == f["flavor"]]
        assert f["id"] == seqcol.named_set_digest([r["name"] for r in rows], [r["sha512t24u"] for r in rows])
        assert f["n_targets"] == sum(t["flavor"] == f["flavor"] for t in targets.values())


@needs_flavors
def test_target_orders_rebuild_the_release_collections():
    """A target's collection is its flavor's manifest in the target's order, with
    the release's seqcol digest."""
    from refbook import seqcol
    by_name = {(r["flavor"], r["name"]): r for r in table("manifests.parquet")}
    flavor_of = {t["target"]: t["flavor"] for t in table("targets.parquet")}
    order = {}
    for r in table("target_sequences.parquet"):
        order.setdefault(r["target"], []).append(r)
    released = {r["flavor"]: r["seqcol_digest"] for r in golden("recipes.parquet")}
    for t, rows in order.items():
        rows.sort(key=lambda r: r["position"])
        seqs = [by_name[flavor_of[t], r["name"]] for r in rows]
        top, _ = seqcol.digests([s["name"] for s in seqs], [s["length"] for s in seqs],
                                [s["sha512t24u"] for s in seqs])
        assert top == released[t], t
