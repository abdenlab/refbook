"""Read the sequence list of a reference from its index, header or FASTA.

Every format becomes the same thing: an ordered list of (name, length, md5),
where md5 is the refget MD5 (uppercase, A-Z only) if the format carries it.

- .fai, chrom.sizes         names and lengths
- .dict / SAM header text   @SQ SN, LN and M5 (also `samtools view -H` output)
- BAM                       its header text, or its binary reference list
- VCF (plain or bgzipped)   ##contig ID, length and md5
- FASTA (plain or gzipped)  digested here: names, lengths and MD5s
CRAM's header sits inside a compressed container; run `samtools view -H` on
it and identify the output instead.
"""

import gzip
import hashlib
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

NOT_AZ = re.compile(rb"[^A-Z]")
CONTIG = re.compile(r"^##contig=<(.*)>\s*$")


@dataclass
class Entry:
    name: str
    length: int
    md5: str | None = None


@dataclass
class Header:
    source: str
    format: str
    entries: list[Entry] = field(default_factory=list)

    @property
    def has_md5(self) -> bool:
        return bool(self.entries) and all(e.md5 for e in self.entries)


def _open_text(path: Path):
    with open(path, "rb") as f:
        magic = f.read(2)
    return gzip.open(path, "rt") if magic == b"\x1f\x8b" else open(path, "rt")


def _sam_entries(lines) -> list[Entry]:
    out = []
    for line in lines:
        if line.startswith("@SQ"):
            tags = dict(f.split(":", 1) for f in line.rstrip("\n").split("\t")[1:] if ":" in f)
            out.append(Entry(tags["SN"], int(tags["LN"]), tags.get("M5", "").lower() or None))
    return out


def _vcf_entries(lines) -> list[Entry]:
    out = []
    for line in lines:
        if not line.startswith("##"):
            break
        m = CONTIG.match(line)
        if not m:
            continue
        fields = dict(re.findall(r'(\w+)=("[^"]*"|[^,]*)', m.group(1)))
        fields = {k: v.strip('"') for k, v in fields.items()}
        if "length" in fields:
            out.append(Entry(fields["ID"], int(fields["length"]), fields.get("md5", "").lower() or None))
    return out


def _bam_entries(path: Path) -> list[Entry]:
    with gzip.open(path, "rb") as f:
        if f.read(4) != b"BAM\x01":
            raise ValueError(f"{path}: not a BAM file")
        (l_text,) = struct.unpack("<i", f.read(4))
        text = f.read(l_text).decode("utf8", "replace")
        entries = _sam_entries(text.splitlines())
        if entries:
            return entries
        (n_ref,) = struct.unpack("<i", f.read(4))
        for _ in range(n_ref):
            (l_name,) = struct.unpack("<i", f.read(4))
            name = f.read(l_name).rstrip(b"\0").decode()
            (l_ref,) = struct.unpack("<i", f.read(4))
            entries.append(Entry(name, l_ref))
        return entries


def _fasta_entries(path: Path) -> list[Entry]:
    out, name, h, n = [], None, None, 0
    with _open_text(path) as f:
        for line in f:
            if line.startswith(">"):
                if name is not None:
                    out.append(Entry(name, n, h.hexdigest()))
                name, h, n = line[1:].split()[0], hashlib.md5(), 0
            else:
                s = line.rstrip("\r\n").encode()
                n += len(s)
                h.update(NOT_AZ.sub(b"", s.upper()))
    if name is not None:
        out.append(Entry(name, n, h.hexdigest()))
    return out


def read_header(path: str | Path) -> Header:
    path = Path(path)
    name = path.name.lower()
    with open(path, "rb") as f:
        head = f.read(4)
    if head == b"CRAM":
        raise ValueError(f"{path}: CRAM; run `samtools view -H {path}` and identify that instead")
    if name.endswith(".bam"):
        return Header(str(path), "bam", _bam_entries(path))
    if name.endswith((".fai", ".sizes", ".len", ".txt")):
        entries = []
        with _open_text(path) as f:
            for line in f:
                if not line.strip():
                    continue
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) < 2 or not cols[1].isdigit():
                    raise ValueError(f"{path}: expected name<TAB>length lines")
                entries.append(Entry(cols[0], int(cols[1])))
        return Header(str(path), "fai" if name.endswith(".fai") else "sizes", entries)
    with _open_text(path) as f:
        first = f.readline()
    if first.startswith("@"):
        with _open_text(path) as f:
            return Header(str(path), "dict" if name.endswith(".dict") else "sam", _sam_entries(f))
    if first.startswith("##fileformat=VCF"):
        with _open_text(path) as f:
            return Header(str(path), "vcf", _vcf_entries(f))
    if first.startswith(">"):
        return Header(str(path), "fasta", _fasta_entries(path))
    raise ValueError(f"{path}: not a .fai, .dict/SAM header, BAM, VCF or FASTA")
