"""Rule R8: an escalated resolution is ROUTED to Hrz7, not left in a per-repo boolean.

This is the standing gate for the failure the rule exists to prevent. A repo can set
``requires_human_review = True``, pass every other test, and still auto-execute in practice
because nothing ever reads the flag. So the assertions here are about the ROUTING, not the flag:
every drafted resolution produces an outbound review, the payload leaves redacted, the managed
router refuses when it has nowhere to submit, and the on-prem placeholder refuses rather than
swallowing the escalation. The reconciliation service ships no posting port at all, so the only
thing a drafted resolution can do is route to a human.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from recon_breaks_engine.adapters.gcp.review_router import CloudReviewRouter
from recon_breaks_engine.adapters.local.review_router import LocalReviewRouter
from recon_breaks_engine.adapters.onprem.review_router import OnPremReviewRouter
from recon_breaks_engine.api.app import app
from recon_breaks_engine.config import Settings, build_container
from recon_breaks_engine.domain.kernel import Citation, Decision, Severity
from recon_breaks_engine.domain.models import BreakResolution, BreakType

from tests.fixtures import sample_cases


def _settings(profile: str = "local") -> Settings:
    return Settings(profile=profile, audit_path=":memory:", tenant="demo-bank")


def _resolution(severity: Severity = Severity.HIGH) -> BreakResolution:
    return BreakResolution(
        subject="break BRK-missing-A6 (ZETA INC FICTIONAL)",
        severity=severity,
        decision=Decision.ESCALATED,
        summary="One feed carries this item with no counterpart on the other feed.",
        requires_human_review=True,
        break_id="BRK-missing-A6",
        break_type=BreakType.MISSING,
        hypothesis="One feed carries this item with no counterpart on the other feed.",
        journal_note="Investigate missing break; do NOT post until a checker confirms.",
        citations=(Citation(source_id="nostro:7", title="Feed nostro line 7", snippet="A6"),),
    )


def test_a_resolution_produces_an_outbound_review() -> None:
    router = LocalReviewRouter(_settings())
    ref = router.route(_resolution(), maker=sample_cases.ACTOR)
    assert ref, "routing must return a reference, so the caller can record where it went"
    pending = router.outbox.pending()
    assert len(pending) == 1
    review = pending[0].review
    assert review.maker == sample_cases.ACTOR
    assert review.tenant == "demo-bank"
    assert review.severity == Severity.HIGH.value
    assert review.source_key, "a durable outbox needs an idempotency key"


def test_a_critical_resolution_demands_dual_control() -> None:
    router = LocalReviewRouter(_settings())
    router.route(_resolution(Severity.CRITICAL), maker=sample_cases.ACTOR)
    assert router.outbox.pending()[0].review.required_approvals == 2


def test_the_payload_is_redacted_before_it_leaves_the_process() -> None:
    """Hrz7 is a shared sink; a raw identifier must never reach the wire."""
    router = LocalReviewRouter(_settings())
    router.route(sample_cases.pii_resolution(), maker=sample_cases.ACTOR)
    wire = repr(router.outbox.pending()[0].review.to_payload())
    assert sample_cases.PLANTED_NRIC not in wire
    assert "REDACTED" in wire


def test_the_managed_router_refuses_when_no_console_is_configured() -> None:
    """An escalation with nowhere to go must fail loudly, not return as if it were reviewed."""
    router = CloudReviewRouter(Settings(profile="gcp", audit_path=":memory:", review_url=""))
    with pytest.raises(RuntimeError, match="R8"):
        router.route(_resolution(), maker=sample_cases.ACTOR)


def test_the_onprem_placeholder_refuses_rather_than_dropping_the_escalation() -> None:
    router = OnPremReviewRouter(_settings("onprem"))
    with pytest.raises(NotImplementedError, match="R8"):
        router.route(_resolution(), maker=sample_cases.ACTOR)


def test_the_service_routes_every_break_and_opens_cases_for_breaches() -> None:
    """The producer path: every drafted resolution is routed, from inside the service."""
    container = build_container(_settings())
    service = sample_cases.build_service(container)
    run = service.run(
        feed_a=sample_cases.NOSTRO_FEED,
        feed_b=sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF,
        actor=sample_cases.ACTOR,
        tenant="demo-bank",
    )
    assert run.requires_human_review is True
    assert len(container.review_router.outbox.pending()) == len(run.ranked_breaks)
    # The three aged breaks (missing, timing, and the PII-carrying nostro row) breach the 3-day
    # clock and open a case each.
    assert len(container.case_engine.opened) == 3


def test_the_api_routes_the_escalation_in_the_same_request() -> None:
    """The serving path, not just the adapter: an escalation must not depend on a later job."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    body = client.post(
        "/v1/reconcile",
        json={"feed_a": "nostro", "feed_b": "scheme", "as_of": "2026-08-08"},
        headers={"X-Dev-Persona": "auditor"},
    ).json()
    assert body["requires_human_review"] is True
    assert body["breaks"], "a reconcile with breaks must return the ranked worklist"
    assert all(r["requires_human_review"] for r in body["resolutions"])
