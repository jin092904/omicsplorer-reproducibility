"""External-service benchmark with provenance-preserving adapters.

The primary v1 comparison is deliberately restricted to GEO Series records that
OmicsPlorer, NCBI GEO DataSets, and OmicsDI can all return.
"""

from genofinder_eval.external.models import QuerySpec, SearchHit, SearchResponse

__all__ = ["QuerySpec", "SearchHit", "SearchResponse"]
