"""A static HTTP server that honors Range requests, for testing remote catalogs.

Python's http.server ignores Range, so it cannot stand in for a static host.
This one serves a directory with single-range support and an optional added
latency per request.

Usage: python -m ref_registry._serve DIR [--port 8765] [--latency-ms 0]
"""

import argparse
import functools
import http.server
import os
import re
import time


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    latency = 0.0

    def log_message(self, *args):  # quiet
        pass

    def send_head(self):
        time.sleep(self.latency)
        path = self.translate_path(self.path)
        if os.path.isdir(path) or not os.path.exists(path):
            return super().send_head()
        size = os.path.getsize(path)
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        f = open(path, "rb")
        if not m:
            self.send_response(200)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return f
        start = int(m.group(1))
        end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        if start >= size:
            f.close()
            self.send_error(416)
            return None
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(1 << 20, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


def serve(directory: str, port: int = 8765, latency_ms: float = 0) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(RangeHandler, directory=directory)
    RangeHandler.latency = latency_ms / 1000
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--latency-ms", type=float, default=0)
    a = ap.parse_args()
    serve(a.directory, a.port, a.latency_ms).serve_forever()
