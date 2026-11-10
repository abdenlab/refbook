"""Publishing an exported release on Hugging Face (the dataset abdenlab/refbook), as one commit tagged v<version>.

The release directory is checked against its own catalog.json first: its version, and every file's size and sha256,
with no file it doesn't list (but catalog.json itself, and README.md, the dataset card). The commit makes the
dataset's main branch exactly the release: files the release doesn't have are deleted in the same commit, so an older
release's layout doesn't linger; the older release stays at its own tag. A tag is never moved: the upload refuses if v<version> exists.

The token is huggingface_hub's own (HF_TOKEN, or a stored `hf auth login`): this module never reads it.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import Refused
from .checks import sha256

REPO = "abdenlab/refbook"


def verify(release: Path, version: str) -> dict:
    """The release's catalog.json, after checking the directory is exactly what it lists, at `version`."""
    index = release / "catalog.json"
    if not index.exists():
        raise Refused(f"{release}: no catalog.json (not an exported release)")
    manifest = json.loads(index.read_text())
    if manifest.get("version") != version:
        raise Refused(f"{release} is release {manifest.get('version')!r}, not {version!r}")
    listed = manifest["files"]
    present = {p.relative_to(release).as_posix() for p in release.rglob("*") if p.is_file()} - {"catalog.json", "README.md"}
    problems = [f"not in catalog.json: {p}" for p in sorted(present - set(listed))]
    problems += [f"missing: {p}" for p in sorted(set(listed) - present)]
    for rel, meta in sorted(listed.items()):
        if rel in present:
            path = release / rel
            if path.stat().st_size != meta["bytes"] or sha256(path) != meta["sha256"]:
                problems.append(f"changed since the export: {rel}")
    if problems:
        raise Refused("not uploaded:\n  " + "\n  ".join(problems))
    return manifest


def upload(release: Path, version: str, repo: str = REPO) -> str:
    """Upload a verified release as one commit to the dataset `repo`, mirroring it exactly, and tag it
    v<version>. Returns the commit's URL."""
    from huggingface_hub import HfApi

    manifest = verify(release, version)
    tag = f"v{version}"
    api = HfApi()
    if any(t.name == tag for t in api.list_repo_refs(repo, repo_type="dataset").tags):
        raise Refused(f"{repo} already has a tag {tag}: a release is never overwritten")
    commit = api.upload_folder(repo_id=repo, repo_type="dataset", folder_path=release, delete_patterns="*",
                               commit_message=f"refbook {version}",
                               commit_description=f"{len(manifest['files'])} files; catalog.json lists each with its sha256.")
    api.create_tag(repo, tag=tag, revision=commit.oid, repo_type="dataset", tag_message=f"refbook {version}")
    return commit.commit_url
