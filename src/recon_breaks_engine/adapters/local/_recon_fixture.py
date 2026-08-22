"""The obviously-synthetic feed pair the offline profile reconciles, single-sourced here.

The SAME rows drive the local feed adapter, the demo and (via the engine, never by copying its
answers) the eval golden set. Every party is fictional and every amount is invented. The pair is
built to exercise every pass and every break type exactly once, so a reader can see the whole
behaviour in one screen and the eval has a labelled target for each:

* exact, tolerance, many-to-one, FX and fee MATCHES; and
* timing, missing, duplicate, FX and fee BREAKS; and
* one PII-carrying nostro row, so the redaction boundary has something to mask on every run.

``ANCHOR_AS_OF`` is the instant the demo and eval reconcile against, so aging is fixed and the
whole run replays byte for byte.
"""

from __future__ import annotations

from datetime import date

from ...domain.kernel import Citation
from ...domain.models import FeedRow, FeedSide

#: The fixed reconciliation instant. Chosen so the aged breaks below breach the 3-day clock.
ANCHOR_AS_OF = date(2026, 8, 8)

#: The planted, obviously synthetic identifiers every redaction proof looks for. They live in the
#: SHIPPED fixture rather than only in a test because a pii_safety metric with nothing to catch
#: stays green through a regression: the eval reconciles these rows on every gate run, so a
#: redaction boundary somebody removes shows up as a red metric and not as a silent PASS.
PLANTED_NRIC = "S1234567D"
PLANTED_EMAIL = "ops@omega-nominees.example"

#: The two feed sets this fixture serves. A is the internal authority (nostro / GL), B external
#: (scheme / statement). Any other name is unknown and the adapter fails closed on it.
FEED_A = "nostro"
FEED_B = "scheme"


def _row(
    feed: str,
    line: int,
    side: FeedSide,
    entry_id: str,
    amount: str,
    currency: str,
    value_date: str,
    reference: str,
    counterparty: str,
    account: str,
) -> FeedRow:
    return FeedRow(
        feed_id=feed,
        line_no=line,
        side=side,
        entry_id=entry_id,
        amount=amount,
        currency=currency,
        value_date=value_date,
        reference=reference,
        counterparty=counterparty,
        account=account,
    )


_A = FeedSide.A
_B = FeedSide.B

_NOSTRO: tuple[FeedRow, ...] = (
    # exact match
    _row(
        FEED_A, 1, _A, "A1", "100.00", "USD", "2026-08-05", "REF-001", "Acme Ltd", "NOSTRO-USD-001"
    ),
    # tolerance match (3c drift)
    _row(
        FEED_A,
        2,
        _A,
        "A2",
        "200.00",
        "USD",
        "2026-08-05",
        "REF-002",
        "Beta Trading",
        "NOSTRO-USD-001",
    ),
    # many-to-one: A3a + A3b sum to scheme B3
    _row(
        FEED_A,
        3,
        _A,
        "A3a",
        "120.00",
        "USD",
        "2026-08-05",
        "REF-003A",
        "Gamma LLP",
        "NOSTRO-USD-001",
    ),
    _row(
        FEED_A,
        4,
        _A,
        "A3b",
        "180.00",
        "USD",
        "2026-08-05",
        "REF-003B",
        "Gamma LLP",
        "NOSTRO-USD-001",
    ),
    # FX match (74.00 USD == 100.00 SGD at policy rate)
    _row(
        FEED_A, 5, _A, "A4", "74.00", "USD", "2026-08-05", "REF-004", "Delta Pte", "NOSTRO-USD-001"
    ),
    # fee match (3.00 fee)
    _row(
        FEED_A,
        6,
        _A,
        "A5",
        "500.00",
        "USD",
        "2026-08-05",
        "REF-005",
        "Epsilon Co",
        "NOSTRO-USD-001",
    ),
    # missing break (no scheme counterpart), aged
    _row(
        FEED_A, 7, _A, "A6", "90.00", "USD", "2026-08-01", "REF-006", "Zeta Inc", "NOSTRO-USD-001"
    ),
    # timing break (scheme dated 4 days later), aged
    _row(
        FEED_A, 8, _A, "A8", "250.00", "USD", "2026-08-01", "REF-008", "Eta Group", "NOSTRO-USD-001"
    ),
    # FX break (rate far outside window)
    _row(
        FEED_A, 9, _A, "A9", "74.00", "USD", "2026-08-07", "REF-009", "Theta Pte", "NOSTRO-USD-001"
    ),
    # fee break (30.00 gap, beyond fee cap)
    _row(
        FEED_A, 10, _A, "A10", "500.00", "USD", "2026-08-07", "REF-010", "Iota Co", "NOSTRO-USD-001"
    ),
    # A nostro-only row carrying personal data, in the shape a remittance warehouse actually
    # stores one: the payment reference IS the payer's national identifier, the counterparty name
    # repeats it, and the warehouse supplied its OWN provenance citation quoting the raw statement
    # narrative. That last part is why the row is here: a citation is evidence text, not a bare
    # locator, and a locator is built out of the identifiers the payment carried. The row
    # reconciles to nothing, so it becomes an aged MISSING break whose resolution, audit record,
    # review payload and escalation case all have to come out masked.
    FeedRow(
        feed_id=FEED_A,
        line_no=99,
        side=_A,
        entry_id="A-PII",
        amount="4200.00",
        currency="USD",
        value_date="2026-08-02",
        reference=PLANTED_NRIC,
        counterparty=f"Omega Nominees NRIC {PLANTED_NRIC}",
        account="NOSTRO-USD-001",
        citation=Citation(
            source_id=f"nostro:99:{PLANTED_NRIC}",
            title=f"Nostro statement line for remitter {PLANTED_NRIC}",
            snippet=f"A-PII 4200.00 USD inward remit NRIC {PLANTED_NRIC} contact {PLANTED_EMAIL}",
        ),
    ),
)

_SCHEME: tuple[FeedRow, ...] = (
    _row(FEED_B, 1, _B, "B1", "100.00", "USD", "2026-08-05", "REF-001", "Acme Ltd", "SCHEME-USD"),
    _row(
        FEED_B, 2, _B, "B2", "200.03", "USD", "2026-08-05", "REF-002", "Beta Trading", "SCHEME-USD"
    ),
    _row(FEED_B, 3, _B, "B3", "300.00", "USD", "2026-08-05", "REF-003", "Gamma LLP", "SCHEME-USD"),
    _row(FEED_B, 4, _B, "B4", "100.00", "SGD", "2026-08-05", "REF-004", "Delta Pte", "SCHEME-SGD"),
    _row(FEED_B, 5, _B, "B5", "497.00", "USD", "2026-08-05", "REF-005", "Epsilon Co", "SCHEME-USD"),
    # timing counterpart, dated later
    _row(FEED_B, 6, _B, "B8", "250.00", "USD", "2026-08-05", "REF-008", "Eta Group", "SCHEME-USD"),
    # duplicate pair on the scheme side (no nostro counterpart)
    _row(FEED_B, 7, _B, "B7a", "150.00", "USD", "2026-08-07", "REF-007", "Kappa Ltd", "SCHEME-USD"),
    _row(FEED_B, 8, _B, "B7b", "150.00", "USD", "2026-08-07", "REF-007", "Kappa Ltd", "SCHEME-USD"),
    # FX break counterpart (200 SGD, far from 74 USD)
    _row(FEED_B, 9, _B, "B9", "200.00", "SGD", "2026-08-07", "REF-009", "Theta Pte", "SCHEME-SGD"),
    # fee break counterpart (470, a 30.00 gap)
    _row(FEED_B, 10, _B, "B10", "470.00", "USD", "2026-08-07", "REF-010", "Iota Co", "SCHEME-USD"),
)

_FEEDS: dict[str, tuple[FeedRow, ...]] = {FEED_A: _NOSTRO, FEED_B: _SCHEME}


def feed_rows(feed_set: str) -> tuple[FeedRow, ...]:
    """The rows of a named feed set, or raise ``KeyError`` for an unknown one (fail closed)."""
    return _FEEDS[feed_set]
