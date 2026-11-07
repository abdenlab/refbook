"""The refget service (refbook.service), through its request handler.

The seqcol tests make the checks of the seqcol compliance suite in the refget
package (refget/compliance.py) on its own test collections
(fixtures/refget_compliance), with two known differences: comparisons list
refbook's named_sequences attribute, and the order of a single shared element
is null, as spec 3.3 says. The refget Sequences tests use the catalog's
sequences. Both need a catalog (REFBOOK_CATALOG, by default the repository's
build) and are skipped without one.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from refbook import seqcol

FIXTURES = Path(__file__).parent / "fixtures" / "refget_compliance"
BUNDLES = json.loads((FIXTURES / "test_fasta_digests.json").read_text())
CATALOG = Path(os.environ.get("REFBOOK_CATALOG",
                              Path(__file__).resolve().parents[2] / "catalog" / "output" / "build" / "catalog"))
pytestmark = pytest.mark.skipif(not (CATALOG / "catalog.json").exists(), reason="no catalog")

CHR1_MD5 = "6aef897c3d6ff0c78aff06ac189178dd"


@pytest.fixture(scope="module")
def svc():
    from refbook import Catalog
    from refbook.service import Service
    extra = [json.loads(p.read_text()) for p in sorted((FIXTURES / "collection").glob("*.json"))]
    return Service(Catalog(CATALOG), extra)


def get(svc, path, **query):
    r = svc.handle("GET", path, {k: [str(v)] for k, v in query.items()})
    return r, (json.loads(r.body) if "json" in r.headers.get("Content-Type", "") else r.body)


# Sequence Collections

def test_service_info(svc):
    r, info = get(svc, "/service-info")
    assert r.status == 200
    assert {"group", "artifact", "version"} <= set(info["type"])
    assert info["seqcol"]["schema"] == seqcol.SCHEMA


@pytest.mark.parametrize("name", sorted(BUNDLES))
def test_collection_levels(svc, name):
    want = BUNDLES[name]
    d = want["top_level_digest"]
    _, l1 = get(svc, f"/collection/{d}", level=1)
    assert {k: l1[k] for k in want["level1"]} == want["level1"]
    assert l1["sorted_name_length_pairs"] == want["sorted_name_length_pairs_digest"]
    _, l2 = get(svc, f"/collection/{d}", level=2)
    assert {k: l2[k] for k in want["level2"]} == want["level2"]
    assert not set(seqcol.TRANSIENT) & set(l2)
    assert get(svc, f"/collection/{d}")[1] == l2                     # level 2 is the default
    for attr in ("lengths", "names", "sequences", "sorted_sequences", "name_length_pairs"):
        r, value = get(svc, f"/attribute/collection/{attr}/{want['level1'][attr]}")
        assert (r.status, value) == (200, want["level2"][attr]), attr
    r, _ = get(svc, f"/attribute/collection/sorted_name_length_pairs/{l1['sorted_name_length_pairs']}")
    assert r.status == 404                                           # transient: not served
    for attr in ("lengths", "names", "sequences"):
        _, hits = get(svc, "/list/collection", **{attr: want["level1"][attr]})
        assert d in hits["results"], attr
    _, hits = get(svc, "/list/collection", names=want["level1"]["names"], lengths=want["level1"]["lengths"])
    assert d in hits["results"]


def test_list_pages(svc):
    _, all_ = get(svc, "/list/collection")
    assert all_["pagination"] == {"page": 0, "page_size": 100, "total": len(svc.collections)}
    _, p1 = get(svc, "/list/collection", page=1, page_size=5)
    assert p1["results"] == all_["results"][5:10]
    assert get(svc, "/list/collection", page="x")[0].status == 400
    assert get(svc, "/list/collection", not_an_attribute="x")[0].status == 400


@pytest.mark.parametrize("path", sorted((FIXTURES / "comparison").glob("compare_base.fa_*.json")),
                         ids=lambda p: p.stem)
def test_comparison_get_and_post(svc, path):
    want = json.loads(path.read_text())
    for k, n in want["array_elements"]["a_and_b_count"].items():
        if n < 2:                                     # spec 3.3: no order for fewer than 2
            want["array_elements"]["a_and_b_same_order"][k] = None
    a, b = want["digests"]["a"], want["digests"]["b"]
    _, got = get(svc, f"/comparison/{a}/{b}")
    _, local = get(svc, f"/collection/{b}")
    r = svc.handle("POST", f"/comparison/{a}", body=json.dumps(local).encode())
    for c in (got, json.loads(r.body)):
        assert c["digests"] == want["digests"]
        # refbook's named_sequences is the only attribute beyond the suite's.
        assert c["attributes"]["a_and_b"] == sorted(want["attributes"]["a_and_b"] + ["named_sequences"])
        ae = {k: {a: v for a, v in m.items() if a != "named_sequences"} for k, m in c["array_elements"].items()}
        assert ae == want["array_elements"]


def test_openapi_describes_every_route(svc):
    r, doc = get(svc, "/openapi.json")
    assert r.status == 200 and doc["openapi"].startswith("3.")
    assert set(doc["paths"]) == {
        "/sequence/service-info", "/sequence/{id}", "/sequence/{id}/metadata", "/service-info",
        "/collection/{digest}", "/comparison/{digest1}/{digest2}", "/comparison/{digest1}",
        "/list/collection", "/attribute/collection/{attribute}/{digest}"}


def test_seqcol_errors(svc):
    assert get(svc, "/collection/nope")[0].status == 404
    d = BUNDLES["base.fa"]["top_level_digest"]
    assert get(svc, f"/collection/{d}", level=3)[0].status == 400
    assert svc.handle("POST", f"/comparison/{d}", body=b"[1,2").status == 400
    assert svc.handle("POST", f"/comparison/{d}", body=b'{"names": [true]}').status == 400
    assert get(svc, "/nowhere")[0].status == 404


# refget Sequences

def test_sequence_service_info(svc):
    r, info = get(svc, "/sequence/service-info")
    assert r.headers["Content-Type"].startswith("application/vnd.ga4gh.refget.v2.0.0+json")
    assert info["refget"]["algorithms"] == ["md5", "ga4gh"]
    assert info["refget"]["circular_supported"] is False
    assert "insdc" in info["refget"]["identifier_types"]


def test_metadata_of_a_root_and_a_derivative(svc):
    _, m = get(svc, f"/sequence/{CHR1_MD5}/metadata")
    sq = m["metadata"]["ga4gh"]
    assert m["metadata"]["length"] == 248956422
    assert {"alias": "CM000663.2", "naming_authority": "insdc"} in m["metadata"]["aliases"]
    assert m["refbook"] == {**m["refbook"], "root_id": "CM000663.2", "operations": []}
    assert get(svc, f"/sequence/ga4gh:{sq}/metadata")[1] == m
    assert get(svc, "/sequence/insdc:CM000663.2/metadata")[1] == m
    # ucsc:chr1 names the root and its IUPAC -> N derivative.
    r, choices = get(svc, "/sequence/ucsc:chr1/metadata")
    assert r.status == 300 and sq in choices["sequences"] and len(choices["sequences"]) == 2
    other = next(s for s in choices["sequences"] if s != sq)
    _, d = get(svc, f"/sequence/{other}/metadata")
    assert d["refbook"]["operations"] == ["iupac_to_n"]
    assert {a["naming_authority"] for a in d["metadata"]["aliases"]} <= {"ucsc", "grc", "ensembl"}


def test_sequence_ranges(svc):
    r, whole = get(svc, "/sequence/insdc:AJ507799.2")                 # EBV, 171,823 bp
    assert r.status == 200 and len(whole) == 171823
    _, m = get(svc, "/sequence/insdc:AJ507799.2/metadata")
    assert hashlib.md5(whole).hexdigest() == m["metadata"]["md5"]
    r, part = get(svc, "/sequence/insdc:AJ507799.2", start=100000, end=100100)
    assert (r.status, part, r.headers["Accept-Ranges"]) == (200, whole[100000:100100], "none")
    r = svc.handle("GET", "/sequence/insdc:AJ507799.2", headers={"Range": "bytes=100000-100099"})
    assert (r.status, r.body) == (206, whole[100000:100100])
    assert r.headers["Content-Range"] == "bytes 100000-100099/171823"
    assert get(svc, "/sequence/insdc:AJ507799.2", start=5, end=5)[1] == b""
    # A derivative's bases are its root's with the operations applied.
    _, d = get(svc, f"/sequence/{CHR1_MD5}", start=0, end=20000)
    assert len(d) == 20000


@pytest.mark.parametrize("query, headers, status", [
    ({"start": "abc"}, {}, 400),
    ({"start": "200000"}, {}, 400),                    # start beyond the sequence
    ({"start": "10", "end": "5"}, {}, 501),            # circular: not supported
    ({"end": "200000"}, {}, 416),
    ({"start": "1"}, {"Range": "bytes=0-1"}, 400),     # both
    ({}, {"Range": "bytes=0-999999"}, 400),            # out of bounds
    ({}, {"Range": "bytes=0-1,5-6"}, 400),             # several ranges
    ({}, {"Accept": "application/json"}, 406),
])
def test_sequence_errors(svc, query, headers, status):
    r = svc.handle("GET", "/sequence/insdc:AJ507799.2", {k: [v] for k, v in query.items()}, headers)
    assert r.status == status


def test_unknown_sequences(svc):
    assert get(svc, "/sequence/" + "0" * 32)[0].status == 404
    assert get(svc, "/sequence/SQ.nope/metadata")[0].status == 404
    assert get(svc, "/sequence/insdc:nope")[0].status == 404


def test_test_sequences_outside_the_catalog():
    from refbook import Catalog
    from refbook.service import Service
    t = Service(Catalog(CATALOG), sequences=[(b"acgtn\nACGTRY", [("insdc", "X00001.1")]),
                                             (b"GATTACA", [("insdc", "X00002.1")])])
    md5 = hashlib.md5(b"ACGTNACGTRY").hexdigest()
    _, m = get(t, "/sequence/insdc:X00001.1/metadata")
    assert m["metadata"]["md5"] == md5 and m["metadata"]["length"] == 11
    assert m["metadata"]["aliases"] == [{"alias": "X00001.1", "naming_authority": "insdc"}]
    assert get(t, f"/sequence/md5:{md5.upper()}", start=3, end=7)[1] == b"TNAC"
    r = t.handle("GET", f"/sequence/{m['metadata']['ga4gh']}",
                 headers={"Accept": "text/vnd.ga4gh.refget.v1.0.0+plain", "Range": "bytes=0-0"})
    assert (r.status, r.body) == (206, b"A")
    assert get(t, "/sequence/insdc:X00002.1")[1] == b"GATTACA"
    assert get(t, f"/sequence/{CHR1_MD5}", start=10000, end=10010)[1] == b"TAACCCTAAC"   # the catalog still
    assert "insdc" in get(t, "/sequence/service-info")[1]["refget"]["identifier_types"]
