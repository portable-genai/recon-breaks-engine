"""Prove every eval metric can go RED (the not-falsely-green harness, per metric).

A metric that cannot fail proves nothing: a redactor scored against its own output, a match
metric that reads the pipeline's own answer, a golden set that planted no target. Each metric
below is fed a clean case that must PASS and a degraded case that must FAIL, so a metric that
silently became a constant is caught here rather than in production.

The proof must drive the SHIPPED scorer, not a lookalike written for the test. Checking
``pii_safety`` against a private one-line helper over a hand-written string proves the helper
works and says nothing whatever about the metric the gate runs: a shipped metric that reads one
field of a multi-field record stays green while the identifier sits in the citations beside it.
So ``pii_safety`` is driven through ``run_eval``'s own functions over the audit rows the real
pipeline persisted.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

import run_eval as ev
from agent_eval_kit import assert_can_go_red
from run_eval import (
    score_break_typing,
    score_groundedness,
    score_match_accuracy,
)

from recon_breaks_engine.config import Settings, build_container
from recon_breaks_engine.domain.kernel import Citation, Decision, Severity
from recon_breaks_engine.domain.models import (
    Break,
    BreakResolution,
    BreakType,
    FeedSide,
    Match,
    RankedBreak,
    ReconRun,
)

from tests.fixtures import sample_cases

_GOLDEN_MATCHES = {("exact", frozenset({"A1", "B1"}))}
_GOLDEN_BREAKS = {frozenset({"A6"}): "missing"}


def _match(pass_name: str, a: str, b: str) -> Match:
    return Match(
        pass_name=pass_name,
        currency="USD",
        a_entry_ids=(a,),
        b_entry_ids=(b,),
        a_total_minor=1,
        b_total_minor=1,
        residual_minor=0,
    )


def _ranked_break(entry_id: str, break_type: BreakType) -> RankedBreak:
    record = Break(
        break_id=f"BRK-{break_type.value}-{entry_id}",
        break_type=break_type,
        side=FeedSide.A,
        entry_ids=(entry_id,),
        amount_minor=9000,
        currency="USD",
        value_date=date(2026, 8, 1),
        reference_key="R",
        counterparty_key="K",
        account="acc",
        age_days=7,
        repeat_count=1,
    )
    return RankedBreak(record=record, score=1, rank=1)


def test_match_accuracy_can_go_red() -> None:
    assert_can_go_red(
        lambda matches: score_match_accuracy(matches, _GOLDEN_MATCHES),
        green=[_match("exact", "A1", "B1")],  # reproduces the golden match
        red=[_match("tolerance", "A1", "B1")],  # right group, WRONG pass: a mis-classification
        threshold=0.90,
        metric="match_accuracy",
    )


def test_break_typing_accuracy_can_go_red() -> None:
    assert_can_go_red(
        lambda breaks: score_break_typing(breaks, _GOLDEN_BREAKS),
        green=[_ranked_break("A6", BreakType.MISSING)],  # correct type
        red=[_ranked_break("A6", BreakType.DUPLICATE)],  # wrong type on the right group
        threshold=0.90,
        metric="break_typing_accuracy",
    )


def _run_with_hypothesis(hypothesis: str) -> ReconRun:
    resolution = BreakResolution(
        subject="break BRK-missing-A6 (ZETA INC FICTIONAL)",
        severity=Severity.HIGH,
        decision=Decision.ESCALATED,
        summary=hypothesis,
        requires_human_review=True,
        break_id="BRK-missing-A6",
        break_type=BreakType.MISSING,
        hypothesis=hypothesis,
        journal_note="Investigate missing break of 90.00 USD; do NOT post.",
        citations=(Citation(source_id="nostro:7", title="t", snippet="s"),),
    )
    return ReconRun(
        as_of=date(2026, 8, 8),
        matches=(),
        ranked_breaks=(_ranked_break("A6", BreakType.MISSING),),
        resolutions=(resolution,),
        requires_human_review=True,
    )


def test_groundedness_can_go_red() -> None:
    assert_can_go_red(
        score_groundedness,
        green=_run_with_hypothesis("The two feeds disagree on this item and need review."),
        red=_run_with_hypothesis("Root cause is a 4242424 posting error, clearly."),
        threshold=0.99,
        metric="groundedness",
    )


# -- pii_safety: the SHIPPED scorer, over REAL persisted rows ----------------------------------


def _persisted_rows() -> list[dict[str, Any]]:
    """Run the REAL pipeline over the offline fixture; return the WORM rows it wrote.

    Hand-built rows would be a second implementation of what the service persists, and this
    metric's whole failure mode was a disagreement between the record's shape and the scorer's
    idea of it. So the rows are the ones the service actually wrote.
    """
    settings = Settings(profile="local", audit_path=":memory:", tenant=sample_cases.TENANT)
    container = build_container(settings)
    sample_cases.build_service(container).run(
        feed_a=sample_cases.NOSTRO_FEED,
        feed_b=sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF,
        actor=sample_cases.ACTOR,
        tenant=sample_cases.TENANT,
    )
    return [dict(row) for row in container.audit.log.read_all()]


def _unredacted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The mutant: the boundary is off, so a citation keeps the raw identifier.

    This is the defect in its exact shape rather than an approximation. The summary stays masked
    (the one field the old scorer read) and the identifier lives in the citation stored in the
    same WORM record.
    """
    mutated = copy.deepcopy(rows)
    for row in mutated:
        citations = row.get("citations") or []
        if citations:
            citations[0]["snippet"] = f"... inward remit NRIC {sample_cases.PLANTED_NRIC} ..."
    return mutated


def _score(rows: list[dict[str, Any]]) -> float:
    return ev.pii_safety(ev.audit_surfaces(rows), [sample_cases.PLANTED_NRIC])


def test_pii_safety_can_go_red() -> None:
    rows = _persisted_rows()
    assert rows, "the pipeline must have written an audit record to score"
    assert_can_go_red(
        _score,
        green=rows,  # the boundary held: nothing content-bearing carries the identifier
        red=_unredacted(rows),  # the boundary off: the citation keeps what the summary lost
        threshold=ev.THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )


def test_the_metric_ignores_the_actor_attribution_field() -> None:
    """The verified principal is an address BY DESIGN, so it may not be scored as a leak.

    A blanket scan over a whole audit row can never go green, and a metric that can never go
    green is a metric somebody switches off. This pins the shipped scorer to the content fields.
    """
    rows = _persisted_rows()
    assert any("@" in str(row["actor"]) for row in rows), "the fixture actor must be an address"
    assert _score(rows) == 1.0
