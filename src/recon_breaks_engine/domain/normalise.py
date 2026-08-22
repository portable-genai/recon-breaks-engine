"""Deterministic canonicalisation: raw feed rows in, matchable canonical entries out.

This is the boundary between "what a feed said" and "what the engine reasons over", and it is
PURE: no model, no I/O, stdlib and the policy only. Every decision it makes (how a decimal string
becomes an integer count of minor units, how a value date string becomes a real date, how a
reference or counterparty string becomes a grouping key) is one a human can replay and audit. A
model has no place here: a parser that guessed would put an unverifiable number into a
consequential match.

Canonicalisation raises on a row it cannot parse rather than dropping it or guessing a value. A
silently dropped row is a reconciliation that quietly ignored money, which is the one thing this
service exists to prevent.

Being that boundary is also why the REDACTION of a row's citation lives here: it is the single
place feed text becomes engine data, so masking it once covers every sink downstream (the WORM
audit record, the Hrz7 review payload, the Hrz7 escalation case, the stored worklist and the API
response) instead of once per sink. See :func:`_citation_for`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pii_kit import redact

from .kernel import Citation
from .models import CanonicalEntry, FeedRow
from .pii import PII_PATTERNS
from .policy import minor_exponent

#: Accepted value-date formats, tried in order. ISO first because it is the warehouse norm.
_DATE_FORMATS: tuple[str, ...] = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%Y%m%d")


class CanonicalisationError(ValueError):
    """A row could not be canonicalised. Carries the offending row so the caller can cite it."""


def to_minor(amount: str, currency: str) -> int:
    """Turn a decimal string into a signed integer count of minor units for ``currency``.

    Uses :class:`decimal.Decimal` (never ``float``) and refuses a value with more fractional
    digits than the currency has minor units: ``"1.234"`` in USD is not a rounding opportunity,
    it is a malformed feed the operator must see. The result is exact and order-independent.
    """
    text = amount.strip().replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise CanonicalisationError(f"amount {amount!r} is not a decimal") from exc
    exponent = minor_exponent(currency)
    scaled = value * (10**exponent)
    if scaled != scaled.to_integral_value():
        raise CanonicalisationError(
            f"amount {amount!r} has more precision than {currency.upper()} "
            f"has minor units ({exponent}); refusing to round a feed value"
        )
    return int(scaled)


def to_value_date(value: str) -> date:
    """Parse a value-date string against the accepted formats, refusing an unparseable one."""
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise CanonicalisationError(f"value date {value!r} matches none of {list(_DATE_FORMATS)}")


def reference_key(reference: str) -> str:
    """Fold a reference to its comparison key: upper-case, alphanumerics only.

    Feeds quote the same reference with different punctuation and spacing (``"REF-001 / A"`` vs
    ``"ref001a"``); the key collapses those so the matcher groups them, while a genuinely
    different reference still keys differently.
    """
    return "".join(ch for ch in reference.upper() if ch.isalnum())


def counterparty_key(counterparty: str) -> str:
    """Fold a counterparty name to its comparison key: upper-case, single-spaced, no punctuation.

    Kept looser than the reference key (spaces are preserved as single separators) because a
    counterparty is a name a human reads on the worklist, and collapsing ``"ACME LTD"`` to
    ``"ACMELTD"`` would make the grouping key unreadable in the console for no matching benefit.
    """
    cleaned = "".join(ch if ch.isalnum() else " " for ch in counterparty.upper())
    return " ".join(cleaned.split())


def _citation_for(row: FeedRow) -> Citation:
    """The row's provenance, MASKED, whether the warehouse supplied it or this module built it.

    This is the one place a citation is minted, so it is the one place the mask has to go. The
    audit write used to redact ``redacted_summary`` and then hand the SAME event its citations
    untouched, so an identifier the summary had just lost was persisted verbatim in the immutable
    row beside it; the Hrz7 payload masked the snippet and left the source_id and the title; the
    escalation case and the worklist the API returns masked nothing at all. Fixing that at each
    of those sinks means getting it right four times and forgetting it on the fifth, so it is
    fixed HERE, where raw feed text crosses into the engine and before anything downstream exists
    to leak it.

    All THREE fields are masked, not only the snippet. A citation is evidence text rather than a
    bare locator: a warehouse builds its source_id and its title out of the identifiers the
    payment carried, which is exactly the shape the offline fixture's PII-carrying row has.

    Masking is deliberately NOT applied to ``reference_key`` and ``counterparty_key`` below. They
    are MATCHING keys, and two different identifiers that mask to the same string would then key
    the same and reconcile as one counterparty. A false match is the one failure a reconciliation
    engine may not have, so the keys stay raw in memory and are masked where they are rendered.
    """
    citation = row.citation or Citation(
        source_id=f"{row.feed_id}:{row.line_no}",
        title=f"Feed {row.feed_id} line {row.line_no}",
        snippet=f"{row.entry_id} {row.amount} {row.currency} ref {row.reference}",
    )
    return Citation(
        source_id=redact(citation.source_id, PII_PATTERNS),
        title=redact(citation.title, PII_PATTERNS),
        snippet=redact(citation.snippet, PII_PATTERNS),
    )


def canonicalise_row(row: FeedRow) -> CanonicalEntry:
    """Canonicalise one raw feed row, raising :class:`CanonicalisationError` on a bad value."""
    currency = row.currency.strip().upper()
    return CanonicalEntry(
        entry_id=row.entry_id,
        side=row.side,
        amount_minor=to_minor(row.amount, currency),
        currency=currency,
        value_date=to_value_date(row.value_date),
        reference_key=reference_key(row.reference),
        counterparty_key=counterparty_key(row.counterparty),
        account=row.account,
        feed_id=row.feed_id,
        line_no=row.line_no,
        citation=_citation_for(row),
    )


def canonicalise(rows: Iterable[FeedRow]) -> tuple[CanonicalEntry, ...]:
    """Canonicalise every row, in a stable order (feed id, then line number).

    The sort makes the whole downstream pipeline replay-stable regardless of the order the feed
    port yielded rows in: two runs over the same rows in a different order produce byte-identical
    canonical entries, and therefore byte-identical matches and breaks.
    """
    canonical = [canonicalise_row(row) for row in rows]
    canonical.sort(key=lambda e: (e.feed_id, e.line_no, e.entry_id))
    return tuple(canonical)
