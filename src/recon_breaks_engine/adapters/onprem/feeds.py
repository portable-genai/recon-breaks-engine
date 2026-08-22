"""On-prem FeedPort: fail-fast portability placeholder (the sovereign-exit proof, P-12)."""

from __future__ import annotations

from ...config import Settings
from ...domain.models import FeedRow


class OnPremFeedAdapter:
    """Satisfies FeedPort but refuses at call time: the client wires its own warehouse."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(self, feed_set: str) -> tuple[FeedRow, ...]:
        raise NotImplementedError(
            "on-prem feed adapter is a portability placeholder: bind the client's own feed "
            "warehouse (see docs/onprem-migration.md)"
        )
