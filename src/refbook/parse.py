"""Read the sequence list of a reference from its index, header or FASTA.

Every format becomes the same thing: an ordered list of (name, length, md5),
where md5 is the refget MD5 (uppercase, A-Z only) if the format carries it.

- .fai, chrom.sizes         names and lengths
- .dict / SAM header text   @SQ SN, LN and M5 (also `samtools view -H` output)
- BAM                       its header text, or its binary reference list
- VCF (plain or bgzipped)   ##contig ID, length and md5
- FASTA (plain or gzipped)  digested here: names, lengths and MD5s
- CRAM 2.x/3.x               the SAM header in the first container (raw,
                            gzip, bzip2 or lzma; rANS-compressed headers are
                            not supported, run `samtools view -H` then)
"""

import bz2
import gzip
import hashlib
import lzma
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


def _itf8(b: bytes, i: int) -> tuple[int, int]:
    """CRAM ITF8 integer at b[i]: (value, next index)."""
    b0 = b[i]
    if b0 < 0x80:
        return b0, i + 1
    if b0 < 0xC0:
        return ((b0 & 0x7F) << 8) | b[i + 1], i + 2
    if b0 < 0xE0:
        return ((b0 & 0x3F) << 16) | (b[i + 1] << 8) | b[i + 2], i + 3
    if b0 < 0xF0:
        return ((b0 & 0x1F) << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3], i + 4
    return (((b0 & 0x0F) << 28) | (b[i + 1] << 20) | (b[i + 2] << 12) | (b[i + 3] << 4)
            | (b[i + 4] & 0x0F)), i + 5


def _ltf8(b: bytes, i: int) -> tuple[int, int]:
    """CRAM LTF8 integer: as many extra bytes as leading 1 bits (up to 8)."""
    b0, n = b[i], 0
    while n < 8 and b0 & (0x80 >> n):
        n += 1
    value = b0 & (0xFF >> (n + 1)) if n < 8 else 0
    for k in range(1, n + 1):
        value = (value << 8) | b[i + k]
    return value, i + n + 1


def cram_header_text(path: Path) -> str:
    """The SAM header text of a CRAM 2.x/3.x file (first container, first block)."""
    with open(path, "rb") as f:
        head = f.read(26)
        if head[:4] != b"CRAM":
            raise ValueError(f"{path}: not a CRAM file")
        major = head[4]
        if major not in (2, 3):
            raise ValueError(f"{path}: CRAM {major}.x is not supported")
        (length,) = struct.unpack("<i", f.read(4))
        buf = f.read(4096)                      # the container header, then the block
        i = 0
        for _ in range(4):                      # ref_seq_id, start, span, n_records
            _, i = _itf8(buf, i)
        for _ in range(2):                      # record counter, bases
            _, i = _ltf8(buf, i)
        _, i = _itf8(buf, i)                    # number of blocks
        n_landmarks, i = _itf8(buf, i)
        for _ in range(n_landmarks):
            _, i = _itf8(buf, i)
        if major == 3:
            i += 4                              # container CRC32
        method, content_type = buf[i], buf[i + 1]
        _, j = _itf8(buf, i + 2)                # content id
        size, j = _itf8(buf, j)
        _, j = _itf8(buf, j)                    # raw size
        if content_type != 0:
            raise ValueError(f"{path}: first CRAM block is not the file header")
        f.seek(26 + 4 + j)
        data = f.read(size)
    if method == 1:
        data = gzip.decompress(data)
    elif method == 2:
        data = bz2.decompress(data)
    elif method == 3:
        data = lzma.decompress(data)
    elif method != 0:
        raise ValueError(f"{path}: CRAM header compressed with method {method}; "
                         f"run `samtools view -H {path}` and identify that instead")
    (l_text,) = struct.unpack("<i", data[:4])
    return data[4:4 + l_text].decode("utf8", "replace")


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
        return Header(str(path), "cram", _sam_entries(cram_header_text(path).splitlines()))
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
