"""The reconciliation orchestrator: feeds in, deterministic engine, drafted resolutions out.

This is the one place the pieces meet, and the order is deliberate and load-bearing:

1. read raw cited rows from the feed port (no arithmetic in the adapter);
2. canonicalise them (pure);
3. reconcile with the deterministic multi-pass matcher (pure);
4. rank the residual breaks (pure);
5. for each break, DRAFT a resolution: the engine authors every fact and the journal note; a
   model may narrate a prose HYPOTHESIS from those facts, and its draft is redacted before the
   call, groundedness-checked after it, and DISCARDED for a deterministic note on any failure;
6. every resolution sets ``requires_human_review`` and is ROUTED to Hrz7 through the review kit
   (rule R8): this service ships no posting port at all, so a drafted journal is text a human
   keys into the ledger and nothing here can auto-post;
7. a break that BREACHES its aging or amount threshold additionally opens an escalation case on
   the Hrz7 case spine, with a clock taken from policy;
8. every step writes an already-redacted audit event.

The consequential decisions (reconcile, break type, rank, breach, severity) are all in steps 2-4
and 7 and are pure and replayable. The model touches only step 5's prose.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.case_engine import CaseEnginePort, CaseRequest
from ..ports.feeds import FeedPort
from ..ports.generation import GenerationPort
from ..ports.observability import ObservabilityTracerPort
from ..ports.review_router import ReviewRouterPort
from .break_ranking import BreakRanker
from .kernel import AuditEvent, Citation, Decision, Severity, utcnow
from .match_engine import MatchEngine
from .models import Break, BreakResolution, BreakType, Match, RankedBreak, ReconRun
from .normalise import canonicalise
from .pii import PII_PATTERNS
from .policy import ReconPolicy

#: Any run of digits, used by the groundedness check. A model narration that carries a number the
#: engine never produced is discarded, so the only figures a human ever reads came from the engine.
_DIGITS = re.compile(r"\d+")

#: One span per reconciliation run. Structural attributes only: see :meth:`ResolutionService.run`.
_RUN_SPAN = "recon.run"


def _minor_to_major(amount_minor: int, exponent: int) -> str:
    """Render a minor-unit integer as a major-unit decimal string, for prompts and notes."""
    if exponent == 0:
        return str(amount_minor)
    sign = "-" if amount_minor < 0 else ""
    whole, frac = divmod(abs(amount_minor), 10**exponent)
    return f"{sign}{whole}.{frac:0{exponent}d}"


class ResolutionService:
    """Reconcile two feeds and draft a maker-checker resolution for every break."""

    def __init__(
        self,
        *,
        feeds: FeedPort,
        generation: GenerationPort,
        review_router: ReviewRouterPort,
        audit: AuditSinkPort,
        case_engine: CaseEnginePort,
        tracer: ObservabilityTracerPort,
        policy: ReconPolicy | None = None,
    ) -> None:
        self._feeds = feeds
        self._generation = generation
        self._review = review_router
        self._audit = audit
        self._cases = case_engine
        self._tracer = tracer
        self._policy = policy or ReconPolicy.default()

    def reconcile_only(
        self, *, feed_a: str, feed_b: str, as_of: date
    ) -> tuple[tuple[Match, ...], tuple[RankedBreak, ...]]:
        """Read, canonicalise, match and rank, WITHOUT drafting or routing anything.

        The pure half of a run, exposed so a caller that wants to route selectively (the demo)
        drives the same engine the full :meth:`run` does, rather than a second implementation.
        """
        rows = (*self._feeds.fetch(feed_a), *self._feeds.fetch(feed_b))
        entries = canonicalise(rows)
        outcome = MatchEngine(self._policy).reconcile(entries, as_of=as_of)
        ranked = BreakRanker(self._policy.ranking).rank(outcome.breaks)
        return outcome.matches, ranked

    def resolve_and_route(
        self, ranked: RankedBreak, *, as_of: date, actor: str, tenant: str = ""
    ) -> tuple[BreakResolution, str]:
        """Draft one break's resolution, ROUTE it (rule R8), open a case if it breaches, audit it.

        Returns the resolution and the routing reference. Setting ``requires_human_review`` is not
        the escalation; the ``route`` call is, and it happens here in the same act that drafts the
        resolution. This service has no posting port, so a drafted journal is only ever text a
        human keys in.
        """
        resolution = self._resolve(ranked)
        ref = self._review.route(resolution, maker=actor, tenant=tenant)
        if self._breaches(ranked.record):
            self._open_case(ranked.record, as_of=as_of, actor=actor, tenant=tenant)
        self._audit_break(resolution, actor=actor)
        return resolution, ref

    def run(
        self,
        *,
        feed_a: str,
        feed_b: str,
        as_of: date,
        actor: str,
        tenant: str = "",
    ) -> ReconRun:
        """Reconcile the feed pair end to end: match, rank, then draft and route every break.

        The whole path runs inside one span. Its attributes are STRUCTURAL only, never an entry
        id, a counterparty, a break's figures or any drafted text: a trace backend is not the
        WORM audit trail. It has no redaction stage, a wider read audience and no retention rule
        written against a regulator's requirement, so anything content-shaped that reaches a
        span has left the boundary the ``redact`` call exists to hold, and left it silently.
        """
        with self._tracer.span(
            _RUN_SPAN,
            action="run",
            actor=actor,
            tenant=tenant,
            feed_a=feed_a,
            feed_b=feed_b,
        ):
            matches, ranked = self.reconcile_only(feed_a=feed_a, feed_b=feed_b, as_of=as_of)
            resolutions = [
                self.resolve_and_route(rb, as_of=as_of, actor=actor, tenant=tenant)[0]
                for rb in ranked
            ]
            citations = tuple(_dedupe(c for m in matches for c in m.citations))
            return ReconRun(
                as_of=as_of,
                matches=matches,
                ranked_breaks=ranked,
                resolutions=tuple(resolutions),
                requires_human_review=any(r.requires_human_review for r in resolutions),
                citations=citations,
            )

    # -- per break -----------------------------------------------------------------------------

    def _resolve(self, ranked: RankedBreak) -> BreakResolution:
        brk = ranked.record
        exponent = _exponent(brk.currency)
        major = _minor_to_major(brk.amount_minor, exponent)
        facts = {
            "break_id": brk.break_id,
            "break_type": brk.break_type.value,
            "amount": major,
            "currency": brk.currency,
            "age_days": str(brk.age_days),
            "rank": str(ranked.rank),
            "entries": ", ".join(brk.entry_ids),
        }
        journal_note = self._journal_note(brk, major)
        hypothesis = self._grounded_hypothesis(facts, brk)
        severity = self._severity(brk)
        summary = redact(f"{hypothesis} Proposed journal (draft): {journal_note}", PII_PATTERNS)
        subject = redact(f"break {brk.break_id} ({brk.counterparty_key} FICTIONAL)", PII_PATTERNS)
        return BreakResolution(
            subject=subject,
            severity=severity,
            decision=Decision.ESCALATED,
            summary=summary,
            requires_human_review=True,  # never auto-posts: there is no posting port at all
            break_id=brk.break_id,
            break_type=brk.break_type,
            hypothesis=hypothesis,
            journal_note=journal_note,
            citations=brk.citations,
        )

    def _grounded_hypothesis(self, facts: dict[str, str], brk: Break) -> str:
        """Ask the model for a prose hypothesis, and DISCARD it if it is not grounded.

        The prompt carries only engine facts. The returned draft is redacted, then checked: if it
        contains any digit run that is not one of the engine's own figures, it is discarded for a
        deterministic engine-authored line. The model can therefore only ever rephrase; it can
        never introduce a number a human might act on.
        """
        prompt = _build_prompt(facts)
        try:
            draft = redact(self._generation.draft(prompt), PII_PATTERNS).strip()
        except Exception:
            return _deterministic_hypothesis(brk)
        allowed = {
            facts["amount"],
            facts["age_days"],
            facts["rank"],
            *_DIGITS.findall(facts["amount"]),
        }
        allowed.update(_DIGITS.findall(brk.break_id))
        if not draft or any(token not in allowed for token in _DIGITS.findall(draft)):
            return _deterministic_hypothesis(brk)
        return draft

    def _journal_note(self, brk: Break, major: str) -> str:
        """The engine-authored proposed journal line: numbers come from the engine, not a model.

        Redacted where it is AUTHORED, because it embeds ``reference_key``, and a reference key
        is feed text: a remittance whose payment reference is the payer's national identifier
        puts that identifier straight into the sentence. The note travels further than the
        summary that wraps it (the API returns ``journal_note`` as its own field), so masking the
        summary alone left the raw form one field away on the same response.
        """
        note = (
            f"Investigate {brk.break_type.value} break of {major} {brk.currency} on "
            f"{brk.reference_key or 'unreferenced'}; do NOT post until a checker confirms."
        )
        return redact(note, PII_PATTERNS)

    def _severity(self, brk: Break) -> Severity:
        aging = self._policy.aging
        if brk.amount_minor >= 10 * aging.escalate_amount_minor:
            return Severity.CRITICAL
        if self._breaches(brk):
            return Severity.HIGH
        return Severity.MEDIUM

    def _breaches(self, brk: Break) -> bool:
        aging = self._policy.aging
        return (
            brk.age_days >= aging.escalate_age_days
            or abs(brk.amount_minor) >= aging.escalate_amount_minor
        )

    def _open_case(self, brk: Break, *, as_of: date, actor: str, tenant: str) -> None:
        """Open the escalation case on the Hrz7 spine, with the counterparty name masked.

        Hrz7 is a shared sink, so this is an outbound crossing and the same rule applies as to
        the review payload: the case carries ``counterparty_key`` verbatim, and a
        counterparty name is where a nominee account's underlying national identifier sits. The
        citations arrive already masked from canonicalisation; this field is the one the engine
        still holds raw, because it is a matching key everywhere except right here.
        """
        self._cases.open_case(
            CaseRequest(
                break_id=brk.break_id,
                break_type=brk.break_type.value,
                workflow=f"recon-break-{brk.break_type.value}",
                clock_days=self._policy.aging.escalate_age_days,
                as_of=as_of,
                amount_minor=brk.amount_minor,
                currency=brk.currency,
                counterparty_key=redact(brk.counterparty_key, PII_PATTERNS),
                opened_by=actor,
                tenant=tenant,
                citations=brk.citations,
            )
        )

    def _audit_break(self, resolution: BreakResolution, *, actor: str) -> None:
        self._audit.record(
            AuditEvent(
                action="recon_resolution",
                actor=actor,
                decision=resolution.decision,
                severity=resolution.severity,
                redacted_summary=resolution.summary,
                citations=resolution.citations,
                timestamp=utcnow(),
            )
        )


# -- pure module helpers -----------------------------------------------------------------------


def _exponent(currency: str) -> int:
    from .policy import minor_exponent

    return minor_exponent(currency)


def _build_prompt(facts: dict[str, str]) -> str:
    lines = "\n".join(f"{key}: {value}" for key, value in facts.items())
    return (
        "You are narrating a reconciliation break for an operations analyst. Using ONLY the "
        "facts below, write one sentence describing the likely root cause. Do not invent any "
        "figure, amount, date or count that is not in the facts.\n" + lines
    )


def _deterministic_hypothesis(brk: Break) -> str:
    reasons = {
        BreakType.TIMING: "a value-date timing difference between the two feeds",
        BreakType.MISSING: "an entry present on one feed with no counterpart on the other",
        BreakType.DUPLICATE: "a duplicated entry on one feed",
        BreakType.FX: "an FX conversion outside the accepted rate window",
        BreakType.FEE: "a fee deduction larger than the configured schedule",
    }
    return f"Likely cause: {reasons.get(brk.break_type, 'an unreconciled residual')}."


def _dedupe(citations: Iterable[Citation]) -> list[Citation]:
    seen: set[str] = set()
    out: list[Citation] = []
    for citation in citations:
        if citation.source_id in seen:
            continue
        seen.add(citation.source_id)
        out.append(citation)
    return out
