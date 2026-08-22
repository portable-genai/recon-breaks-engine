"""A reconciliation run opens ONE span, and that span carries no content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit store.
So the value of tracing the run path depends entirely on the span carrying structural
attributes only: which action, whose, which tenant, which feed pair. An entry id, a
counterparty name, a break's figures or any drafted hypothesis or journal note reaching a
span has left the boundary the service's ``redact`` call exists to hold, and left it silently.

The content case runs the REAL local fixture feed pair, so the needles below (counterparties,
references, every resolution's drafted text) are values that would actually leak if any
attribute were content-shaped.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from recon_breaks_engine.config import build_container
from recon_breaks_engine.domain.models import ReconRun
from recon_breaks_engine.domain.resolution_service import ResolutionService

from tests.conftest import local_settings
from tests.fixtures import sample_cases

#: Every attribute key the run span is allowed to carry. A break that started explaining itself
#: on the span (a figure, a counterparty, a drafted note) would widen this set, which is the
#: point of asserting on the set rather than on the individual keys.
_RUN_KEYS = {"action", "actor", "tenant", "feed_a", "feed_b"}


class _RecordingTracer:
    """Captures every span name and attribute so the test can inspect what was emitted."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _run() -> tuple[_RecordingTracer, ReconRun]:
    """The REAL local adapters, exactly as ``sample_cases.build_service`` wires them."""
    container = build_container(local_settings())
    tracer = _RecordingTracer()
    service = ResolutionService(
        feeds=container.feeds,
        generation=container.generation,
        review_router=container.review_router,
        audit=container.audit,
        case_engine=container.case_engine,
        tracer=tracer,  # type: ignore[arg-type]
    )
    run = service.run(
        feed_a=sample_cases.NOSTRO_FEED,
        feed_b=sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF,
        actor=sample_cases.ACTOR,
        tenant=sample_cases.TENANT,
    )
    return tracer, run


def _emitted(tracer: _RecordingTracer) -> str:
    """Every attribute VALUE that was emitted, and every KEY, as one searchable blob."""
    parts: list[str] = []
    for name, attributes in tracer.spans:
        parts.append(name)
        parts.extend(attributes)
        parts.extend(attributes.values())
    return " ".join(parts)


def test_a_reconciliation_run_opens_exactly_one_named_span() -> None:
    tracer, _ = _run()
    assert [name for name, _ in tracer.spans] == ["recon.run"]


def test_the_span_carries_the_structural_attributes_an_operator_needs() -> None:
    """Enough to answer "whose run is slow, on which tenant and feed pair", and nothing more."""
    tracer, _ = _run()
    _, attributes = tracer.spans[0]
    assert attributes["action"] == "run"
    assert attributes["actor"] == sample_cases.ACTOR
    assert attributes["tenant"] == sample_cases.TENANT
    assert attributes["feed_a"] == sample_cases.NOSTRO_FEED
    assert attributes["feed_b"] == sample_cases.SCHEME_FEED


def test_the_attribute_set_is_a_fixed_allowlist_whatever_the_breaks() -> None:
    """A breaching break must not start attaching its figures, or its draft, to the span."""
    tracer, run = _run()
    assert run.ranked_breaks, "the fixture feed stopped producing breaks worth a worklist"
    for _, attributes in tracer.spans:
        assert set(attributes) == _RUN_KEYS


def test_no_span_attribute_carries_feed_content_or_any_drafted_text() -> None:
    """Every content-shaped value in reach of the run: fixture rows and drafted resolutions."""
    tracer, run = _run()
    emitted = _emitted(tracer)

    forbidden: list[str] = [
        sample_cases.PLANTED_NRIC,
        "Acme Ltd",
        "Zeta Inc",
        "NOSTRO-USD-001",
        "REF-006",
    ]
    for resolution in run.resolutions:
        forbidden.extend(
            (
                resolution.break_id,
                resolution.subject,
                resolution.summary,
                resolution.hypothesis,
                resolution.journal_note,
            )
        )
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal not in emitted, f"a span attribute carried {literal!r}"
        assert literal.lower() not in emitted.lower(), f"a span attribute carried {literal!r}"


def test_every_emitted_attribute_value_is_a_string_the_port_declares() -> None:
    """``span(name, **attributes: str)``: a non-string would serialise however the SDK felt."""
    tracer, _ = _run()
    values: list[Any] = [v for _, attributes in tracer.spans for v in attributes.values()]
    assert values
    assert all(isinstance(value, str) for value in values)
