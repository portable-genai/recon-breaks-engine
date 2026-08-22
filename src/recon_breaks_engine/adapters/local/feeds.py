"""Local FeedPort: deterministic fixture feeds, SDK-free, for the offline profile.

Serves the obviously-synthetic feed pair in ``_recon_fixture`` (the same rows the demo and the
eval reconcile), and fails closed on an unknown feed set rather than returning an empty tuple: a
silently empty feed reconciles to "everything matched" and hides missing money.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import FeedRow
from ._recon_fixture import feed_rows


class LocalFeedAdapter:
    """Return the fixture rows for a named feed set (raw and cited; never computes)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(self, feed_set: str) -> tuple[FeedRow, ...]:
        try:
            return feed_rows(feed_set)
        except KeyError as exc:
            raise KeyError(
                f"unknown feed set {feed_set!r}; the offline fixture serves only the "
                "reconciliation pair (see adapters/local/_recon_fixture.py)"
            ) from exc
