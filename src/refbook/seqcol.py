"""GA4GH sequence collection (seqcol) digests.

From the spec (github.com/ga4gh/refget, docs/seqcols/README.md): canonicalize
each attribute with RFC-8785, digest it with sha512t24u; the top-level digest
covers the inherent attributes, names and sequences.
"""

import base64
import hashlib
import json

INHERENT = ("names", "sequences")


def canonical(item) -> bytes:
    """RFC-8785 for our data: ASCII keys, no floats, integers within 64 bits."""
    return json.dumps(item, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                      sort_keys=True).encode("utf8")


def sha512t24u(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha512(data).digest()[:24]).decode("ascii")


def digests(names: list[str], lengths: list[int], sequences: list[str]) -> tuple[str, dict]:
    """(top-level digest, level-1 digests) of a collection; sequences are SQ. ids."""
    obj = {"lengths": lengths, "names": names, "sequences": sequences}
    level1 = {k: sha512t24u(canonical(v)) for k, v in obj.items()}
    return sha512t24u(canonical({k: level1[k] for k in INHERENT})), level1
