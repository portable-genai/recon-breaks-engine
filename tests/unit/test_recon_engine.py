"""The deterministic core: canonicalisation, the multi-pass matcher, ranking, and resolution.

Every consequential decision in this service is made here in pure stdlib, so this is where the
proofs live: each pass matches what it should, a stricter pass wins over a looser one, the
many-to-one search terminates, the residue is typed correctly, the ranking is total and stable,
the run replays byte for byte, and the model's narration is discarded when it is not grounded.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from hex_service_kit.serialization import to_jsonable
from pii_kit import pack_leak

from recon_breaks_engine.api.schemas import ReconcileResponse
from recon_breaks_engine.config import build_container
from recon_breaks_engine.domain.kernel import Citation
from recon_breaks_engine.domain.match_engine import MatchEngine
from recon_breaks_engine.domain.metrics_export import build_worklist_export
from recon_breaks_engine.domain.models import BreakType, CanonicalEntry, FeedSide
from recon_breaks_engine.domain.normalise import (
    CanonicalisationError,
    reference_key,
    to_minor,
    to_value_date,
)
from recon_breaks_engine.domain.pii import PII_PATTERNS
from recon_breaks_engine.domain.policy import ReconPolicy
from recon_breaks_engine.domain.resolution_service import ResolutionService
from recon_breaks_engine.ports import PORT_PROTOCOLS
from recon_breaks_engine.ports.case_engine import CaseHandle, CaseRequest

from tests.conftest import local_settings
from tests.fixtures import sample_cases

_POLICY = ReconPolicy.default()
_AS_OF = date(2026, 8, 8)


def _entry(
    entry_id: str,
    side: FeedSide,
    amount_minor: int,
    *,
    currency: str = "USD",
    value_date: date = date(2026, 8, 5),
    reference_key_: str = "REF1",
    counterparty_key: str = "ACME",
    account: str = "NOSTRO-USD-001",
) -> CanonicalEntry:
    return CanonicalEntry(
        entry_id=entry_id,
        side=side,
        amount_minor=amount_minor,
        currency=currency,
        value_date=value_date,
        reference_key=reference_key_,
        counterparty_key=counterparty_key,
        account=account,
        feed_id="f",
        line_no=1,
        citation=Citation(source_id=f"f:{entry_id}", title="t", snippet="s"),
    )


# -- canonicalisation --------------------------------------------------------------------------


def test_to_minor_is_exact_and_currency_aware() -> None:
    assert to_minor("100.00", "USD") == 10000
    assert to_minor("1,234.50", "USD") == 123450
    assert to_minor("250", "JPY") == 250  # zero-decimal currency


def test_to_minor_refuses_more_precision_than_the_currency_has() -> None:
    with pytest.raises(CanonicalisationError):
        to_minor("1.234", "USD")
    with pytest.raises(CanonicalisationError):
        to_minor("1.5", "JPY")


def test_value_date_and_reference_key_normalise() -> None:
    assert to_value_date("2026-08-05") == date(2026, 8, 5)
    assert to_value_date("05/08/2026") == date(2026, 8, 5)
    assert reference_key("REF-001 / A") == reference_key("ref001a")


# -- the passes --------------------------------------------------------------------------------


def _reconcile(entries: list[CanonicalEntry]) -> tuple[list, list]:
    outcome = MatchEngine(_POLICY).reconcile(entries, as_of=_AS_OF)
    return list(outcome.matches), list(outcome.breaks)


def test_exact_pass_matches_identical_entries() -> None:
    matches, breaks = _reconcile([_entry("A", FeedSide.A, 10000), _entry("B", FeedSide.B, 10000)])
    assert not breaks
    assert [m.pass_name for m in matches] == ["exact"]


def test_tolerance_pass_matches_within_allowance_and_leaves_a_residual() -> None:
    matches, breaks = _reconcile([_entry("A", FeedSide.A, 20000), _entry("B", FeedSide.B, 20003)])
    assert not breaks
    assert matches[0].pass_name == "tolerance"
    assert matches[0].residual_minor == -3


def test_a_stricter_pass_wins_over_a_looser_one() -> None:
    """An exact counterpart must be taken by exact, leaving the near one to tolerance, not both.

    Two B entries share the reference: one is an exact amount match, one is within tolerance. The
    exact pass must consume the exact one, so the tolerance pass can only see the other.
    """
    entries = [
        _entry("A", FeedSide.A, 20000),
        _entry("Bexact", FeedSide.B, 20000),
        _entry("Bnear", FeedSide.B, 20003),
    ]
    matches, breaks = _reconcile(entries)
    exact = [m for m in matches if m.pass_name == "exact"]
    assert exact and exact[0].b_entry_ids == ("Bexact",)
    # The near B had no A left to pair with, so it is a residue break, not a second match.
    assert any(b.entry_ids == ("Bnear",) for b in breaks)


def test_many_to_one_sums_a_bounded_subset_and_terminates() -> None:
    entries = [
        _entry("A1", FeedSide.A, 12000, reference_key_="RA1"),
        _entry("A2", FeedSide.A, 18000, reference_key_="RA2"),
        _entry("B", FeedSide.B, 30000, reference_key_="RB"),
    ]
    matches, breaks = _reconcile(entries)
    assert not breaks
    m = matches[0]
    assert m.pass_name == "many_to_one"
    assert set(m.a_entry_ids) == {"A1", "A2"} and m.b_entry_ids == ("B",)


def test_each_residue_break_type_is_classified() -> None:
    entries = [
        # missing: A with no counterpart
        _entry("Amiss", FeedSide.A, 9000, reference_key_="RMISS"),
        # duplicate: two identical B entries, no A
        _entry("Bd1", FeedSide.B, 15000, reference_key_="RDUP", counterparty_key="KAPPA"),
        _entry("Bd2", FeedSide.B, 15000, reference_key_="RDUP", counterparty_key="KAPPA"),
        # timing: same amount+ref, dates > window apart
        _entry("At", FeedSide.A, 25000, reference_key_="RT", value_date=date(2026, 8, 1)),
        _entry("Bt", FeedSide.B, 25000, reference_key_="RT", value_date=date(2026, 8, 6)),
        # fee: same ref, gap beyond fee cap
        _entry("Afee", FeedSide.A, 50000, reference_key_="RFEE"),
        _entry("Bfee", FeedSide.B, 47000, reference_key_="RFEE"),
        # fx: cross currency, rate outside window
        _entry("Afx", FeedSide.A, 7400, reference_key_="RFX"),
        _entry("Bfx", FeedSide.B, 20000, reference_key_="RFX", currency="SGD"),
    ]
    _matches, breaks = _reconcile(entries)
    by_type = {b.break_type for b in breaks}
    assert {
        BreakType.MISSING,
        BreakType.DUPLICATE,
        BreakType.TIMING,
        BreakType.FEE,
        BreakType.FX,
    } <= by_type


def test_the_run_replays_byte_for_byte_regardless_of_input_order() -> None:
    entries = [
        _entry("A", FeedSide.A, 10000),
        _entry("B", FeedSide.B, 10000),
        _entry("Amiss", FeedSide.A, 9000, reference_key_="RMISS"),
    ]
    first = MatchEngine(_POLICY).reconcile(entries, as_of=_AS_OF)
    second = MatchEngine(_POLICY).reconcile(list(reversed(entries)), as_of=_AS_OF)
    assert first == second


# -- ranking -----------------------------------------------------------------------------------


def test_ranking_is_total_stable_and_its_factors_sum_to_the_score() -> None:
    _matches, breaks = _reconcile(
        [
            _entry("Aold", FeedSide.A, 9000, reference_key_="ROLD", value_date=date(2026, 8, 1)),
            _entry("Anew", FeedSide.A, 9000, reference_key_="RNEW", value_date=date(2026, 8, 7)),
        ]
    )
    from recon_breaks_engine.domain.break_ranking import BreakRanker

    ranked = BreakRanker(_POLICY.ranking).rank(breaks)
    assert [rb.rank for rb in ranked] == [1, 2]
    # The older break outranks the newer one, all else equal.
    assert ranked[0].record.age_days >= ranked[1].record.age_days
    for rb in ranked:
        assert sum(v for _n, v in rb.factors) == rb.score


# -- resolution: the model narrates, and an ungrounded draft is discarded -----------------------


class _FakeGeneration:
    def __init__(self, text: str) -> None:
        self._text = text

    def draft(self, prompt: str) -> str:
        return self._text


def _service_with(generation: object) -> ResolutionService:
    container = build_container(local_settings())
    return ResolutionService(
        feeds=container.feeds,
        generation=generation,  # type: ignore[arg-type]
        review_router=container.review_router,
        audit=container.audit,
        case_engine=container.case_engine,
        tracer=container.tracer,
    )


def test_an_ungrounded_model_number_is_discarded() -> None:
    """A narration carrying a figure the engine never produced must not reach the resolution."""
    service = _service_with(_FakeGeneration("Root cause is a 9999999 discrepancy, obviously."))
    run = service.run(
        feed_a=sample_cases.NOSTRO_FEED,
        feed_b=sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF,
        actor=sample_cases.ACTOR,
    )
    assert run.resolutions
    for resolution in run.resolutions:
        assert "9999999" not in resolution.summary
        assert resolution.requires_human_review is True


def test_a_grounded_model_narration_is_used_verbatim() -> None:
    service = _service_with(_FakeGeneration("The feeds disagree on this item and need review."))
    run = service.run(
        feed_a=sample_cases.NOSTRO_FEED,
        feed_b=sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF,
        actor=sample_cases.ACTOR,
    )
    assert any("need review" in r.hypothesis for r in run.resolutions)


#: The ATTRIBUTION fields on an audit row, a review and a case request: who did it, and for whom.
#: They are excluded from every PII scan below because the verified principal is an address BY
#: DESIGN, so a blanket scan over a whole record could never go green, and a check that can never
#: go green is a check somebody switches off. Everything else on those records is content.
_ATTRIBUTION = frozenset({"actor", "maker", "opened_by", "tenant"})


def _content(value: object) -> object:
    """``value`` with every attribution field dropped, at any depth, ready to scan for PII."""
    if isinstance(value, dict):
        return {k: _content(v) for k, v in value.items() if k not in _ATTRIBUTION}
    if isinstance(value, list | tuple):
        return [_content(v) for v in value]
    return value


class _SpyGeneration:
    """The real local narrator with a tap on what the model boundary was actually handed.

    Asserting on the drafted prose alone cannot see this: a narrator is free to drop a fact it
    was given, so a hypothesis can read clean while the raw identifier still crossed into the
    model's context. The tap records the PROMPT, which is the boundary the rule is about.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.prompts: list[str] = []

    def draft(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._inner.draft(prompt)  # type: ignore[attr-defined]


class _SpyCaseEngine:
    """The real local case recorder with a tap on the request that would cross to
    human-review-console.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.requests: list[CaseRequest] = []

    def open_case(self, request: CaseRequest) -> CaseHandle:
        self.requests.append(request)
        return self._inner.open_case(request)  # type: ignore[attr-defined]


def test_a_feed_row_carrying_personal_data_reaches_no_sink_unmasked() -> None:
    """Redact before ANYTHING leaves: the model, the WORM record, human-review-console review,
    human-review-console cases, the API.

    The fixture's PII-carrying nostro row is the realistic input this is about. Its reference is
    the payer's national identifier, its counterparty name repeats it, and the warehouse supplied
    its own provenance citation whose source_id, title and snippet all quote that raw statement
    line. Every sink is checked TOGETHER, in one test, because the failure this exists to catch is
    a boundary that holds at all of them but one: the service redacted ``redacted_summary`` and
    then handed the SAME audit event its citations untouched, so an identifier the summary had
    just lost was persisted verbatim, in the same immutable row, in a record nobody can clean
    afterwards. The human-review-console payload had the same shape one level down, masking a
    citation's snippet
    and leaving its source_id and title, and the escalation case masked nothing at all.

    The attribution fields are deliberately not scanned (see :data:`_ATTRIBUTION`); everything
    else each record carries is.
    """
    container = build_container(local_settings())
    generation = _SpyGeneration(container.generation)
    cases = _SpyCaseEngine(container.case_engine)
    service = ResolutionService(
        feeds=container.feeds,
        generation=generation,  # type: ignore[arg-type]
        review_router=container.review_router,
        audit=container.audit,
        case_engine=cases,  # type: ignore[arg-type]
        tracer=container.tracer,
    )
    run = service.run(
        feed_a=sample_cases.NOSTRO_FEED,
        feed_b=sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF,
        actor=sample_cases.ACTOR,
        tenant=sample_cases.TENANT,
    )
    planted = (sample_cases.PLANTED_NRIC, sample_cases.PLANTED_EMAIL)

    def clean(label: str, sink: object) -> None:
        text = json.dumps(_content(to_jsonable(sink)), default=str, sort_keys=True)
        for literal in planted:
            assert literal not in text, f"a raw identifier reached {label}"
        assert not pack_leak(text, PII_PATTERNS), f"an unplanted pattern reached {label}"

    assert generation.prompts, "guard the guard: nothing is proved if draft was never called"
    clean("the model", generation.prompts)

    rows = [dict(row) for row in container.audit.log.read_all()]
    assert rows, "guard the guard: nothing is proved if the audit write never happened"
    clean("the WORM record", rows)

    pending = container.review_router.outbox.pending()
    assert pending, (
        "guard the guard: nothing is proved if nothing was routed to human-review-console"
    )
    clean("the human-review-console review payload", pending)

    assert cases.requests, "guard the guard: nothing is proved if no escalation case was opened"
    clean("the human-review-console case request", cases.requests)

    # The serialised API body, not the in-memory ``ReconRun``. The engine necessarily HOLDS the
    # raw feed text while it reconciles (``Break.reference_key`` and ``Break.counterparty_key``
    # are matching keys, and masking two different identifiers to one string would make them key
    # the same and reconcile as one counterparty). What must be clean is what crosses out, so the
    # response a client actually receives is the thing scanned.
    body = ReconcileResponse.from_domain(run, feed_id="nostro:scheme", worklist_id="wl:test")
    clean("the API response body", body.model_dump())

    # Masking is not dropping: the evidence is still cited and the break is still identifiable.
    cited = [c for r in run.resolutions for c in r.citations]
    assert cited, "a redacted resolution still carries its provenance"
    assert any("nostro:99" in c.source_id for c in cited), "the locator survived masking intact"


def test_the_repo_ships_no_posting_port_so_nothing_can_auto_post() -> None:
    """Never-auto-posts is enforced by the ABSENCE of any adapter that could post to a ledger.

    The exact-set assertion is the inventory; the SECOND assertion is the safety property, and it
    is the one that must never be relaxed. Adding an unrelated port (the tracer and the evaluation
    gate arrived with the shared observability commons) is expected to update the inventory. A
    port whose name reaches a ledger is not, whatever the inventory says.
    """
    assert set(PORT_PROTOCOLS) == {
        "audit",
        "identity",
        "review_router",
        "feeds",
        "generation",
        "case_engine",
        "worklist_store",
        "tracer",
        "evaluation",
    }
    assert not any("post" in name or "ledger" in name for name in PORT_PROTOCOLS)


# -- the F5 export contract --------------------------------------------------------------------


def test_the_worklist_export_conforms_and_counts_from_the_engine() -> None:
    container = build_container(local_settings())
    run = sample_cases.build_service(container).run(
        feed_a=sample_cases.NOSTRO_FEED,
        feed_b=sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF,
        actor=sample_cases.ACTOR,
    )
    export = build_worklist_export(
        run, feed_id="nostro:scheme", as_of=sample_cases.AS_OF, aging=_POLICY.aging
    )
    assert export["schema_version"] == "ops-worklist-export/v1"
    assert export["queue_depth"] == len(run.ranked_breaks)
    assert export["throughput"] == len(run.matches)
    buckets = export["aging_buckets"]
    assert isinstance(buckets, dict)
    assert sum(buckets.values()) == len(run.ranked_breaks)
