"""Canonical synthetic fixtures, shared by the unit and contract suites.

Every party is obviously fictional and every identifier is invented (RFC 5737 / RFC 3849 or an
``.example`` domain). The reconciliation feed pair lives in the local adapter's own fixture
(``adapters/local/_recon_fixture.py``) and is re-exported here so a test names it once; this
module adds the shared actor/tenant, a planted identifier for the redaction proofs, and a couple
of hand-built domain artifacts the suites reuse.
"""

from __future__ import annotations

from datetime import date

from recon_breaks_engine.adapters.local._recon_fixture import (
    ANCHOR_AS_OF,
    FEED_A,
    FEED_B,
    PLANTED_EMAIL,
    PLANTED_NRIC,
)
from recon_breaks_engine.config import Container
from recon_breaks_engine.domain.kernel import Citation, Decision, Severity
from recon_breaks_engine.domain.models import BreakResolution, BreakType
from recon_breaks_engine.domain.resolution_service import ResolutionService

#: The verified principal the tests attribute work to (never a client-asserted actor).
ACTOR = "analyst@bank.example"

#: A tenant partition, so the outbound-review assertions are not all on the empty string.
TENANT = "demo-bank"

#: The feed pair the offline profile reconciles, and the instant it reconciles against.
NOSTRO_FEED = FEED_A
SCHEME_FEED = FEED_B
AS_OF: date = ANCHOR_AS_OF

# ``PLANTED_NRIC`` and ``PLANTED_EMAIL`` are re-exported from the offline fixture above, so a
# redaction assertion has independent literals to look for rather than trusting the pattern pack
# to agree with itself. Re-exported rather than copied: they ride on the fixture's PII-carrying
# nostro row, and a suite asserting on its own private literal proves nothing about the row the
# eval and the demo actually reconcile.


def build_service(container: Container) -> ResolutionService:
    """A :class:`ResolutionService` wired to a container's real local adapters."""
    return ResolutionService(
        feeds=container.feeds,
        generation=container.generation,
        review_router=container.review_router,
        audit=container.audit,
        case_engine=container.case_engine,
        tracer=container.tracer,
    )


def pii_resolution() -> BreakResolution:
    """An escalated resolution carrying personal data, for the redact-before-anything proofs."""
    return BreakResolution(
        subject=f"break BRK-missing-A6 (GAMMA LLP FICTIONAL) NRIC {PLANTED_NRIC}",
        severity=Severity.HIGH,
        decision=Decision.ESCALATED,
        summary=f"missing counterpart; contact {PLANTED_EMAIL} re NRIC {PLANTED_NRIC}",
        requires_human_review=True,
        break_id="BRK-missing-A6",
        break_type=BreakType.MISSING,
        hypothesis="One feed carries this item with no counterpart on the other feed.",
        journal_note="Investigate missing break; do NOT post until a checker confirms.",
        citations=(
            Citation(
                source_id="nostro:7", title="Feed nostro line 7", snippet=f"NRIC {PLANTED_NRIC}"
            ),
        ),
    )
