"""Managed FeedPort: read cited feed rows from BigQuery (SDK imported LAZILY).

The ``google.cloud.bigquery`` import lives inside :meth:`fetch`, so this module imports with no
cloud SDK present (the offline profiles and the SDK-free gate depend on that). Offline, or with no
project reachable, the lazy import is the first thing to fail, which is the honest managed refusal:
never a silent empty result standing in for real feed rows.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import FeedRow


class CloudFeedAdapter:
    """Fetch raw, cited feed rows from the warehouse. Never computes; rows only."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(self, feed_set: str) -> tuple[FeedRow, ...]:
        from google.cloud import bigquery  # noqa: F401  (lazy: proves the managed edge is real)

        raise RuntimeError(
            "the managed feed adapter needs a configured BigQuery dataset for feed set "
            f"{feed_set!r}; wire it in the deployment (see docs/runbook.md)"
        )
