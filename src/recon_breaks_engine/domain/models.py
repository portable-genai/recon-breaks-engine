"""Vertical artifact models: the reconciliation engine's own request and result types.

The artifacts THIS vertical produces, as opposed to the vertical-neutral machinery in
``kernel.py``. The service's own name is deliberately not substituted into this docstring: a
rendered line whose length depends on ``friendly_name`` fails the repo's own format check for no
reason but the length of its name.

Money is carried two ways on purpose. A :class:`FeedRow` is a RAW cited row exactly as a feed
stated it, so its amount is the decimal STRING the feed carried and its value date is the string
the feed carried: canonicalisation has not happened yet and inventing precision here would hide a
parsing decision. A :class:`CanonicalEntry` is what the deterministic matcher reasons over, so
its amount is an integer count of MINOR units and its value date is a real ``date``: every
downstream comparison is then exact and no float ever touches a consequential number.

A fork building a different vertical rewrites this module and keeps ``kernel.py`` untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from hex_service_kit.enums import LenientStrEnum

from .kernel import Citation, Decision, Severity


class FeedSide(LenientStrEnum):
    """Which side of the reconciliation an entry sits on.

    Deliberately abstract: side A is the internal or first authority (nostro, GL, PSP payout),
    side B the external or second authority (scheme, RTGS, bank statement, OMS). The engine never
    privileges one side; naming them A and B keeps the matcher independent of the feed pairing a
    deployment configures.
    """

    A = "a"
    B = "b"


class BreakType(LenientStrEnum):
    """The kind of residual a break is, decided by the engine from evidence, never by a model."""

    TIMING = "timing"  # a counterpart exists but is dated outside the timing window
    MISSING = "missing"  # no counterpart on the other side at all
    DUPLICATE = "duplicate"  # a same-side entry repeats an already-present one
    FX = "fx"  # a cross-currency counterpart exists but the rate is outside the window
    FEE = "fee"  # a same-currency counterpart exists but differs by more than the fee cap


@dataclass(frozen=True, slots=True)
class FeedRow:
    """One raw, cited row from a feed warehouse, exactly as the feed stated it.

    ``amount`` is the decimal string the feed carried (canonicalisation is a later, deliberate
    step) and ``value_date`` is the date string the feed carried. ``citation`` names the feed and
    line the row came from, so every downstream artifact can be traced to a source line.
    """

    feed_id: str
    line_no: int
    side: FeedSide
    entry_id: str
    amount: str
    currency: str
    value_date: str
    reference: str
    counterparty: str
    account: str = ""
    citation: Citation | None = None


@dataclass(frozen=True, slots=True)
class CanonicalEntry:
    """A normalised entry the matcher reasons over: exact integer money, a real date, keyed text.

    ``amount_minor`` is a signed integer count of minor units. ``reference_key`` and
    ``counterparty_key`` are the canonicalised forms the matcher groups on. ``citation`` is
    carried through from the raw row so a match or a break can always name its source line.
    """

    entry_id: str
    side: FeedSide
    amount_minor: int
    currency: str
    value_date: date
    reference_key: str
    counterparty_key: str
    account: str
    feed_id: str
    line_no: int
    citation: Citation


@dataclass(frozen=True, slots=True)
class Match:
    """One reconciled group: the entries a single pass paired, and the residual it left.

    ``residual_minor`` is the signed amount the pass could not account for (0 for an exact match,
    a fee for a fee-explained match, a small drift for a tolerance or FX match). The pass name is
    kept so the console can show WHICH rule reconciled the group and the eval can score precision
    and recall per pass.
    """

    pass_name: str
    currency: str
    a_entry_ids: tuple[str, ...]
    b_entry_ids: tuple[str, ...]
    a_total_minor: int
    b_total_minor: int
    residual_minor: int
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class Break:
    """A residual entry (or same-side pair) no pass could reconcile, typed by the engine."""

    break_id: str
    break_type: BreakType
    side: FeedSide
    entry_ids: tuple[str, ...]
    amount_minor: int
    currency: str
    value_date: date
    reference_key: str
    counterparty_key: str
    account: str
    age_days: int
    repeat_count: int
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class RankedBreak:
    """A break plus its deterministic integer rank score and the factors that produced it.

    ``factors`` is the per-signal contribution (age, amount band, repeat, criticality) so the
    worklist can show WHY a break sits where it does. Integer scoring throughout: a float score
    would make the ordering sensitive to summation order and reorder the worklist on replay.
    """

    record: Break
    score: int
    rank: int
    factors: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class BreakResolution:
    """A drafted, maker-checker resolution for one break. Routed to human-review-console; it never
    auto-posts.

    The engine decides the break and its facts; a model may only NARRATE ``hypothesis`` and
    ``journal_note`` from those facts, and both are discarded on validation failure. The attribute
    surface (``subject``, ``severity``, ``decision``, ``summary``, ``requires_human_review``,
    ``citations``) is exactly what the review-router payload reads, so an escalation routes with
    no adapter-specific reshaping.
    """

    subject: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    break_id: str
    break_type: BreakType
    hypothesis: str
    journal_note: str
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconRun:
    """The whole outcome of one reconciliation run: matches, ranked breaks, drafted resolutions.

    ``as_of`` is the explicit instant the run was computed against (aging is measured from it), so
    a run replays byte for byte. ``requires_human_review`` is true when any resolution needs a
    human, which is the run-level signal a surface acts on.
    """

    as_of: date
    matches: tuple[Match, ...]
    ranked_breaks: tuple[RankedBreak, ...]
    resolutions: tuple[BreakResolution, ...]
    requires_human_review: bool
    citations: tuple[Citation, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class StoredWorklist:
    """A ranked break worklist as PERSISTED, carrying the tenant it belongs to.

    The tenant is the partition the ``WorklistStorePort`` filters on and the domain authorizes
    against the verified principal (403, never 404, cross-tenant). ``worklist_id`` is the durable
    handle a surface retrieves it by, ``feed_id`` names the feed pair it reconciled, and
    ``ranked_breaks`` is the ordered worklist the run produced, each break still carrying its
    citations.
    """

    worklist_id: str
    tenant: str
    feed_id: str
    as_of: date
    ranked_breaks: tuple[RankedBreak, ...]
