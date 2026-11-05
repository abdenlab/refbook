"""Check that every run of N in the roots is explained by the AGP.

Reads the component-level AGPs (*.comp.agp.gz, *.scaf.agp.gz) of every GRCh38
release and of hs38d1 in REGISTRY/raw, plus
the roots, N-runs and assembly members (10_roots), and checks:

- every root in an assembly has an AGP (EBV is in none), identical in every
  release that has it, tiling 1..length
- every AGP gap (N/U line) is entirely N in the root
- every N-run is exactly one AGP gap, or else is classified (N inside a
  component, gap plus adjacent component N, ...)
- each release's genomic_gaps.txt.gz (p7, p13, p14 only) is exactly its AGP
  gaps plus the N-runs inside components of >= MIN_COMPONENT_N

Writes REGISTRY/build/grch38/60_check_gaps/: check_gaps.tsv (one row per N-run
or gap that is not an exact match) and check_gaps.json (the result, with the
sha256 of each input table), and prints a summary. Exits nonzero on a hard
failure, after recording it.

Usage: uv run python -I pipeline/60_check_gaps.py REGISTRY_DIR [--assembly grch38]
"""

import argparse
import bisect
import gzip
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout

# Shortest component N-run that genomic_gaps.txt lists. Observed, not documented:
# GRCh38 has listed runs of >= 10 and unlisted runs of <= 7, nothing in between.
MIN_COMPONENT_N = 10
STEP = "60_check_gaps"


def agp_files(release: Path) -> list[Path]:
    return sorted(p for p in release.glob("*_assembly_structure/**/AGP/*.agp.gz")
                  if p.name.endswith((".comp.agp.gz", ".scaf.agp.gz")))


def read_agp(path: Path) -> dict[str, list[tuple]]:
    """object -> AGP rows, as tuples of the (string) columns after `object`."""
    objs = defaultdict(list)
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            objs[cols[0]].append(tuple(cols[1:]))
    return objs


def gaps_of(rows: list[tuple]) -> list[tuple[int, int, str]]:
    """0-based half-open (start, end, gap_type) of the N/U lines."""
    return [(int(r[0]) - 1, int(r[1]), r[5]) for r in rows if r[3] in ("N", "U")]


def check_tiling(obj: str, rows: list[tuple], length: int) -> list[str]:
    errs, pos = [], 0
    for r in rows:
        beg, end = int(r[0]), int(r[1])
        if beg != pos + 1:
            errs.append(f"{obj}: row starts at {beg}, expected {pos + 1}")
        if r[3] not in ("N", "U") and int(r[6]) - int(r[5]) != end - beg:
            errs.append(f"{obj}: component span != object span at {beg}")
        pos = end
    if pos != length:
        errs.append(f"{obj}: AGP ends at {pos}, root length {length}")
    return errs


def classify_runs(runs: list[tuple[int, int]], gaps: list[tuple[int, int, str]]):
    """Compare one root's N-runs (sorted, disjoint, 0-based half-open) with its AGP
    gaps. Returns the gaps that are not entirely N, and each run with its kind:
    "exact" (one gap), "adjacent_gaps" (several gaps filling it), "no_gap" (Ns
    inside a component) or "gap_plus_component_N", plus the types of its gaps."""
    starts = [s for s, _ in runs]
    in_run, not_all_n = defaultdict(list), []
    for gs, ge, gt in gaps:
        i = bisect.bisect_right(starts, gs) - 1
        if i < 0 or runs[i][1] < ge:
            not_all_n.append((gs, ge, gt))
        else:
            in_run[i].append((gs, ge, gt))
    classified = []
    for i, (rs, re_) in enumerate(runs):
        g = in_run.get(i, [])
        if len(g) == 1 and g[0][:2] == (rs, re_):
            kind = "exact"
        elif not g:
            kind = "no_gap"
        elif sum(ge - gs for gs, ge, _ in g) == re_ - rs:
            kind = "adjacent_gaps"
        else:
            kind = "gap_plus_component_N"
        classified.append((rs, re_, kind, [t for *_, t in g]))
    return not_all_n, classified


def read_genomic_gaps(path: Path) -> dict[str, set[tuple[int, int]]]:
    gaps = defaultdict(set)
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                continue
            acc, start, stop = line.split("\t")[:3]
            gaps[acc].add((int(start) - 1, int(stop)))
    return gaps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("--assembly", default=layout.ASSEMBLY)
    args = ap.parse_args()
    build = layout.build_dir(args.registry, args.assembly)
    with layout.step_output(build, STEP) as out:
        passed = run(layout.raw_dir(args.registry), build, out)
    if not passed:
        sys.exit(1)


def run(raw: Path, build: Path, out: Path) -> bool:
    roots = pq.read_table(layout.path(build, "roots.parquet"), columns=["root_id", "length"])
    length = dict(zip(roots["root_id"].to_pylist(), roots["length"].to_pylist()))
    runs_t = pq.read_table(layout.path(build, "layer_n_runs.parquet"))
    runs = defaultdict(list)
    for acc, s, e in zip(*(runs_t[c].to_pylist() for c in ("root_id", "start", "end"))):
        runs[acc].append((s, e))
    in_assembly = set(pq.read_table(layout.path(build, "assembly_members.parquet"),
                                    columns=["genbank_accession"])
                      ["genbank_accession"].to_pylist())

    errors = []
    agp, first_seen = {}, {}
    rel_objs = {}  # release name -> roots with an AGP in that release
    rel_gg = {}    # release name -> its genomic_gaps.txt, where published
    for d in layout.assembly_dirs(raw):
        rel_objs[d.name] = set()
        for path in agp_files(d):
            for obj, rows in read_agp(path).items():
                if obj not in length:
                    continue  # placed scaffolds are AGP objects but not roots
                if obj in agp and agp[obj] != rows:
                    errors.append(f"{obj}: AGP in {d.name} differs from {first_seen[obj]}")
                agp.setdefault(obj, rows)
                first_seen.setdefault(obj, d.name)
                rel_objs[d.name].add(obj)
        gg_path = d / f"{d.name}_genomic_gaps.txt.gz"
        if gg_path.exists():  # only published for p7, p13, p14
            rel_gg[d.name] = read_genomic_gaps(gg_path)
    print(f"AGP for {len(agp)} of {len(length)} roots, {len(rel_objs)} assembly "
          f"releases", file=sys.stderr)
    for acc in sorted(in_assembly - set(agp)):
        errors.append(f"{acc}: no AGP in any release")
    for obj, rows in agp.items():
        errors += check_tiling(obj, rows, length[obj])

    # Compare N-runs with gaps. A gap must lie within a single run (all N).
    # A run is "exact" if it equals one gap; otherwise classify it.
    report = []
    stats = Counter()
    gap_types = Counter()
    component_n = defaultdict(set)  # acc -> N-runs that touch no AGP gap
    for acc in sorted(length):
        gaps = gaps_of(agp.get(acc, []))
        for *_, gt in gaps:
            gap_types[gt] += 1
        not_all_n, classified = classify_runs(runs.get(acc, []), gaps)
        for gs, ge, gt in not_all_n:
            stats["gap_not_all_N"] += 1
            report.append((acc, gs, ge, "gap_not_all_N", gt))
        for rs, re_, kind, types in classified:
            stats[kind] += 1
            if kind == "no_gap":
                component_n[acc].add((rs, re_))
            if kind != "exact":
                report.append((acc, rs, re_, kind, ",".join(types)))

    # genomic_gaps.txt lists the AGP gaps (adjacent ones separately) plus the
    # N-runs inside components of at least MIN_COMPONENT_N.
    for name, gg in rel_gg.items():
        for acc in rel_objs[name] | set(gg):
            want = {(s, e) for s, e, _ in gaps_of(agp.get(acc, []))}
            want |= {(s, e) for s, e in component_n[acc] if e - s >= MIN_COMPONENT_N}
            if gg.get(acc, set()) != want:
                errors.append(f"{acc}: genomic_gaps.txt in {name} != AGP gaps "
                              f"+ component N-runs >= {MIN_COMPONENT_N}")

    with open(out / "check_gaps.tsv", "w") as f:
        f.write("root_id\tstart\tend\tkind\tgap_types\n")
        f.writelines("\t".join(map(str, row)) + "\n" for row in report)

    n_bp = Counter()
    for acc, s, e, kind, _ in report:
        n_bp[kind] += e - s
    print(f"N-runs: {sum(len(v) for v in runs.values())}, "
          f"AGP gaps: {sum(gap_types.values())}", file=sys.stderr)
    print(f"gap types: {dict(gap_types)}", file=sys.stderr)
    for kind, n in sorted(stats.items()):
        print(f"{kind}\t{n}\t{n_bp.get(kind, '')}", file=sys.stderr)
    lens = Counter(e - s for v in component_n.values() for s, e in v)
    print(f"no_gap run lengths: {sorted(lens.items())}", file=sys.stderr)
    print(f"genomic_gaps.txt checked in {len(rel_gg)} releases", file=sys.stderr)
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    passed = not errors and not stats["gap_not_all_N"]
    layout.record_check(build, out, "check_gaps", passed,
                        ["roots.parquet", "layer_n_runs.parquet", "assembly_members.parquet"],
                        {"errors": errors[:100], "runs": dict(stats)})
    return passed


if __name__ == "__main__":
    main()
