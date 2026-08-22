"""FeedPort: the warehouse edge the reconciliation reads its raw, cited rows from.

The port returns RAW rows and never computes: canonicalisation, matching and every number are the
deterministic domain's job, so the adapter's only responsibility is to hand back the rows a named
feed set contains, each carrying a citation that names the feed and line it came from. Modelled on
the metrics-port shape used elsewhere in the catalog (cited rows in, no arithmetic in the
adapter), so an adapter can never quietly become a second, unaudited engine.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import FeedRow


@runtime_checkable
class FeedPort(Protocol):
    def fetch(self, feed_set: str) -> tuple[FeedRow, ...]:
        """Return every raw, cited row in the named feed set (never computes; rows only).

        An unknown feed set is fail-closed: the adapter raises rather than returning an empty
        tuple, because a silently empty feed reconciles to "everything matched" and hides missing
        money, which is the exact failure this service exists to catch.
        """
        ...
