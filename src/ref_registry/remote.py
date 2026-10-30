"""Read a catalog over HTTP: whole small files into a cache, big ones by range.

`HttpFile` is a seekable, read-only file object over HTTP range requests, so
pyarrow can read Parquet from it as from a local file. It counts requests and
bytes, which is what remote cost comes down to.
"""

import hashlib
import io
import os
import tempfile
import urllib.request
from pathlib import Path

USER_AGENT = "ref-registry (reference genome catalog)"


def _request(url: str, headers: dict | None = None, method: str = "GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(req, timeout=120)


class HttpFile(io.RawIOBase):
    def __init__(self, url: str, size: int | None = None):
        self.url, self.pos, self.requests, self.bytes = url, 0, 0, 0
        if size is None:
            with _request(url, method="HEAD") as r:
                size = int(r.headers["Content-Length"])
        self.size = size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: 0, 1: self.pos, 2: self.size}[whence] + offset
        return self.pos

    def readinto(self, buf) -> int:
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        with _request(self.url, {"Range": f"bytes={self.pos}-{self.pos + n - 1}"}) as r:
            if r.status != 206:
                raise OSError(f"{self.url}: server ignored the Range header (HTTP {r.status})")
            data = r.read()
        self.requests += 1
        self.bytes += len(data)
        buf[:len(data)] = data
        self.pos += len(data)
        return len(data)


def download(url: str, dest: Path, sha256: str, size: int) -> Path:
    """Fetch url into dest (atomically), checking size and sha256 against the manifest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
    h, n = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as f, _request(url) as r:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                f.write(chunk)
                h.update(chunk)
                n += len(chunk)
        if n != size or h.hexdigest() != sha256:
            raise OSError(f"{url}: downloaded {n} bytes with sha256 {h.hexdigest()}, "
                          f"manifest says {size} bytes, {sha256}")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest
