"""The build's index, and the export: a release made of the published tables, gated on the checks.

The catalog's tables are built in output/build/catalog/<task>/; the index (output/build/catalog/catalog.json) maps
each published name to its file there, so refbook.Catalog opens a build without copying anything. An export copies
(never links) the published files into a fresh directory, in a release's flat layout, with catalog.json (format 2:
every file's size, sha256 and role; the checks' results; the hash of every lock), the evidence (each target's
observation, the checks' reports, the locks) and the dataset card. It refuses unless every check passed on exactly
the files it ships, every task that read raw/ read it through the current locks, and (for a release, not a
development export) the root check consulted ENA. A release is never overwritten.
"""

from __future__ import annotations

import datetime
import json
import shutil
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from . import Refused
from .checks import sha256

FORMAT = 2
# Published names: the task directory (under build/catalog/) that writes each, and its role in a release.
PUBLISHED = {
    "roots.parquet": ("roots", "roots"), "roots_external.parquet": ("external", "roots"),
    "root_blocks.parquet": ("roots", "bases"),
    "assembly_members.parquet": ("members", "assemblies"),
    "aliases.parquet": ("aliases", "aliases"), "sequence_aliases.parquet": ("aliases", "aliases"),
    "layer_agp.parquet": ("layers", "layer"), "layer_regions.parquet": ("layers", "layer"),
    "layer_placements.parquet": ("layers", "layer"), "layer_hardmask_grc.parquet": ("layers", "layer"),
    "layer_iupac.parquet": ("roots", "layer"), "layer_n_runs.parquet": ("roots", "layer"),
    "layer_softmask_ncbi.parquet": ("roots", "layer"),
    "sequences.parquet": ("editions", "sequences"), "derivations.parquet": ("editions", "sequences"),
    "editions.parquet": ("editions", "editions"), "manifests.parquet": ("editions", "editions"),
    "targets.parquet": ("editions", "targets"), "target_sequences.parquet": ("editions", "targets"),
    "collections": ("editions", "collections"),
}
CHECKS = ["check_gaps", "check_roots", "check_materialize"]


def published(catalog: Path) -> dict[str, Path]:
    """Each published name's file (or directory) in the build."""
    return {name: catalog / task / name for name, (task, _) in PUBLISHED.items()}


def write_index(catalog: Path) -> None:
    """catalog.json for a build: every published file by the name a release gives it, with its path."""
    files = {}
    for name, path in published(catalog).items():
        for f in sorted(path.glob("*")) if path.is_dir() else [path]:
            if not f.is_file():
                raise Refused(f"{name}: not built ({f})")
            rel = f"{name}/{f.name}" if path.is_dir() else name
            files[rel] = {"path": f.relative_to(catalog).as_posix(), "bytes": f.stat().st_size}
    index = {"name": "refbook", "format": FORMAT, "version": "build", "build": True, "files": files}
    tmp = catalog / ".catalog.json.partial"
    tmp.write_text(json.dumps(index, indent=1) + "\n")
    tmp.replace(catalog / "catalog.json")


def gate(catalog: Path, checks: dict[str, Path], lock_paths: list[Path], development: bool) -> tuple[dict, list[str]]:
    """Each check's recorded result, and why the build can't be exported, if it can't."""
    results, problems = {}, []
    files = published(catalog)
    for check, path in checks.items():
        if not path.exists():
            problems.append(f"{check}: has not run")
            continue
        r = results[check] = json.loads(path.read_text())
        if not r["passed"]:
            problems.append(f"{check}: failed")
        for name, digest in r["inputs"].items():
            if name in files and (not files[name].exists() or sha256(files[name]) != digest):
                problems.append(f"{check}: {name} has changed since the check ran; rerun it")
        if r["details"].get("ena") == "skipped" and not development:
            problems.append(f"{check}: ran without ENA; run `doit check_roots_ena`, or export --development")
    current = {p.name: sha256(p) for p in lock_paths}
    for f in sorted(catalog.parent.rglob("inputs.json")):
        for name, digest in json.loads(f.read_text()).items():
            if current.get(name) != digest:
                problems.append(f"{f.parent.relative_to(catalog.parent)}: built from another {name}; rebuild it")
    return results, problems


def card(template: Path, catalog: Path, version: str, release_members: set[str], addon_members: set[str]) -> str:
    """The dataset card (README.md), from the template with this release's version and counts."""
    editions = pq.read_table(catalog / "editions" / "editions.parquet", columns=["edition"]).to_pylist()
    targets = pq.read_table(catalog / "editions" / "targets.parquet",
                            columns=["edition", "publisher", "alias"]).to_pylist()
    by_edition = defaultdict(list)
    for t in targets:
        by_edition[t["edition"]].append(f"{t['publisher']} `{t['alias']}`")
    rows = ["| Edition | Published as |", "| --- | --- |"]
    rows += [f"| `{f}` | {'; '.join(sorted(ts))} |" for f, ts in sorted(by_edition.items())]
    return template.read_text().format(
        version=version, n_editions=len(targets), n_sets=len(editions), edition_table="\n".join(rows),
        n_roots=pq.read_metadata(catalog / "roots" / "roots.parquet").num_rows,
        n_grch38=len(release_members), n_decoys=len(addon_members))


def export(catalog: Path, out: Path, version: str, checks: dict[str, Path], evidence: list[tuple[Path, str]],
           lock_paths: list[Path], card_text: str, development: bool) -> dict:
    """Copy the release into `out` (see the module). `evidence` is (file, path in the release) pairs."""
    if out.exists():
        raise Refused(f"{out} exists: a release is never overwritten")
    results, problems = gate(catalog, checks, lock_paths, development)
    if problems:
        raise Refused("not exported:\n  " + "\n  ".join(problems))
    staging = out.with_name(out.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)  # left by an interrupted export
    entries = []
    for name, path in published(catalog).items():
        role = PUBLISHED[name][1]
        entries += [(p, f"{name}/{p.name}" if path.is_dir() else name, role)
                    for p in (sorted(path.glob("*")) if path.is_dir() else [path])]
    entries += [(p, rel, "evidence") for p, rel in evidence]
    files = {}
    for src, rel, role in entries:
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        files[rel] = {"bytes": dst.stat().st_size, "sha256": sha256(dst), "role": role}
    manifest = {
        "name": "refbook", "format": FORMAT, "version": version,
        "locks": {p.name: sha256(p) for p in lock_paths},
        "checks": {c: {"passed": r["passed"], **({"ena": r["details"]["ena"]} if "ena" in r["details"] else {})}
                   for c, r in results.items()},
        "created": datetime.date.today().isoformat(),
        "description": "Roots, layers and reproduced edition recipes of every book",
        "files": files,
    }
    (staging / "catalog.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (staging / "README.md").write_text(card_text)
    staging.rename(out)
    return {"files": len(files), "bytes": sum(f["bytes"] for f in files.values()), "out": str(out)}
