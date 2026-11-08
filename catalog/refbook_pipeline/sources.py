"""Sources: what the catalog downloads, declared as data in catalog/sources.toml.

A source is a set of files from one publisher, locked together (catalog/locks/<source>.lock). Its files land at
raw/<host>/<url path>, so a file's path is its URL. A source declares its files in one or more of these ways:

- `base` + `files`: files under `base` that must exist; `optional`: files fetched if the publisher has them.
- `trees`: directories under `base` fetched whole (recursively), minus `reject` patterns.
- `ncbi_assembly`: an NCBI assembly directory, `base` and its standard files (`<asm>_assembly_report.txt`, ...,
  `md5checksums.txt`, ...: all optional, since older releases lack some) and its `<asm>_assembly_structure/`
  tree without sequence files (`structure = false` if NCBI no longer keeps it: superseded GRCh37 releases keep
  only the report, regions and stats); `also` lists more of its files, required.
- `efetch`: GenBank records by accession, from NCBI's E-utilities, saved as
  eutils.ncbi.nlm.nih.gov/efetch/nuccore_<accession>.<rettype>.
- `github_tree`: files of a repository tree (`repo`, `ref`, a `prefix` and `suffix` filter), listed by GitHub's
  API at fetch time and fetched from `base` (raw.githubusercontent.com/<repo>/<ref>).

`sequences` lists the source's files that hold roots (FASTA, gzipped or not; paths under `base`, or under raw/ for
an efetch source), and `loose_roots` the roots in no assembly report, each with the GenBank record that gives its
length (EBV). `minted_roots` lists roots with no accession, named by the catalog: each one's `name` in the FASTA,
its `root_id` (`<publisher>:<name>`), the `fai` whose entry gives its length, and optionally the `agp_bed` that maps
it to its parts (hs37d5's concatenated decoys: see layers.build_agp_bed). Every other root is a member of an
assembly report.

`external` declares a source's sequences external roots, listed by identity and digest and never hosted: its
`collection` (what recipes select by), the `prefix` of its root IDs, and its `format` (imgt_hla: one FASTA per
gene, the source's github_tree files).

`checksums` names checksum lists outside the source (raw paths, in another source's lock) that also cover its
files: NCBI's list for a release directory covers its subdirectories, which can be sources of their own.

`roles` says what the catalog uses a source for: `input` (built from: roots, layers, aliases), `target`
(published files the recipes reproduce), or both. Roles are data; a source has one lock either way.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import Refused

USER_AGENT = "refbook (reference genome catalog)"
EFETCH_DIR = "eutils.ncbi.nlm.nih.gov/efetch"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
# An NCBI assembly directory's standard files: <asm>_<suffix>, and files named as is.
NCBI_SUFFIXES = ["assembly_report.txt", "assembly_regions.txt", "assembly_stats.txt", "genomic_gaps.txt.gz",
                 "fcs_report.txt"]
NCBI_FILES = ["md5checksums.txt", "uncompressed_checksums.txt", "assembly_status.txt", "README.txt"]
NCBI_TREE_REJECT = ["index.html*", "*.fna.gz", "*.fa.gz"]
ROLES = {"input", "target"}


@dataclass(frozen=True)
class Tree:
    path: str                  # under the source's base, ending in /
    reject: tuple[str, ...] = ()


@dataclass(frozen=True)
class Source:
    name: str
    roles: tuple[str, ...]
    base: str = ""                                   # host/path, no scheme
    files: tuple[str, ...] = ()                      # under base, required
    optional: tuple[str, ...] = ()                   # under base, if the publisher has them
    trees: tuple[Tree, ...] = ()
    efetch: tuple[tuple[str, str], ...] = ()         # (accession, rettype)
    github_tree: dict = field(default_factory=dict)  # repo, ref, prefix, suffix
    checksums: tuple[str, ...] = ()                  # checksum lists elsewhere that cover these files
    sequences: tuple[str, ...] = ()                  # raw paths of the files that hold roots
    loose_roots: tuple[tuple[str, str], ...] = ()    # (accession, raw path of its GenBank record)
    minted_roots: tuple[dict, ...] = ()              # name, root_id, fai, agp_bed? (raw paths)
    external: dict = field(default_factory=dict)     # collection, prefix, format
    ncbi_assembly: bool = False                      # an NCBI assembly directory
    structure: bool = True                           # ...with its assembly structure tree
    note: str = ""


def load(path: Path) -> dict[str, Source]:
    """Every declared source, by name."""
    out = {}
    for s in tomllib.loads(path.read_text())["source"]:
        name = s["name"]
        if name in out:
            raise Refused(f"{path}: source {name} is declared twice")
        if not set(s.get("roles", [])) <= ROLES or not s.get("roles"):
            raise Refused(f"{name}: roles must be some of {sorted(ROLES)}")
        base, files, optional, trees = s.get("base", ""), list(s.get("files", [])), list(s.get("optional", [])), []
        if "ncbi_assembly" in s:
            base = s["ncbi_assembly"].rstrip("/")
            asm = base.rsplit("/", 1)[-1]
            optional += [f"{asm}_{x}" for x in NCBI_SUFFIXES] + NCBI_FILES
            files += s.get("also", [])
            if s.get("structure", True):
                trees.append(Tree(f"{asm}_assembly_structure/", tuple(NCBI_TREE_REJECT)))
        trees += [Tree(t["path"], tuple(t.get("reject", []))) for t in s.get("trees", [])]
        efetch = tuple((acc, rt) for acc in s.get("efetch", {}).get("accessions", [])
                       for rt in s.get("efetch", {}).get("rettypes", ["fasta"]))
        out[name] = Source(name=name, roles=tuple(s["roles"]), base=base, files=tuple(files),
                           optional=tuple(optional), trees=tuple(trees), efetch=efetch,
                           github_tree=dict(s.get("github_tree", {})), checksums=tuple(s.get("checksums", [])),
                           sequences=tuple(_join(base, f) for f in s.get("sequences", [])),
                           loose_roots=tuple(sorted(s.get("loose_roots", {}).items())),
                           minted_roots=tuple(_minted(name, base, m) for m in s.get("minted_roots", [])),
                           external=dict(s.get("external", {})), ncbi_assembly="ncbi_assembly" in s,
                           structure="ncbi_assembly" in s and s.get("structure", True),
                           note=s.get("note", ""))
    return out


def _minted(source: str, base: str, m: dict) -> dict:
    if set(m) - {"name", "root_id", "fai", "agp_bed"} or not {"name", "root_id", "fai"} <= set(m):
        raise Refused(f"{source}: a minted root takes name, root_id, fai and optionally agp_bed")
    if ":" not in m["root_id"]:
        raise Refused(f"{source}: minted root {m['root_id']}: a minted ID is <publisher>:<name>")
    return {**m, **{k: _join(base, m[k]) for k in ("fai", "agp_bed") if k in m}}


def fai_length(path: Path, name: str) -> int:
    """A sequence's length from a FASTA index."""
    for line in path.read_text().splitlines():
        cols = line.split("\t")
        if cols[0] == name:
            return int(cols[1])
    raise Refused(f"{path.name}: no entry for {name}")


def _join(base: str, rel: str) -> str:
    return f"{base}/{rel}" if base else rel


def reports(source: Source) -> list[str]:
    """The assembly report of an NCBI assembly source (raw path), if it is one."""
    if not source.ncbi_assembly:
        return []
    asm = source.base.rsplit("/", 1)[-1]
    return [f"{source.base}/{asm}_assembly_report.txt"]


def efetch_path(acc: str, rettype: str) -> str:
    return f"{EFETCH_DIR}/nuccore_{acc}.{rettype}"


def url_of(rel: str) -> str:
    """A file's source URL from its path under raw/ (efetch results are named for the record they hold)."""
    if rel.startswith(EFETCH_DIR + "/"):
        stem, rettype = Path(rel).name.removeprefix("nuccore_").rsplit(".", 1)
        return f"{EFETCH_URL}?db=nuccore&id={stem}&rettype={rettype}&retmode=text"
    return "https://" + rel


def _walk(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def files(source: Source, raw: Path) -> tuple[list[str], list[str]]:
    """The source's files under raw/ (paths relative to raw), and the required ones that are missing."""
    found, missing = set(), []
    for f in source.files:
        rel = _join(source.base, f)
        (found.add(rel) if (raw / rel).is_file() else missing.append(rel))
    for f in source.optional:
        rel = _join(source.base, f)
        if (raw / rel).is_file():
            found.add(rel)
    for t in source.trees:
        for p in _walk(raw / _join(source.base, t.path)):
            if not any(fnmatch.fnmatch(p.name, pat) for pat in t.reject):
                found.add(p.relative_to(raw).as_posix())
    for acc, rt in source.efetch:
        rel = efetch_path(acc, rt)
        (found.add(rel) if (raw / rel).is_file() else missing.append(rel))
    if source.github_tree:  # what the listing gave at fetch time: the files under base that match it
        prefix, suffix = source.github_tree.get("prefix", ""), source.github_tree.get("suffix", "")
        for p in _walk(raw / source.base):
            in_repo = p.relative_to(raw / source.base).as_posix()
            if in_repo.startswith(prefix) and in_repo.endswith(suffix):
                found.add(p.relative_to(raw).as_posix())
    return sorted(found), missing


# Fetching. Files are mirrored with wget: --timestamping keeps the server's
# Last-Modified as the file's mtime and skips a file that hasn't changed. Nothing here runs unless asked.

WGET = ["wget", "--no-verbose", "--timestamping", "--force-directories", "--tries=5", "--waitretry=10",
        "--execute", "robots=off"]


def commands(source: Source, listing: list[str] | None = None) -> list[tuple[list[str], bool]]:
    """The commands that fetch a source, each with whether it may fail (an optional file the publisher lacks).
    `listing` is the GitHub tree's file paths, for a github_tree source (see github_listing)."""
    out = [([*WGET, url_of(_join(source.base, f))], False) for f in source.files]
    out += [([*WGET, url_of(_join(source.base, f))], True) for f in source.optional]
    for t in source.trees:
        reject = ["--reject", ",".join(t.reject)] if t.reject else []
        out.append(([*WGET, "--recursive", "--no-parent", "--level=inf", *reject,
                     url_of(_join(source.base, t.path))], False))
    for acc, rt in source.efetch:
        out.append((["curl", "-sSfL", "--retry", "5", "-A", USER_AGENT, "-o", efetch_path(acc, rt),
                     f"{EFETCH_URL}?db=nuccore&id={acc}&rettype={rt}&retmode=text"], False))
    for path in listing or []:
        out.append(([*WGET, url_of(_join(source.base, path))], False))
    return out


def github_listing(tree: dict) -> list[str]:
    """The paths of a GitHub repository tree that match its prefix and suffix, from GitHub's API."""
    url = f"https://api.github.com/repos/{tree['repo']}/git/trees/{tree['ref']}?recursive=1"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        entries = json.load(r)["tree"]
    return sorted(e["path"] for e in entries if e["type"] == "blob" and e["path"].startswith(tree.get("prefix", ""))
                  and e["path"].endswith(tree.get("suffix", "")))


def fetch(source: Source, raw: Path) -> None:
    """Download a source into raw/. An efetch record already fetched is kept (E-utilities give no
    Last-Modified); everything else is re-checked against the server by wget."""
    raw.mkdir(parents=True, exist_ok=True)
    (raw / EFETCH_DIR).mkdir(parents=True, exist_ok=True)
    listing = github_listing(source.github_tree) if source.github_tree else None
    for cmd, may_fail in commands(source, listing):
        if cmd[0] == "curl":
            out = raw / cmd[cmd.index("-o") + 1]
            if out.is_file() and out.stat().st_size:
                continue
        done = subprocess.run(cmd, check=False, cwd=raw)
        if done.returncode and not may_fail:
            raise Refused(f"{source.name}: {' '.join(cmd[-1:])} failed ({done.returncode})")
