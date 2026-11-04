"""The registry's layout and the GRCh38 releases, defined once for every step.

A registry directory holds raw/ (downloads, at raw/<host>/<url path>) and
build/<assembly>/ (the steps' outputs).
"""

from pathlib import Path

ASSEMBLY = "grch38"
NCBI = "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405"
HS38D1 = "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/786/075/GCA_000786075.2_hs38d1"
GRCH38 = "GCA_000001405."   # GenBank assembly accession prefix of every GRCh38 release

# GRCh38 p0..p14: (patch number, GenBank assembly accession.version, assembly name).
# p0 is the major release, officially just "GRCh38".
RELEASES = [(n, f"{GRCH38}{15 + n}", "GRCh38" if n == 0 else f"GRCh38.p{n}") for n in range(15)]
LATEST = RELEASES[-1]


def raw_dir(registry: Path) -> Path:
    return registry / "raw"


def build_dir(registry: Path, assembly: str = ASSEMBLY) -> Path:
    return registry / "build" / assembly


def release_dir(raw: Path, n: int) -> Path:
    """The NCBI directory of GRCh38 patch release n under raw/."""
    _, accession, name = RELEASES[n]
    return raw / NCBI / f"{accession}_{name}"


def release_dirs(raw: Path) -> list[Path]:
    """Every GRCh38 release directory, p0 to p14."""
    return [release_dir(raw, n) for n, _, _ in RELEASES]


def assembly_dirs(raw: Path) -> list[Path]:
    """Every assembly directory with a report: GRCh38 p0-p14, then hs38d1."""
    return release_dirs(raw) + [raw / HS38D1]


def release_number(release: Path) -> int:
    """The patch number of a GRCh38 release directory: 0 for GCA_000001405.15_GRCh38."""
    accession = release.name.split("_")[0] + "_" + release.name.split("_")[1]
    for n, acc, _ in RELEASES:
        if acc == accession:
            return n
    raise ValueError(f"{release}: not a GRCh38 release directory")
