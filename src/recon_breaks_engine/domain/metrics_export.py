"""The ops-worklist metrics export: the versioned data contract F5 (control room) consumes.

This is deliberately a DATA CONTRACT, not a shared package: it is warehouse schema rather than an
identical code layer, so the polyrepo packaging rule does not bite. F1 defines it here and in
``schema/ops_worklist_export.schema.json`` plus ``docs/ops-metrics-contract.md``; F2 conforms to
it; F5 reads it with drift guards on both sides.

The export is a PURE function of an engine-computed :class:`ReconRun`: it counts and buckets, it
never re-derives a number, and it stamps an explicit ``as_of`` so a replay of the same run
produces a byte-identical export. Aging buckets and the SLA clock state come straight from the
engine's ``age_days`` and the aging policy, so the control room and the engine can never disagree
about how old a break is.
"""

from __future__ import annotations

from datetime import date

from .models import ReconRun
from .policy import AgingPolicy

#: The contract version. F5's drift guard pins this exact string; a breaking change bumps it.
SCHEMA_VERSION = "ops-worklist-export/v1"

#: Aging bucket upper bounds in days (inclusive). The final open-ended bucket catches the rest.
_BUCKET_BOUNDS: tuple[tuple[str, int], ...] = (
    ("d0_1", 1),
    ("d2_3", 3),
    ("d4_7", 7),
)
_OVERFLOW_BUCKET = "d8_plus"


def _bucket_for(age_days: int) -> str:
    for name, upper in _BUCKET_BOUNDS:
        if age_days <= upper:
            return name
    return _OVERFLOW_BUCKET


def build_worklist_export(
    run: ReconRun,
    *,
    feed_id: str,
    as_of: date,
    aging: AgingPolicy,
) -> dict[str, object]:
    """Build the ops-worklist export dict for one reconciliation run (schema-conformant).

    ``throughput`` is the number of groups the passes reconciled this run and ``queue_depth`` the
    number of breaks left; both are counts of engine output, not recomputations. The SLA clock
    state splits the breaks into those that have breached the aging threshold and those still
    within it, again from the engine's own ``age_days``.
    """
    buckets: dict[str, int] = {name: 0 for name, _ in _BUCKET_BOUNDS}
    buckets[_OVERFLOW_BUCKET] = 0
    breached = 0
    for ranked in run.ranked_breaks:
        age = ranked.record.age_days
        buckets[_bucket_for(age)] += 1
        if age >= aging.escalate_age_days:
            breached += 1
    queue_depth = len(run.ranked_breaks)
    return {
        "schema_version": SCHEMA_VERSION,
        "feed_id": feed_id,
        "as_of": as_of.isoformat(),
        "queue_depth": queue_depth,
        "throughput": len(run.matches),
        "aging_buckets": buckets,
        "sla_clock_state": {
            "breached": breached,
            "within": queue_depth - breached,
            "escalate_age_days": aging.escalate_age_days,
        },
    }
