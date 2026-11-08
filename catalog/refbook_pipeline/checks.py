"""The checks a release is gated on, each run on the tables the catalog publishes (not on raw files), each recording
its result with the sha256 of every table it read, so an export can require a pass on exactly the files it ships.

- check_gaps: every run of N in the roots is explained by the published AGP (layer_agp, layer_n_runs, roots): every
  member root has an AGP, which tiles it in part order; every AGP gap is entirely N; every N-run is one gap or is
  classified (several adjacent gaps; N inside a component; a gap plus a component's N); and each release's own
  genomic_gaps.txt (GRC's, where published: GRCh38 p7, p13, p14) lists exactly its AGP gaps plus the N-runs inside
  components of at least MIN_COMPONENT_N.
- check_roots: the roots' digests against two independent sources. ENA's refget server (its own copy of INSDC) must
  hold each MD5 at its length (consulted only when asked: one request per root), but for the roots ENA lacks that
  roots_ena_exceptions.tsv lists with exactly that MD5 and how else it was confirmed; a listed root ENA now holds,
  or whose MD5 is not the listed one, fails. The GRC analysis-set FASTA's deflines carry M5 per sequence, which must
  equal ours for a root the GRC leaves unmasked and differ for one it masks.
- check_materialize: from the bases, through the library: every derivation in the sequence store rebuilt and
  digested, every edition and target resolved to its seqcol digest, one collection streamed in full.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from pathlib import Path

from refbook.parse import open_compressed

from . import Refused

# The shortest component N-run genomic_gaps.txt lists. Observed, not documented: GRCh38 has listed runs of >= 10
# and unlisted runs of <= 7, nothing in between.
MIN_COMPONENT_N = 10
ENA = "https://www.ebi.ac.uk/ena/cram/sequence/{}/metadata"
USER_AGENT = "refbook (reference genome catalog)"


def sha256(path: Path) -> str:
    """sha256 of a file, or of a directory's files (names and contents, in order)."""
    h = hashlib.sha256()
    for f in sorted(q for q in path.rglob("*") if q.is_file()) if path.is_dir() else [path]:
        if path.is_dir():
            h.update(f.relative_to(path).as_posix().encode() + b"\0")
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
    return h.hexdigest()


def record(out: Path, check: str, passed: bool, inputs: dict[str, Path], details: dict) -> dict:
    """<out>/<check>.json: the result, and the sha256 of every published table it read, by its published name."""
    result = {"check": check, "passed": passed, "details": details,
              "inputs": {name: sha256(p) for name, p in sorted(inputs.items())}}
    (out / f"{check}.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


# check_gaps

def classify_runs(runs: list[tuple[int, int]], gaps: list[tuple[int, int, str]]):
    """One root's N-runs (sorted, disjoint, 0-based half-open) against its AGP gaps: the gaps that are not entirely
    N, and each run with its kind ("exact": one gap; "adjacent_gaps": several filling it; "no_gap": N inside a
    component; "gap_plus_component_N") and its gaps' types."""
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


def check_tiling(root: str, parts: list[dict], length: int) -> list[str]:
    """An AGP tiles its root: parts numbered 1..n in order, each starting where the last ended, a component's span
    the object's, ending at the root's length."""
    errs, pos = [], 0
    for i, p in enumerate(parts, 1):
        if p["part_number"] != i:
            errs.append(f"{root}: part {p['part_number']} where {i} was expected")
        if p["start"] != pos:
            errs.append(f"{root}: part {i} starts at {p['start']}, expected {pos}")
        if p["component_id"] is not None and p["component_end"] - p["component_start"] != p["end"] - p["start"]:
            errs.append(f"{root}: part {i}'s component span != its span")
        pos = p["end"]
    if pos != length:
        errs.append(f"{root}: AGP ends at {pos}, root length {length}")
    return errs


def read_genomic_gaps(path: Path) -> dict[str, set[tuple[int, int]]]:
    gaps = defaultdict(set)
    with open_compressed(path, "rt") as f:
        for line in f:
            if not line.startswith("#"):
                acc, start, stop = line.split("\t")[:3]
                gaps[acc].add((int(start) - 1, int(stop)))
    return gaps


def check_gaps(agp: list[dict], n_runs: list[dict], lengths: dict[str, int], members: list[dict],
               genomic_gaps: dict[str, Path]) -> tuple[bool, dict, list[tuple]]:
    """(passed, details, the report's rows) for check_gaps (see the module). `genomic_gaps` gives, by release name,
    the GRC's genomic_gaps.txt.gz where published."""
    errors = []
    parts = defaultdict(list)
    for p in agp:
        parts[p["root_id"]].append(p)
    runs = defaultdict(list)
    for r in n_runs:
        runs[r["root_id"]].append((r["start"], r["end"]))
    for acc, v in runs.items():
        v.sort()
        if any(a[1] > b[0] for a, b in pairwise(v)):
            errors.append(f"{acc}: its runs of N overlap")
    for acc in sorted({m["genbank_accession"] for m in members} - set(parts)):
        errors.append(f"{acc}: no AGP")
    for acc, ps in parts.items():
        ps.sort(key=lambda p: p["part_number"])
        errors += check_tiling(acc, ps, lengths[acc])
    gaps = {acc: [(p["start"], p["end"], p["gap_type"]) for p in ps if p["component_id"] is None]
            for acc, ps in parts.items()}

    report, stats, component_n = [], Counter(), defaultdict(set)
    for acc in sorted(lengths):
        not_all_n, classified = classify_runs(runs.get(acc, []), gaps.get(acc, []))
        for gs, ge, gt in not_all_n:
            stats["gap_not_all_N"] += 1
            report.append((acc, gs, ge, "gap_not_all_N", gt))
        for rs, re_, kind, types in classified:
            stats[kind] += 1
            if kind == "no_gap":
                component_n[acc].add((rs, re_))
            if kind != "exact":
                report.append((acc, rs, re_, kind, ",".join(types)))
    in_release = defaultdict(set)
    for m in members:
        in_release[m["assembly_name"]].add(m["genbank_accession"])
    for name, path in sorted(genomic_gaps.items()):
        gg = read_genomic_gaps(path)
        for acc in in_release[name] | set(gg):
            want = {(s, e) for s, e, _ in gaps.get(acc, [])}
            want |= {(s, e) for s, e in component_n[acc] if e - s >= MIN_COMPONENT_N}
            if gg.get(acc, set()) != want:
                errors.append(f"{acc}: genomic_gaps.txt in {name} != AGP gaps + component N-runs >= {MIN_COMPONENT_N}")
    passed = not errors and not stats["gap_not_all_N"]
    return passed, {"errors": errors[:100], "runs": dict(stats)}, report


# check_roots

def ena_length(md5: str) -> int | None:
    """The length ENA's refget server gives for an MD5, or None if it doesn't hold it."""
    req = urllib.request.Request(ENA.format(md5), headers={"User-Agent": USER_AGENT})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)["metadata"].get("length")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError):
            pass
    raise Refused(f"ENA unreachable for {md5}")


def ena_lengths(md5s: list[str]) -> dict[str, int | None]:
    with ThreadPoolExecutor(8) as pool:
        return dict(zip(md5s, pool.map(ena_length, md5s)))


def grc_m5(path: Path) -> dict[str, str]:
    """accession -> M5, from a GRC analysis-set FASTA's deflines (AC: and M5: tags)."""
    out = {}
    with open_compressed(path, "rt") as f:
        for line in f:
            if line.startswith(">"):
                ac, m5 = re.search(r"\bAC:(\S+)", line), re.search(r"\bM5:([0-9a-f]{32})", line)
                if ac and m5:
                    out[ac.group(1)] = m5.group(1)
    return out


def read_ena_exceptions(path: Path) -> dict[str, str]:
    """root_id -> MD5 of every root documented as absent from ENA (roots_ena_exceptions.tsv: root_id, md5, checked,
    why; `#` lines are comments)."""
    if not path.exists():
        return {}
    rows = [line.split("\t") for line in path.read_text().splitlines() if line and not line.startswith("#")]
    return {r[0]: r[1] for r in rows[1:]}


def root_status(length: int, md5: str, ena: int | None | str, grc_md5: str | None, masked: bool,
                excepted: str | None = None) -> tuple[str, str, bool]:
    """(ENA result, GRC result, passed) for one root; `ena` is "not checked" when ENA wasn't consulted; `excepted`
    the MD5 roots_ena_exceptions.tsv lists for the root, if it does."""
    if ena == "not checked":
        ena_s = ena
    elif ena is None:
        ena_s = "absent (documented)" if excepted == md5 else "absent"
    elif excepted is not None:
        ena_s = "ok (UNEXPECTED: listed as absent)"
    else:
        ena_s = "ok" if ena == length else f"length {ena}"
    if grc_md5 is None:
        grc = "not in set"
    elif grc_md5 == md5:
        grc = "match" + (" (UNEXPECTED: masked by the GRC)" if masked else "")
    else:
        grc = "differs" + ("" if masked else " (UNEXPECTED)")
    return ena_s, grc, ena_s in ("ok", "not checked", "absent (documented)") and "UNEXPECTED" not in grc


def check_roots(roots: list[dict], masked: set[str], m5: dict[str, str], analysis_set: str,
                ena: dict[str, int | None] | None,
                exceptions: dict[str, str] | None = None) -> tuple[bool, dict, list[tuple]]:
    """(passed, details, the report's rows) for check_roots; `ena` is None when ENA wasn't consulted;
    `exceptions` the roots documented as absent from ENA (read_ena_exceptions)."""
    exceptions = exceptions or {}
    counts, failed, rows = Counter(), [], []
    for r in roots:
        acc = r["root_id"]
        e = "not checked" if ena is None else ena[r["md5"]]
        ena_s, grc_s, ok = root_status(r["length"], r["md5"], e, m5.get(acc), acc in masked, exceptions.get(acc))
        counts[f"ena:{ena_s}"] += 1
        counts[f"grc:{grc_s}"] += 1
        rows.append((acc, r["length"], r["md5"], ena_s, grc_s))
        if not ok:
            failed.append(acc)
    failed += sorted(set(exceptions) - {r["root_id"] for r in roots})  # listed, but no longer a root
    return not failed, {"counts": dict(counts), "failed": failed[:100], "analysis_set": analysis_set,
                        "ena": "skipped" if ena is None else "checked"}, rows


# check_materialize (through the library, over the build's index)

def check_materialize(build_catalog: Path, stream_names: list[str]) -> tuple[bool, dict, list[str]]:
    """(passed, details, what it did): every derivation rebuilt from root_blocks and digested, every edition and
    target resolved to its seqcol digest, and the named collections streamed in full and digested."""
    import time

    from refbook import Catalog, collection, materialize
    from refbook.materialize import SCHEMA, Bases, apply_operations
    from refbook.seqcol import digests, sha512t24u

    cat = Catalog(build_catalog)
    bases = Bases(cat)
    want = {**{f: r["seqcol_digest"] for f, r in cat.editions.items()},
            **{t: r["seqcol_digest"] for t, r in cat.targets.items()}}
    errors, log = [], []
    t0 = time.time()
    by_root = defaultdict(list)
    for sq, ways in cat.derivations.items():
        for d in ways:
            by_root[d["root_id"]].append((sq, d["operations"], d.get("book")))
    for root, ways in sorted(by_root.items()):
        raw = bytes(bases.get(root))
        for sq, ops, book in ways:
            b = apply_operations(cat, root, ops, raw, book=book)
            rec = cat.sequence[sq]
            if (hashlib.md5(b).hexdigest(), "SQ." + sha512t24u(b), len(b)) != (rec["md5"], sq, rec["length"]):
                errors.append(f"{root} {ops}: does not give {sq}")
    n = sum(len(v) for v in cat.derivations.values())
    log.append(f"{n} derivations of {len(cat.sequence)} sequences rebuilt, {time.time() - t0:.0f} s")
    t0 = time.time()
    for name, digest in want.items():
        try:
            if collection(cat, name).digest != digest:
                errors.append(f"{name}: seqcol digest is not the catalog's {digest}")
        except Exception as e:  # noqa: BLE001 - report every collection, then fail
            errors.append(f"{name}: {e}")
    log.append(f"{len(want)} collections resolve to their seqcol digests, {time.time() - t0:.0f} s")
    for name in stream_names:
        t0 = time.time()
        names, lengths, sqs, batches = [], [], [], 0
        reader = materialize(cat, name, bases=bases)
        if not reader.schema.equals(SCHEMA, check_metadata=False):
            errors.append(f"{name}: schema {reader.schema}")
            continue
        for batch in reader:
            batches += 1
            for nm, seq in zip(batch.column("name").to_pylist(), batch.column("sequence")):
                b = seq.as_py().encode("ascii")
                names.append(nm)
                lengths.append(len(b))
                sqs.append("SQ." + sha512t24u(b))
        top, _ = digests(names, lengths, sqs)
        if top != want[name]:
            errors.append(f"{name}: streamed seqcol {top} != catalog {want[name]}")
        log.append(f"streamed {name}: {len(names)} sequences, {sum(lengths):,} bp, {batches} batches, "
                   f"{time.time() - t0:.0f} s")
    return not errors, {"errors": errors[:100], "derivations": n, "collections": len(want),
                        "streamed": stream_names}, log
