"""On-prem CaseEnginePort: fail-fast portability placeholder (the sovereign-exit proof, P-12)."""

from __future__ import annotations

from ...config import Settings
from ...ports.case_engine import CaseHandle, CaseRequest


class OnPremCaseEngine:
    """Satisfies CaseEnginePort but refuses at call time: the client wires its own case spine."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def open_case(self, request: CaseRequest) -> CaseHandle:
        raise NotImplementedError(
            "on-prem case engine is a portability placeholder: bind the client's own case "
            "system (see docs/onprem-migration.md)"
        )
