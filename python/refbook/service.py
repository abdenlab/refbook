"""refget over a catalog: GA4GH refget Sequences v2 and Sequence Collections v1.

`Service(cat).handle(method, path, query, headers, body)` answers one request
with a `Response`, so the same handler runs under any HTTP server (`serve`, a
test, a Worker port). The endpoints, as the specs name them (local copies in
_scratch/resources/refget/):

refget Sequences v2 (docs/sequences/README.md)
    GET  /sequence/service-info
    GET  /sequence/:id                 ?start=&end= or a Range header
    GET  /sequence/:id/metadata        plus refbook's account under "refbook"
Sequence Collections v1 (docs/seqcols/README.md)
    GET  /service-info                 with refbook's seqcol schema
    GET  /collection/:digest           ?level=1|2 (default 2)
    GET  /comparison/:digest1/:digest2
    POST /comparison/:digest1          a level-2 collection in the body
    GET  /list/collection              ?page=&page_size=&<attribute>=<level-1 digest>
    GET  /attribute/collection/:attribute/:digest
    GET  /openapi.json                 this API (seqcol 3.6)

:id is any identifier `refbook.store.find` accepts. The collections are the
catalog's stored ones (every flavor and target), plus any level-2 collections
passed as `extra` (for instance the compliance suite's test collections). Circular
sequences are not supported (501, as the spec allows).
"""

import json
import re
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version

from refbook import seqcol, store
from refbook.catalog import Catalog
from refbook.materialize import Bases
from refbook.resolve import collection

REFGET_JSON = "application/vnd.ga4gh.refget.v2.0.0+json; charset=us-ascii"
REFGET_TEXT = "text/vnd.ga4gh.refget.v2.0.0+plain; charset=us-ascii"
SEQCOL_JSON = "application/json"
TEXT_TYPES = ("text/vnd.ga4gh.refget.v2.0.0+plain", "text/plain", "text/*", "*/*")
JSON_TYPES = ("application/vnd.ga4gh.refget.v2.0.0+json", "application/json", "application/*", "*/*")
UINT32 = re.compile(r"\d{1,10}")
RANGE = re.compile(r"bytes=(\d+)-(\d+)")
ORGANIZATION = {"name": "abdenlab", "url": "https://github.com/abdenlab/refbook"}

try:
    VERSION = version("refbook")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    VERSION = "0.0.0"


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


class Error(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _json(obj, status: int = 200, content_type: str = SEQCOL_JSON) -> Response:
    return Response(status, json.dumps(obj).encode(), {"Content-Type": content_type})


def _accepts(headers: dict[str, str], allowed: tuple[str, ...]) -> bool:
    accept = headers.get("accept")
    if not accept:
        return True
    types = [t.split(";")[0].strip().lower() for t in accept.split(",")]
    return any(t in allowed for t in types)


class Service:
    def __init__(self, cat: Catalog, extra: list[dict] = (), bases: Bases | None = None,
                 subsequence_limit: int | None = None):
        self.cat = cat
        self._bases = bases
        self.subsequence_limit = subsequence_limit
        # digest -> (names, lengths, sequences) of every collection served.
        self.collections: dict[str, tuple[list, list, list]] = {}
        for digest in sorted(cat.named):
            c = collection(cat, digest)
            self.collections[digest] = (list(c.names), list(c.lengths), list(c.sequences))
        for x in extra:
            cols = (list(x["names"]), list(x["lengths"]), list(x["sequences"]))
            self.collections[seqcol.digests(*cols)[0]] = cols
        self.level1 = {d: seqcol.level1_attributes(*cols) for d, cols in self.collections.items()}
        # (attribute, level-1 digest) -> one collection with it, for /attribute.
        self.has_attribute: dict[tuple[str, str], str] = {}
        for d, l1 in self.level1.items():
            for attr, digest in l1.items():
                self.has_attribute.setdefault((attr, digest), d)

    @property
    def bases(self) -> Bases:
        if self._bases is None:
            self._bases = Bases(self.cat)
        return self._bases

    def handle(self, method: str, path: str, query: dict[str, list[str]] | None = None,
               headers: dict[str, str] | None = None, body: bytes | None = None) -> Response:
        query = query or {}
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        parts = [p for p in path.split("/") if p]
        try:
            r = self._route(method, parts, query, headers, body)
        except Error as e:
            r = _json({"error": e.message, "status": e.status}, e.status)
        r.headers.setdefault("Access-Control-Allow-Origin", "*")
        return r

    def _route(self, method, parts, query, headers, body) -> Response:
        get = method in ("GET", "HEAD")
        match parts:
            case ["sequence", "service-info"] if get:
                return self.sequence_service_info(headers)
            case ["sequence", ident, "metadata"] if get:
                return self.sequence_metadata(ident, headers)
            case ["sequence", ident] if get:
                return self.sequence(ident, query, headers)
            case ["service-info"] if get:
                return _json(self.seqcol_service_info())
            case ["collection", digest] if get:
                return self.collection(digest, query)
            case ["comparison", a, b] if get:
                return _json(self.compare(self._level2(a), self._level2(b)))
            case ["comparison", a] if method == "POST":
                return _json(self.compare(self._level2(a), self._posted(body)))
            case ["list", "collection"] if get:
                return _json(self.list_collections(query))
            case ["attribute", "collection", attr, digest] if get:
                return _json(self.attribute(attr, digest))
            case ["openapi.json"] if get:
                return _json(openapi())
        raise Error(404, f"no endpoint {method} /{'/'.join(parts)}")

    # refget Sequences

    def sequence_service_info(self, headers) -> Response:
        if not _accepts(headers, JSON_TYPES):
            raise Error(406, "service-info is JSON")
        authorities = sorted({a for pairs in self.cat.sequence_aliases().values() for a, _ in pairs})
        return _json({
            "id": "io.github.abdenlab.refbook.refget",
            "name": "refbook refget sequences",
            "type": {"group": "org.ga4gh", "artifact": "refget", "version": "2.0.0"},
            "description": "Reference sequences of the refbook catalog, from their checksums",
            "organization": ORGANIZATION,
            "version": VERSION,
            "refget": {
                "circular_supported": False,
                "subsequence_limit": self.subsequence_limit,
                "algorithms": ["md5", "ga4gh"],
                "identifier_types": authorities,
            },
        }, content_type=REFGET_JSON)

    def _sequence_id(self, ident: str) -> str:
        found = store.find(self.cat, ident)
        if not found:
            raise Error(404, f"{ident}: not a known sequence")
        if len(found) > 1:
            raise _MultipleChoices(found)
        return found[0]

    def sequence_metadata(self, ident, headers) -> Response:
        if not _accepts(headers, JSON_TYPES):
            raise Error(406, "metadata is JSON")
        try:
            sq = self._sequence_id(ident)
        except _MultipleChoices as m:
            return m.response()
        return _json(store.metadata(self.cat, sq), content_type=REFGET_JSON)

    def sequence(self, ident, query, headers) -> Response:
        if not _accepts(headers, TEXT_TYPES):
            raise Error(406, "sequences are served as text")
        start, end = (query.get(k, [None])[0] for k in ("start", "end"))
        rng = headers.get("range")
        if rng and (start is not None or end is not None):
            raise Error(400, "both a Range header and start/end")
        for v in (start, end):
            if v is not None and not (UINT32.fullmatch(v) and int(v) < 2**32):
                raise Error(400, f"not an unsigned 32-bit integer: {v!r}")
        try:
            sq = self._sequence_id(ident)
        except _MultipleChoices as m:
            return m.response()
        length = self.cat.sequence[sq]["length"]
        status, extra = 200, {}
        if rng:
            m = RANGE.fullmatch(rng.strip())
            if not m:
                raise Error(400, f"not a single byte range: {rng!r}")
            first, last = int(m.group(1)), int(m.group(2))
            if first > last or last >= length:
                raise Error(400, f"range {rng} is out of bounds (length {length})")
            s, e, status = first, last + 1, 206
            extra = {"Content-Range": f"bytes {first}-{last}/{length}", "Accept-Ranges": "bytes"}
        else:
            s = int(start) if start is not None else 0
            e = int(end) if end is not None else length
            if start is not None and s > length:
                raise Error(400, f"start {s} is beyond the sequence (length {length})")
            if s > e:
                raise Error(501, "circular sequences are not supported (start > end)")
            if e > length:
                raise Error(416, f"end {e} is beyond the sequence (length {length})")
            if start is not None or end is not None:
                extra = {"Accept-Ranges": "none"}
        if self.subsequence_limit and (start is not None or end is not None or rng) \
                and e - s > self.subsequence_limit:
            raise Error(416, f"more than {self.subsequence_limit} bases requested")
        bases = store.subsequence(self.cat, sq, s, e, self.bases)
        return Response(status, bases, {"Content-Type": REFGET_TEXT, **extra})

    # Sequence Collections

    def seqcol_service_info(self) -> dict:
        return {
            "id": "io.github.abdenlab.refbook.seqcol",
            "name": "refbook sequence collections",
            "type": {"group": "org.ga4gh", "artifact": "refget-seqcol", "version": "1.0.0"},
            "description": "The refbook catalog's flavors and targets as sequence collections",
            "organization": ORGANIZATION,
            "version": VERSION,
            "seqcol": {"schema": seqcol.SCHEMA},
        }

    def _known(self, digest: str) -> tuple[list, list, list]:
        if digest not in self.collections:
            raise Error(404, f"{digest}: not a known collection")
        return self.collections[digest]

    def _level2(self, digest: str) -> dict:
        return seqcol.level2(*self._known(digest))

    def collection(self, digest, query) -> Response:
        level = query.get("level", ["2"])[0]
        if level not in ("1", "2"):
            raise Error(400, f"level must be 1 or 2, not {level!r}")
        cols = self._known(digest)
        return _json(self.level1[digest] if level == "1" else seqcol.level2(*cols))

    @staticmethod
    def _posted(body: bytes | None) -> dict:
        try:
            c = json.loads(body or b"")
        except ValueError as e:
            raise Error(400, f"the body is not JSON: {e}") from None
        if not isinstance(c, dict):
            raise Error(400, "the body must be a level-2 collection (a JSON object)")
        return c

    @staticmethod
    def compare(a: dict, b: dict) -> dict:
        try:
            return seqcol.compare(a, b)
        except ValueError as e:
            raise Error(400, f"not a seqcol collection: {e}") from None

    def list_collections(self, query) -> dict:
        def number(k, default):
            v = query.get(k, [str(default)])[0]
            if not v.isdigit():
                raise Error(400, f"{k} must be a non-negative integer")
            return int(v)
        page, page_size = number("page", 0), number("page_size", 100)
        if page_size < 1:
            raise Error(400, "page_size must be at least 1")
        filters = {k: v[0] for k, v in query.items() if k not in ("page", "page_size")}
        unknown = set(filters) - set(seqcol.SCHEMA["properties"])
        if unknown:
            raise Error(400, f"not attributes of this server's schema: {sorted(unknown)}")
        hits = [d for d in self.collections if all(self.level1[d].get(k) == v for k, v in filters.items())]
        return {"results": hits[page * page_size:(page + 1) * page_size],
                "pagination": {"page": page, "page_size": page_size, "total": len(hits)}}

    def attribute(self, attr, digest):
        if attr in seqcol.TRANSIENT:
            raise Error(404, f"{attr} is transient: it has no level-2 value to serve")
        d = self.has_attribute.get((attr, digest))
        if d is None:
            raise Error(404, f"no {attr} with digest {digest}")
        return seqcol.level2(*self.collections[d])[attr]


def openapi() -> dict:
    """The OpenAPI 3.1 description of the service's endpoints."""
    def param(name, where, description, required=True, schema=None):
        return {"name": name, "in": where, "required": required, "description": description,
                "schema": schema or {"type": "string"}}

    def ok(description, content_type=SEQCOL_JSON, schema=None):
        return {"description": description, "content": {content_type.split(";")[0]: {"schema": schema or {}}}}

    error = {"description": "An error: a JSON object with `error` and `status`"}
    ident = param("id", "path", "An MD5, an `SQ.` digest (either may carry its `md5:`/`ga4gh:` "
                  "namespace) or a namespaced alias such as `insdc:CM000663.2`")
    digest = param("digest", "path", "A collection's top-level digest")
    collection = {"$ref": "#/components/schemas/Collection"}
    comparison = {"type": "object", "required": ["digests", "attributes", "array_elements"]}
    return {
        "openapi": "3.1.0",
        "info": {"title": "refbook refget", "version": VERSION,
                 "description": "GA4GH refget Sequences v2 and Sequence Collections v1 over the refbook catalog."},
        "paths": {
            "/sequence/service-info": {"get": {"summary": "refget Sequences service-info",
                                               "responses": {"200": ok("service-info", REFGET_JSON)}}},
            "/sequence/{id}": {"get": {
                "summary": "A sequence, or bases [start, end) of it (or a Range header)",
                "parameters": [ident,
                               param("start", "query", "0-based, inclusive", False, {"type": "integer", "minimum": 0}),
                               param("end", "query", "0-based, exclusive", False, {"type": "integer", "minimum": 0}),
                               param("Range", "header", "a single byte range, `bytes=first-last`", False)],
                "responses": {"200": ok("The bases", REFGET_TEXT, {"type": "string"}),
                              "206": ok("The bases of the Range", REFGET_TEXT, {"type": "string"}),
                              "300": ok("The identifier names several sequences", REFGET_JSON),
                              "400": error, "404": error, "406": error, "416": error, "501": error}}},
            "/sequence/{id}/metadata": {"get": {
                "summary": "A sequence's metadata, and refbook's account of it under `refbook`",
                "parameters": [ident],
                "responses": {"200": ok("metadata", REFGET_JSON), "300": ok("Several sequences", REFGET_JSON),
                              "404": error, "406": error}}},
            "/service-info": {"get": {"summary": "Sequence Collections service-info, with the schema",
                                      "responses": {"200": ok("service-info")}}},
            "/collection/{digest}": {"get": {
                "summary": "A collection at level 1 (digests) or 2 (values, without transient attributes)",
                "parameters": [digest, param("level", "query", "1 or 2 (default)", False,
                                             {"type": "integer", "enum": [1, 2], "default": 2})],
                "responses": {"200": ok("The collection", schema=collection), "400": error, "404": error}}},
            "/comparison/{digest1}/{digest2}": {"get": {
                "summary": "Compare two collections (seqcol 3.3)",
                "parameters": [param("digest1", "path", "Collection a"), param("digest2", "path", "Collection b")],
                "responses": {"200": ok("The comparison", schema=comparison), "404": error}}},
            "/comparison/{digest1}": {"post": {
                "summary": "Compare a collection with a level-2 collection in the body (seqcol 3.3)",
                "parameters": [param("digest1", "path", "Collection a")],
                "requestBody": {"required": True, "content": {SEQCOL_JSON: {"schema": collection}}},
                "responses": {"200": ok("The comparison", schema=comparison), "400": error, "404": error}}},
            "/list/collection": {"get": {
                "summary": "Collection digests, paged; filtered by `<attribute>=<level-1 digest>` (AND)",
                "parameters": [param("page", "query", "from 0", False, {"type": "integer", "minimum": 0}),
                               param("page_size", "query", "default 100", False, {"type": "integer", "minimum": 1})],
                "responses": {"200": ok("results and pagination"), "400": error}}},
            "/attribute/collection/{attribute}/{digest}": {"get": {
                "summary": "An attribute's level-2 value by its level-1 digest (not for transient attributes)",
                "parameters": [param("attribute", "path", "An attribute of the schema"),
                               param("digest", "path", "Its level-1 digest")],
                "responses": {"200": ok("The value"), "404": error}}},
        },
        "components": {"schemas": {"Collection": seqcol.SCHEMA}},
    }


class _MultipleChoices(Exception):
    """An alias that names several sequences: 300, listing them."""

    def __init__(self, found: list[str]):
        self.found = found

    def response(self) -> Response:
        return _json({"error": "this identifier names several sequences", "status": 300,
                      "sequences": self.found}, 300, REFGET_JSON)


def serve(service: Service, host: str = "127.0.0.1", port: int = 8000):
    """An HTTP server for a Service (threaded; for local use and tests)."""
    import http.server
    import urllib.parse

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _answer(self, method):
            url = urllib.parse.urlsplit(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else None
            r = service.handle(method, urllib.parse.unquote(url.path),
                               urllib.parse.parse_qs(url.query, keep_blank_values=True),
                               dict(self.headers), body)
            self.send_response(r.status)
            for k, v in r.headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(r.body)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(r.body)

        def do_GET(self):
            self._answer("GET")

        def do_HEAD(self):
            self._answer("HEAD")

        def do_POST(self):
            self._answer("POST")

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Range, Accept")
            self.end_headers()

    return http.server.ThreadingHTTPServer((host, port), Handler)
