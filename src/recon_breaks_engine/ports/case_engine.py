"""CaseEnginePort: open an escalation case with an aging clock, on the Hrz7 case spine.

Aged or high-value breaks open a case whose workflow and regulatory/aging clock come from Hrz7's
case engine as deployment CONFIGURATION (a ``WorkflowDefinition`` carrying a
``ClockSpec``), driven over Hrz7's ``/v1/cases`` surface. The BREACH decision (is this break old
enough or large enough to escalate?) is the deterministic engine's, made before this port is
called; the port only opens the case and reports the deadline the clock implies. An adapter never
decides breach, and it never closes a case on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable

from ..domain.kernel import Citation


@dataclass(frozen=True, slots=True)
class CaseRequest:
    """The break-derived facts a case is opened from. Every field is engine-decided."""

    break_id: str
    break_type: str
    workflow: str
    clock_days: int
    as_of: date
    amount_minor: int
    currency: str
    counterparty_key: str
    opened_by: str
    tenant: str = ""
    citations: tuple[Citation, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CaseHandle:
    """What opening a case returned: its id, the workflow it runs, and the clock deadline."""

    case_id: str
    workflow: str
    deadline: date
    status: str


@runtime_checkable
class CaseEnginePort(Protocol):
    def open_case(self, request: CaseRequest) -> CaseHandle:
        """Open (or record) one escalation case and return its handle with an aging deadline.

        The deadline is computed from the request's ``as_of`` plus ``clock_days``, which is the
        clock the caller took from the break's workflow policy: the port does not invent a clock.
        """
        ...
