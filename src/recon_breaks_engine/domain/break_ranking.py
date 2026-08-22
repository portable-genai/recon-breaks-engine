"""Deterministic break ranking: a break worklist ordered by an explainable integer score.

Pure stdlib over the injected :class:`RankingPolicy`. The score is the sum of four integer
factors (age, an amount BAND rather than the raw amount, repeat count, account criticality), and
the per-factor contributions travel on the :class:`RankedBreak` so the console can show WHY a
break sits where it does. Integer arithmetic throughout: a float score would make the ordering
sensitive to summation order and could reorder the worklist on replay, and a worklist that
reorders itself is not a worklist.

Ties break on ``break_id``, which is itself deterministic, so the whole ordering is total and
replay-stable.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import Break, RankedBreak
from .policy import RankingPolicy


def _amount_band(amount_minor: int) -> int:
    """A coarse log-scaled band for an absolute amount, so one huge break cannot swamp aging.

    Band n covers amounts up to 10**n minor units, capped at 9. A linear amount contribution
    would let a single very large break dominate every other signal; a band keeps large amounts
    important without making them the only thing that matters.
    """
    value = abs(amount_minor)
    band = 0
    threshold = 10
    while value >= threshold and band < 9:
        band += 1
        threshold *= 10
    return band


class BreakRanker:
    """Score and order a set of breaks into a worklist."""

    def __init__(self, policy: RankingPolicy) -> None:
        self._policy = policy

    def factors(self, brk: Break) -> tuple[tuple[str, int], ...]:
        """The per-signal integer contributions to ``brk``'s score, in a fixed order."""
        return (
            ("age", brk.age_days * self._policy.age_weight),
            ("amount", _amount_band(brk.amount_minor) * self._policy.amount_band_weight),
            ("repeat", max(brk.repeat_count - 1, 0) * self._policy.repeat_weight),
            ("criticality", self._policy.criticality(brk.account)),
        )

    def score(self, brk: Break) -> int:
        return sum(value for _name, value in self.factors(brk))

    def rank(self, breaks: Iterable[Break]) -> tuple[RankedBreak, ...]:
        """Return the breaks as a ranked worklist, most urgent first, ties broken by id."""
        scored = [(self.score(brk), brk) for brk in breaks]
        # Sort by descending score, then ascending break_id for a total, stable order.
        scored.sort(key=lambda pair: (-pair[0], pair[1].break_id))
        return tuple(
            RankedBreak(record=brk, score=value, rank=index + 1, factors=self.factors(brk))
            for index, (value, brk) in enumerate(scored)
        )
