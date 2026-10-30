"""Reference genome catalog: identify a header or FASTA against reproduced flavors."""

from ref_registry.catalog import Catalog
from ref_registry.identify import identify
from ref_registry.materialize import materialize
from ref_registry.parse import read_header

__all__ = ["Catalog", "identify", "materialize", "read_header"]
