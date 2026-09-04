"""Shared conversion from an escalated result to an ``review-kit`` Review payload.

Lives in the adapter layer, not the pure domain, because it depends on the kit. The subject, the
summary and EVERY field of every citation (the locator and the title as well as the snippet) are
redacted BEFORE they leave the process (the same redact-before-anything rule the audit write obeys),
using the shared ``pii-kit``, so no raw identifier reaches human-review-console over the wire;
human-review-console redacts again before its own audit write (defence in depth). Canonicalisation
has already masked these citations upstream, and this pass is deliberately kept anyway: this module
converts whatever a caller hands it, and a boundary that trusts its input is a boundary only for the
callers that happen to be correct today. ``maker`` and ``tenant`` are asserted here and trusted by
human-review-console because the caller is an authenticated S2S service; per-hop on-behalf-of token
exchange is the deferred next layer.
"""

from __future__ import annotations

import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.kernel import Severity
from ..domain.models import BreakResolution

#: Cap the citations carried on the wire: enough for a reviewer to trace the decision without
#: copying the whole evidence set into the console.
_MAX_CITATIONS = 8

#: The console is a SHARED sink: a case filed in one market may still quote another market's
#: national id, so the payload is scrubbed against every jurisdiction's rows plus the universal
#: email/phone rows, whatever this deployment's own ``domain.pii.JURISDICTIONS`` selects.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)

#: Bands that demand dual control (two approvals) rather than a single checker.
_DUAL_CONTROL = (Severity.CRITICAL,)


def _redact(text: str) -> str:
    """Mask every jurisdiction's identifiers plus email/phone, and normalise whitespace."""
    return re.sub(r"\s+", " ", pii_redact(text, _ALL_PATTERNS)).strip()


def _kit_citations(result: BreakResolution) -> tuple[KitCitation, ...]:
    """Mask ALL THREE citation fields, and dedupe on the masked source_id.

    Redacting only the snippet reads like enough and is not: a warehouse builds a locator and a
    title out of the identifiers the payment carried, so ``nostro:99:S1234567D`` / "statement
    line for remitter S1234567D" puts the identifier on the wire while the snippet beside them
    comes out clean. The source_id is a locator by role, not by content.

    Dedupe on the MASKED source_id, not the raw one, for the same reason ``result_to_review``
    derives its keys from the masked subject: redaction is deterministic, so a retried delivery
    produces the same masked locator and stays idempotent at the console, whereas deduping on
    the raw id would let two rows that mask identically both reach a sink that then sees them as
    one.
    """
    seen: set[str] = set()
    out: list[KitCitation] = []
    for citation in result.citations:
        source_id = _redact(citation.source_id)
        if source_id in seen:
            continue
        seen.add(source_id)
        out.append(
            KitCitation(
                source_id=source_id,
                title=_redact(citation.title),
                snippet=_redact(citation.snippet),
            )
        )
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def result_to_review(result: BreakResolution, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when a result escalates."""
    # Redact ONCE and reuse: the subject is a shared sink's field, so every place the subject
    # text reaches the wire (the case reference AND the idempotency key, not only the ``subject``
    # field) must carry the masked form. Deriving these from the raw subject leaked the identifier
    # into ``case_ref`` and ``source_key`` while ``subject`` itself was clean. Redaction is
    # deterministic, so a retried delivery still produces the same masked key and stays idempotent.
    subject = _redact(result.subject)
    return Review(
        action="recon_breaks_engine:resolution",
        subject=subject,
        maker=maker,
        tenant=tenant,
        summary=_redact(result.summary),
        severity=result.severity.value,
        required_approvals=2 if result.severity in _DUAL_CONTROL else 1,
        sod_group="recon_breaks_engine-maker-checker",
        case_ref=subject,
        # Producer-owned, tenant-scoped key so a retried delivery is idempotent at the console.
        source_key=f"recon-breaks-engine:{subject}:{result.severity.value}",
        citations=_kit_citations(result),
    )
