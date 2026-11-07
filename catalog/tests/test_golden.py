"""Golden tests: the pipeline's results against release 0.1.0.

Release 0.1.0 is immutable and its files are checked against catalog.json,
so it serves as the golden output. The recipe engine, run on the build's
tables, must give the release's flavor_sequences (as reproduced.parquet is now) row for row, and every
recipe must reproduce its observation. These are the conformance tests a
reimplementation of the engine has to pass.

Needs a catalog (REFBOOK_CATALOG, else the repository's build; see under_test.py) and
the release (REFBOOK_RELEASE); skipped without them.
"""

import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from refbook_pipeline import engine
from under_test import CATALOG as BUILD
from under_test import observed as observed_path
from under_test import published, recipes, table

RELEASE = Path(os.environ.get("REFBOOK_RELEASE", "/net/common/genomes/registry/catalog/0.1.0"))
pytestmark = pytest.mark.skipif(
    not (BUILD / "catalog.json").exists() or not (RELEASE / "catalog.json").exists(),
    reason="no build or release")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def golden(name: str) -> list[dict]:
    """A table of the release, after checking it against catalog.json. Release 0.1.0 predates two
    renames: its flavor_sequences.parquet and recipes.parquet key rows by "flavor", which there means
    the target; that column is read as "target"."""
    path = RELEASE / name
    want = json.loads((RELEASE / "catalog.json").read_text())["files"][name]["sha256"]
    assert sha256(path) == want, f"{path} does not match catalog.json"
    rows = pq.read_table(path).to_pylist()
    return [{("target" if k == "flavor" else k): v for k, v in r.items()} for r in rows]


@pytest.fixture(scope="module")
def reproduced():
    rs = recipes()
    tables = engine.load_tables(engine.table_paths(published(), rs), rs)
    outputs = {r["target"]: engine.run(r, tables) for r in rs}
    return engine, rs, tables, outputs


def observed(target: str) -> list[dict]:
    return pq.read_table(observed_path(target)).to_pylist()


def test_recipes_give_the_release_target_sequences(reproduced):
    """The recipes, in each target's observed order, give the release's rows."""
    engine, _, _, outputs = reproduced
    want = {}
    for row in golden("flavor_sequences.parquet"):
        want.setdefault(row["target"], []).append(row)
    assert set(outputs) == set(want)
    for target, rows in outputs.items():
        assert engine.in_observed_order(rows, observed(target)) == sorted(
            want[target], key=lambda r: r["position"]), target


def test_the_core_compiles_like_the_frozen_python_engine(reproduced):
    """Every recipe, compiled by the Rust core, gives the frozen Python
    compiler's rows: the same names, roots and operations, in the same order."""
    import reference_engine
    engine, rs, tables, _ = reproduced
    for r in rs:
        assert engine.compile(r, tables) == reference_engine.compile(r, tables), r["target"]


def test_every_recipe_reproduces_its_observation(reproduced):
    engine, rs, _, outputs = reproduced
    for r in rs:
        assert engine.compare(outputs[r["target"]], observed(r["target"])) == [], r["target"]


def test_seqcol_digests_match_the_release():
    from refbook import seqcol
    seqs = {}
    for row in golden("flavor_sequences.parquet"):
        seqs.setdefault(row["target"], []).append(row)
    for rec in golden("recipes.parquet"):
        rows = sorted(seqs[rec["target"]], key=lambda r: r["position"])
        top, level1 = seqcol.digests([r["name"] for r in rows], [r["length"] for r in rows],
                                     [r["sha512t24u"] for r in rows])
        assert (top, level1["names"], level1["lengths"], level1["sequences"]) == (
            rec["seqcol_digest"], rec["seqcol_names"], rec["seqcol_lengths"],
            rec["seqcol_sequences"]), rec["target"]


@pytest.mark.parametrize("root", ["J01415.2", "AJ507799.2", "KN707606.1", "KI270706.1"])
def test_root_bases_match_their_digests(root):
    """The release's bases, read straight from its root_blocks (release 0.1.0 is
    catalog format 1, which the library no longer opens)."""
    from refbook import refget
    from refbook.blocks import row_groups_by_root
    f = pq.ParquetFile(RELEASE / "root_blocks.parquet")
    t = f.read_row_groups(row_groups_by_root(f)[root], columns=["start", "bases"])
    bases = "".join(b for _, b in sorted(zip(t["start"].to_pylist(), t["bases"].to_pylist()))).encode()
    want = next(r for r in golden("roots.parquet") if r["root_id"] == root)
    assert refget.digests(bases) == (want["md5"], want["sha512t24u"])


# The edition model (41_editions.py) against the release's targets.



def test_targets_are_their_editions_in_some_order():
    """Each release target, as a named sequence set, is its edition's manifest."""
    from refbook import seqcol
    manifest = {}
    for r in table("manifests.parquet"):
        manifest.setdefault(r["edition"], set()).add((r["name"], r["root_id"], r["length"], r["md5"], r["sha512t24u"]))
    target_rows = {}
    for r in golden("flavor_sequences.parquet"):
        target_rows.setdefault(r["target"], []).append(r)
    targets = {t["target"]: t for t in table("targets.parquet")}
    assert set(targets) == set(target_rows)
    for t, rows in target_rows.items():
        as_set = {(r["name"], r["root_id"], r["length"], r["md5"], r["sha512t24u"]) for r in rows}
        assert as_set == manifest[targets[t]["edition"]], t
    for f in table("editions.parquet"):
        rows = [r for r in table("manifests.parquet") if r["edition"] == f["edition"]]
        assert f["id"] == seqcol.named_set_digest([r["name"] for r in rows], [r["sha512t24u"] for r in rows])
        assert f["n_targets"] == sum(t["edition"] == f["edition"] for t in targets.values())


def test_target_orders_rebuild_the_release_collections():
    """A target's collection is its edition's manifest in the target's order, with
    the release's seqcol digest."""
    from refbook import seqcol
    by_name = {(r["edition"], r["name"]): r for r in table("manifests.parquet")}
    edition_of = {t["target"]: t["edition"] for t in table("targets.parquet")}
    order = {}
    for r in table("target_sequences.parquet"):
        order.setdefault(r["target"], []).append(r)
    released = {r["target"]: r["seqcol_digest"] for r in golden("recipes.parquet")}
    for t, rows in order.items():
        rows.sort(key=lambda r: r["position"])
        seqs = [by_name[edition_of[t], r["name"]] for r in rows]
        top, _ = seqcol.digests([s["name"] for s in seqs], [s["length"] for s in seqs],
                                [s["sha512t24u"] for s in seqs])
        assert top == released[t], t
