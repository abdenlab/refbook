"""Read a catalog over HTTP: whole small files into a cache, big ones by range.

`HttpFile` is a seekable, read-only file object over HTTP range requests, so
pyarrow can read Parquet from it as from a local file. It counts requests and
bytes, which is what remote cost comes down to.

Redirects are followed here, not by urllib, for two reasons. Hosts such as
Hugging Face answer every file request with a redirect to a CDN, so following
it once and reading the CDN URL directly halves the round trips and keeps bulk
traffic off the (rate-limited) origin. And urllib would copy an Authorization
header onto the redirected request; a token is sent only to the origin host.

`prefetch(ranges)` fetches byte ranges concurrently; later reads inside them
are served from memory.
"""

import hashlib
import io
import os
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

USER_AGENT = "refbook (reference genome catalog)"
TOKEN_HOSTS = {"huggingface.co"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _token(host: str) -> str | None:
    """A Hugging Face token for huggingface.co: HF_TOKEN, else the stored `hf auth login`."""
    if host not in TOKEN_HOSTS:
        return None
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    path = home / "token"
    return path.read_text().strip() if path.exists() else None


def _open(url: str, headers: dict | None = None, method: str = "GET", max_redirects: int = 5):
    """Open url, following redirects ourselves; returns (response, final url)."""
    for _ in range(max_redirects + 1):
        h = {"User-Agent": USER_AGENT, **(headers or {})}
        token = _token(urlparse(url).hostname or "")
        if token:
            h["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, method=method, headers=h)
        try:
            return _opener.open(req, timeout=120), url
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urljoin(url, e.headers["Location"])
                continue
            raise
    raise OSError(f"{url}: too many redirects")


class HttpFile(io.RawIOBase):
    def __init__(self, url: str, size: int | None = None, workers: int = 16):
        self.url, self.pos, self.requests, self.bytes = url, 0, 0, 0
        self.workers = workers
        self._final: str | None = None          # the URL after redirects (e.g. a signed CDN URL)
        self._cache: list[tuple[int, bytes]] = []
        if size is None:
            r, self._final = _open(url, method="HEAD")
            with r:
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

    def _get(self, start: int, end: int) -> bytes:
        """Bytes [start, end) by a range request, resolving the redirect once."""
        for attempt in (0, 1):
            target = self._final or self.url
            try:
                r, final = _open(target, {"Range": f"bytes={start}-{end - 1}"})
            except urllib.error.HTTPError as e:
                if attempt == 0 and self._final and e.code in (401, 403, 410):
                    self._final = None            # signed URL expired: resolve again
                    continue
                raise
            with r:
                if r.status != 206:
                    raise OSError(f"{self.url}: server ignored the Range header (HTTP {r.status})")
                data = r.read()
            self._final = final
            self.requests += 1
            self.bytes += len(data)
            return data
        raise OSError(f"{self.url}: could not read bytes {start}-{end}")

    def prefetch(self, ranges: list[tuple[int, int]]) -> None:
        """Fetch [start, end) ranges concurrently; keep them for later reads."""
        todo = [(s, e) for s, e in ranges if not self._cached(s, e)]
        if not todo:
            return
        if self._final is None:                   # resolve the redirect once, before fanning out
            s, e = todo.pop(0)
            self._cache.append((s, self._get(s, e)))
        with ThreadPoolExecutor(self.workers) as pool:
            for (s, _), data in zip(todo, pool.map(lambda r: self._get(*r), todo)):
                self._cache.append((s, data))

    def _cached(self, start: int, end: int) -> bytes | None:
        for s, data in self._cache:
            if s <= start and end <= s + len(data):
                return data[start - s:end - s]
        return None

    def clear(self) -> None:
        self._cache = []

    def readinto(self, buf) -> int:
        n = min(len(buf), self.size - self.pos)
        if n <= 0:
            return 0
        data = self._cached(self.pos, self.pos + n)
        if data is None:
            data = self._get(self.pos, self.pos + n)
        buf[:len(data)] = data
        self.pos += len(data)
        return len(data)


def resolve(url: str) -> str:
    """The URL a GET of url ends up at (e.g. a signed CDN URL), without reading the body."""
    r, final = _open(url, {"Range": "bytes=0-0"})
    r.close()
    return final


def download(url: str, dest: Path, sha256: str, size: int) -> Path:
    """Fetch url into dest (atomically), checking size and sha256 against the manifest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
    h, n = hashlib.sha256(), 0
    try:
        r, _ = _open(url)
        with os.fdopen(fd, "wb") as f, r:
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
