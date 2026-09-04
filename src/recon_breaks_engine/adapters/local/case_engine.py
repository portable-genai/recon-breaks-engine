"""Local CaseEnginePort: a recording adapter that computes deadlines from the same clock data.

Stands in for human-review-console's ``/v1/cases`` surface offline. It computes the case deadline
from the request's ``as_of`` plus ``clock_days`` (the clock the deterministic engine took from the
break's workflow policy) exactly as the managed case engine would from its ``ClockSpec``, and
records the opened case in memory so the demo, the tests and the eval can assert that a breaching
break opened exactly one case with the right deadline. It NEVER decides breach and never closes a
case: those are the engine's and a human's jobs respectively.
"""

from __future__ import annotations

from datetime import timedelta

from ...config import Settings
from ...ports.case_engine import CaseHandle, CaseRequest


class LocalCaseRecorder:
    """Record opened cases and return a handle with a clock-derived deadline (no live
    human-review-console).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._opened: list[CaseHandle] = []

    def open_case(self, request: CaseRequest) -> CaseHandle:
        handle = CaseHandle(
            case_id=f"CASE-{request.break_id}",
            workflow=request.workflow,
            deadline=request.as_of + timedelta(days=request.clock_days),
            status="open",
        )
        self._opened.append(handle)
        return handle

    @property
    def opened(self) -> tuple[CaseHandle, ...]:
        """The cases opened so far, for inspection in tests, the eval and the demo."""
        return tuple(self._opened)
