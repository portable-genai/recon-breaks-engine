"""Tool functions an agent runtime calls: thin, side-effect-honest wrappers on the services.

Design rules, in the order they matter:

* **No business logic here.** The domain service decides HOW; the model only decides WHICH tool
  to call. A rule that lives in a tool wrapper is a rule the CLI and the API do not have.
* **Rule R8 applies on this path too.** Reconciliation routes every drafted resolution to Hrz7
  and opens a case for a breaching break from INSIDE the service, in the same call. An agent
  surface that only returned the worklist would be a third place an escalation can quietly stop.
* **Import-safe without a runtime.** ``google.adk`` is imported lazily inside
  :func:`build_function_tools`, so these callables are importable, testable and runnable with no
  ADK and no cloud SDK installed.
* **Typed and documented.** A runtime derives each tool's name, description and JSON parameter
  schema from the signature and the docstring, so both are part of the contract.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pii_kit import redact

from ..config import Container, Settings, build_container
from ..domain.pii import PII_PATTERNS
from ..domain.resolution_service import ResolutionService

#: The identity a tool call is attributed to when the runtime propagates none. It names the
#: SERVICE, not a person, so an unattributed action is never mistaken for a human's.
DEFAULT_ACTOR = "recon-breaks-engine-agent"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _redacted(node: Any) -> Any:
    """Mask personal data in every string of a tool result, however deeply it is nested."""
    if isinstance(node, str):
        return redact(node, PII_PATTERNS)
    if isinstance(node, dict):
        return {key: _redacted(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_redacted(value) for value in node]
    return node


def reconcile_feeds(
    feed_a: str,
    feed_b: str,
    as_of: str = "",
    actor: str = DEFAULT_ACTOR,
    tenant: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Reconcile two feed sets and return the ranked break worklist.

    The deterministic engine reconciles and types every break; the model narrates only. Every
    drafted resolution is routed to human review and a breaching break opens an escalation case
    (rule R8), from inside the service. Nothing here can post to a ledger: this service ships no
    posting port at all.

    Args:
      feed_a: The first (internal) feed set to reconcile.
      feed_b: The second (external) feed set to reconcile.
      as_of: ISO date to reconcile against; empty means today.
      actor: The verified identity this call is attributed to.
      tenant: Tenant partition asserted on outbound reviews and cases.

    Returns:
      A JSON-safe dict with every string masked for personal data (P-04: a tool result goes into
      a model's context): the match count, the ranked breaks (type, score, entry ids), and the
      run-level ``requires_human_review`` flag.
    """
    container = _container(settings)
    service = ResolutionService(
        feeds=container.feeds,
        generation=container.generation,
        review_router=container.review_router,
        audit=container.audit,
        case_engine=container.case_engine,
        tracer=container.tracer,
    )
    run = service.run(
        feed_a=feed_a,
        feed_b=feed_b,
        as_of=date.fromisoformat(as_of) if as_of else date.today(),
        actor=actor,
        tenant=tenant,
    )
    payload: dict[str, Any] = {
        "as_of": run.as_of.isoformat(),
        "match_count": len(run.matches),
        "requires_human_review": run.requires_human_review,
        "breaks": [
            {
                "rank": rb.rank,
                "score": rb.score,
                "break_id": rb.record.break_id,
                "break_type": rb.record.break_type.value,
                "amount_minor": rb.record.amount_minor,
                "currency": rb.record.currency,
                "age_days": rb.record.age_days,
                "entry_ids": list(rb.record.entry_ids),
            }
            for rb in run.ranked_breaks
        ],
    }
    return _redacted(payload)  # type: ignore[no-any-return]


def verify_audit_trail(settings: Settings | None = None) -> dict[str, Any]:
    """Verify the audit trail's hash chain and its external head anchor.

    Returns:
      A dict with ``ok``, the record counts and a ``detail`` string. ``ok`` is false for an
      edited, deleted or reordered record, and, when an external anchor is configured, for a
      truncated tail as well. Without an anchor a truncation cannot be detected, and the detail
      says so rather than implying a stronger guarantee than the store provides.
    """
    resolved = settings or Settings.load()
    audit = _container(resolved).audit
    verify = getattr(audit, "verify", None)
    if verify is None:
        raise NotImplementedError(
            f"the {resolved.profile} audit adapter does not expose chain verification; a "
            "managed WORM sink is verified by its own retention policy, not from here"
        )
    report = verify()
    return {
        "ok": report.ok,
        "entries": report.entries,
        "chained": report.chained,
        "legacy": report.legacy,
        "first_bad_seq": report.first_bad_seq,
        "detail": report.detail,
        "anchored": bool(resolved.audit_anchor_path),
    }


#: The tool table. The agent card advertises exactly these, by function name.
TOOL_FUNCTIONS = (reconcile_feeds, verify_audit_trail)


def build_function_tools() -> list[Any]:
    """Wrap each callable as a runtime FunctionTool (the only ADK-dependent code path).

    The import is deliberately here rather than at module scope: without it this module, the
    card and every tool would need an agent runtime installed to be imported at all, and the
    offline gate installs none.
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=function) for function in TOOL_FUNCTIONS]
