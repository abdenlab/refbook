"""Reference genome catalog: resolve, materialize, fetch and identify sequence collections."""

from refbook.catalog import Catalog
from refbook.fetch import fetch
from refbook.identify import identify
from refbook.materialize import materialize
from refbook.parse import read_header
from refbook.refcache import populate_ref_cache, sequence_by_md5
from refbook.resolve import Collection, collection, resolve

__all__ = ["Catalog", "Collection", "collection", "fetch", "identify", "materialize",
           "populate_ref_cache", "read_header", "resolve", "sequence_by_md5"]
