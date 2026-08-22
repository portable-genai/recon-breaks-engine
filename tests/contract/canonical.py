"""ONE canonical request per port, shared by the structural and behavioural contract suites.

Parity means the same request through every implementation, so the request needs a single home.
Retyping it per suite is how two "parity" tests end up asserting different things.

Each :class:`PortCase` answers three questions about one port:

* ``invoke``   : what a single canonical call to this port looks like;
* ``answered`` : what it means for the OFFLINE family to have actually answered (a port that
  returns ``None`` and records nothing has not answered, it has merely not raised);
* ``managed_refusal`` : what the MANAGED family must do when called with no cloud reachable.
  Never a silent success: either it refuses because it is unconfigured, or its lazy SDK import
  fails. Both are honest; returning as if the work happened is not.

Adding a port means adding a case here. ``test_port_parity.py`` fails the build if this table
and the port map ever disagree, so the touch list in ``CONTRIBUTING.md`` is enforced rather than
merely written down.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from agent_eval_kit import EvalReport
from hex_service_kit.identity import IdentityError, Principal, RequestContext
from hex_service_kit.observability import TokenUsage

from recon_breaks_engine.adapters.local._recon_fixture import FEED_A
from recon_breaks_engine.domain.kernel import (
    AuditEvent,
    Citation,
    Decision,
    Severity,
)
from recon_breaks_engine.domain.models import (
    BreakResolution,
    BreakType,
    FeedRow,
    StoredWorklist,
)
from recon_breaks_engine.ports.case_engine import CaseHandle, CaseRequest

from tests.fixtures import sample_cases

#: The audit record every audit-port implementation is handed. Already redacted, as the port
#: requires: a raw identifier must never reach a WORM record.
CANONICAL_EVENT = AuditEvent(
    action="recon_resolution",
    actor=sample_cases.ACTOR,
    decision=Decision.ESCALATED,
    severity=Severity.HIGH,
    redacted_summary="break BRK-missing-A6 (ZETA INC FICTIONAL): missing counterpart",
    citations=(Citation(source_id="nostro:7", title="Feed nostro line 7", snippet="A6 90.00 USD"),),
)

#: The escalated resolution every review-router implementation is handed (rule R8's payload).
CANONICAL_RESULT = BreakResolution(
    subject="break BRK-missing-A6 (ZETA INC FICTIONAL)",
    severity=Severity.HIGH,
    decision=Decision.ESCALATED,
    summary="One feed carries this item with no counterpart on the other feed.",
    requires_human_review=True,
    break_id="BRK-missing-A6",
    break_type=BreakType.MISSING,
    hypothesis="One feed carries this item with no counterpart on the other feed.",
    journal_note="Investigate missing break of 90.00 USD; do NOT post until a checker confirms.",
    citations=(Citation(source_id="nostro:7", title="Feed nostro line 7", snippet="A6 90.00 USD"),),
)

#: The canonical case-open request every case-engine implementation is handed.
CANONICAL_CASE_REQUEST = CaseRequest(
    break_id="BRK-missing-A6",
    break_type="missing",
    workflow="recon-break-missing",
    clock_days=3,
    as_of=date(2026, 8, 8),
    amount_minor=9000,
    currency="USD",
    counterparty_key="ZETA INC",
    opened_by=sample_cases.ACTOR,
    tenant=sample_cases.TENANT,
)

#: The engine-facts prompt every generation implementation is handed. Digit-free break type only.
CANONICAL_PROMPT = "break_type: missing\namount: 90.00\ncurrency: USD\nage_days: 7\nrank: 1"

#: The worklist every worklist-store implementation is handed. Tenant-scoped, so a get after a put
#: proves both the round trip and that the stored tenant survives (the field the domain authorizes).
CANONICAL_WORKLIST = StoredWorklist(
    worklist_id="wl:demo-bank:nostro:scheme",
    tenant=sample_cases.TENANT,
    feed_id="nostro:scheme",
    as_of=date(2026, 8, 8),
    ranked_breaks=(),
)

#: The inbound transport context every identity implementation is handed.
CANONICAL_CONTEXT = RequestContext(headers={"x-dev-persona": "auditor"})


@dataclass(frozen=True, slots=True)
class PortCase:
    """One port's canonical call plus the two verdicts the parity suites need."""

    invoke: Callable[[Any], Any]
    answered: Callable[[Any, Any], bool]
    managed_refusal: tuple[type[BaseException], ...]
    detail: str


def _audit_invoke(adapter: Any) -> Any:
    return adapter.record(CANONICAL_EVENT)


def _audit_answered(adapter: Any, _result: Any) -> bool:
    stored = adapter.log.read_all()
    return bool(stored) and stored[-1]["actor"] == sample_cases.ACTOR and adapter.verify().ok


def _identity_invoke(adapter: Any) -> Any:
    return adapter.resolve(CANONICAL_CONTEXT)


def _identity_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, Principal) and bool(result.actor)


def _review_invoke(adapter: Any) -> Any:
    return adapter.route(CANONICAL_RESULT, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)


def _review_answered(adapter: Any, result: Any) -> bool:
    return bool(result) and len(adapter.outbox.pending()) == 1


def _feeds_invoke(adapter: Any) -> Any:
    return adapter.fetch(FEED_A)


def _feeds_answered(_adapter: Any, result: Any) -> bool:
    return bool(result) and all(isinstance(row, FeedRow) for row in result)


def _generation_invoke(adapter: Any) -> Any:
    return adapter.draft(CANONICAL_PROMPT)


def _generation_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, str) and bool(result.strip())


def _case_invoke(adapter: Any) -> Any:
    return adapter.open_case(CANONICAL_CASE_REQUEST)


def _case_answered(adapter: Any, result: Any) -> bool:
    return (
        isinstance(result, CaseHandle)
        and result.status == "open"
        and result.case_id.endswith("A6")
        and len(adapter.opened) == 1
    )


def _worklist_invoke(adapter: Any) -> Any:
    return adapter.put(CANONICAL_WORKLIST)


def _worklist_answered(adapter: Any, result: Any) -> bool:
    stored = adapter.get(result)
    return stored is not None and stored.tenant == sample_cases.TENANT


def _tracer_invoke(adapter: Any) -> Any:
    with adapter.span("canonical.unit", action="canonical"):
        adapter.record_token_usage(TokenUsage(input_tokens=7, output_tokens=2), "canonical-model")
    return True


def _tracer_answered(adapter: Any, result: Any) -> bool:
    return bool(result)


def _evaluation_invoke(adapter: Any) -> Any:
    return adapter.evaluate("eval/datasets/canonical.jsonl")


def _evaluation_answered(adapter: Any, result: Any) -> bool:
    return isinstance(result, EvalReport) and result.dataset.endswith("canonical.jsonl")


CANONICAL_CALLS: dict[str, PortCase] = {
    "audit": PortCase(
        invoke=_audit_invoke,
        answered=_audit_answered,
        # The lazy `google.cloud` import is the first thing the managed sink does.
        managed_refusal=(ImportError,),
        detail="write one already-redacted WORM record",
    ),
    "identity": PortCase(
        invoke=_identity_invoke,
        answered=_identity_answered,
        # No IAP assertion header offline, so the managed adapter refuses before importing.
        managed_refusal=(IdentityError,),
        detail="resolve a verified principal from transport context",
    ),
    "review_router": PortCase(
        invoke=_review_invoke,
        answered=_review_answered,
        # Rule R8: with no console configured the managed router must refuse, not swallow.
        managed_refusal=(RuntimeError,),
        detail="route one escalated result to human review",
    ),
    "feeds": PortCase(
        invoke=_feeds_invoke,
        answered=_feeds_answered,
        # The lazy `google.cloud.bigquery` import is the first thing the managed feed does.
        managed_refusal=(ImportError,),
        detail="return the raw cited rows of a feed set",
    ),
    "generation": PortCase(
        invoke=_generation_invoke,
        answered=_generation_answered,
        # The lazy managed-model import is the first thing the managed adapter does.
        managed_refusal=(ImportError,),
        detail="narrate one grounded sentence from engine facts",
    ),
    "case_engine": PortCase(
        invoke=_case_invoke,
        answered=_case_answered,
        # With no Hrz7 console configured the managed case engine must refuse, not swallow.
        managed_refusal=(RuntimeError,),
        detail="open one escalation case with an aging clock",
    ),
    "worklist_store": PortCase(
        invoke=_worklist_invoke,
        answered=_worklist_answered,
        # The lazy `google.cloud.bigquery` import is the first thing the managed store does.
        managed_refusal=(ImportError,),
        detail="persist and retrieve a tenant-scoped worklist",
    ),
    "tracer": PortCase(
        invoke=_tracer_invoke,
        answered=_tracer_answered,
        # NOTHING. Tracing is not essential to correctness, so the managed adapter must not refuse
        # offline either: with no SDK it degrades to a no-op and the traced body still runs. An
        # adapter that raised here would take a request down over a diagnostic.
        managed_refusal=(),
        detail="open one span and report the cost of a model call",
    ),
    "evaluation": PortCase(
        invoke=_evaluation_invoke,
        answered=_evaluation_answered,
        # The managed gate reaches Hrz4 over HTTP, which is unreachable offline.
        managed_refusal=(Exception,),
        detail="score one golden dataset through the promotion authority",
    ),
}
