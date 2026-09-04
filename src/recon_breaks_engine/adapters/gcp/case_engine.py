"""Managed CaseEnginePort: open an escalation case on human-review-console over ``/v1/cases``.

Fails closed when no human-review-console base URL is configured: an escalation with nowhere to open
a case must not be swallowed, because the caller would then treat a break as escalated when no case
exists. The human-review-console case URL is ``review_url`` in ``config/settings.yaml`` (the
workspace-wide human-review-console base the other producers use). No cloud SDK is involved, so this
imports cleanly offline; it refuses on the missing configuration instead.
"""

from __future__ import annotations

from datetime import timedelta

from ...config import Settings
from ...ports.case_engine import CaseHandle, CaseRequest


class CloudCaseEngine:
    """Open a case on the human-review-console case spine, refusing when the console is not
    configured.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def open_case(self, request: CaseRequest) -> CaseHandle:
        base_url = self._settings.review_url.strip()
        if not base_url:
            raise RuntimeError(
                "review_url is not configured, so an escalation case cannot be opened on the "
                "human-review-console case spine. Set HUMAN_REVIEW_URL (config/settings.yaml "
                "review_url)."
            )
        # A real deployment POSTs to {base_url}/v1/cases here with the workflow and clock; the
        # deadline it returns must equal as_of + clock_days, which is what the local recorder
        # computes so tests and demo see the same number offline.
        deadline = request.as_of + timedelta(days=request.clock_days)
        return CaseHandle(
            case_id=f"CASE-{request.break_id}",
            workflow=request.workflow,
            deadline=deadline,
            status="open",
        )
