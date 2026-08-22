"""API request/response schemas (Pydantic) mapped to/from the pure-domain models."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from ..domain.metrics_export import build_worklist_export
from ..domain.models import RankedBreak, ReconRun, StoredWorklist
from ..domain.policy import ReconPolicy


class ReconcileRequest(BaseModel):
    """Reconcile two named feed sets, optionally as at an explicit date (else today)."""

    feed_a: str
    feed_b: str
    #: The instant to reconcile against, ISO 8601. Aging is measured from it, so supplying it
    #: makes a run replayable; omitting it uses the server's current date.
    as_of: str = ""


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class MatchModel(BaseModel):
    pass_name: str
    currency: str
    a_entry_ids: list[str]
    b_entry_ids: list[str]
    residual_minor: int


class RankedBreakModel(BaseModel):
    rank: int
    score: int
    break_id: str
    break_type: str
    currency: str
    amount_minor: int
    age_days: int
    entry_ids: list[str]
    factors: list[tuple[str, int]]
    citations: list[CitationModel]


class ResolutionModel(BaseModel):
    break_id: str
    break_type: str
    subject: str
    severity: str
    decision: str
    summary: str
    hypothesis: str
    journal_note: str
    requires_human_review: bool
    citations: list[CitationModel]


def _ranked_break_model(rb: RankedBreak) -> RankedBreakModel:
    return RankedBreakModel(
        rank=rb.rank,
        score=rb.score,
        break_id=rb.record.break_id,
        break_type=rb.record.break_type.value,
        currency=rb.record.currency,
        amount_minor=rb.record.amount_minor,
        age_days=rb.record.age_days,
        entry_ids=list(rb.record.entry_ids),
        factors=[(name, value) for name, value in rb.factors],
        citations=[_citation(c) for c in rb.record.citations],
    )


class ReconcileResponse(BaseModel):
    as_of: str
    match_count: int
    matches: list[MatchModel]
    breaks: list[RankedBreakModel]
    resolutions: list[ResolutionModel]
    requires_human_review: bool
    #: The ops-worklist export (the F5 data contract) computed from this run.
    export: dict[str, object]
    #: The durable, tenant-scoped handle the ranked worklist was persisted under, so a client can
    #: retrieve it later through ``GET /v1/worklist/{worklist_id}`` (authorized to its own tenant).
    worklist_id: str = ""

    @classmethod
    def from_domain(
        cls, run: ReconRun, *, feed_id: str, worklist_id: str = ""
    ) -> ReconcileResponse:
        return cls(
            as_of=run.as_of.isoformat(),
            worklist_id=worklist_id,
            match_count=len(run.matches),
            matches=[
                MatchModel(
                    pass_name=m.pass_name,
                    currency=m.currency,
                    a_entry_ids=list(m.a_entry_ids),
                    b_entry_ids=list(m.b_entry_ids),
                    residual_minor=m.residual_minor,
                )
                for m in run.matches
            ],
            breaks=[_ranked_break_model(rb) for rb in run.ranked_breaks],
            resolutions=[
                ResolutionModel(
                    break_id=r.break_id,
                    break_type=r.break_type.value,
                    subject=r.subject,
                    severity=r.severity.value,
                    decision=r.decision.value,
                    summary=r.summary,
                    hypothesis=r.hypothesis,
                    journal_note=r.journal_note,
                    requires_human_review=r.requires_human_review,
                    citations=[_citation(c) for c in r.citations],
                )
                for r in run.resolutions
            ],
            requires_human_review=run.requires_human_review,
            export=build_worklist_export(
                run, feed_id=feed_id, as_of=run.as_of, aging=ReconPolicy.default().aging
            ),
        )


def _citation(citation: object) -> CitationModel:
    return CitationModel(
        source_id=getattr(citation, "source_id", ""),
        title=getattr(citation, "title", ""),
        snippet=getattr(citation, "snippet", ""),
    )


class WorklistResponse(BaseModel):
    """One persisted, tenant-scoped ranked worklist, returned only to its own tenant."""

    worklist_id: str
    feed_id: str
    as_of: str
    breaks: list[RankedBreakModel]

    @classmethod
    def from_domain(cls, worklist: StoredWorklist) -> WorklistResponse:
        return cls(
            worklist_id=worklist.worklist_id,
            feed_id=worklist.feed_id,
            as_of=worklist.as_of.isoformat(),
            breaks=[_ranked_break_model(rb) for rb in worklist.ranked_breaks],
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str


def today_iso() -> str:
    """The server's current date, ISO 8601, for a reconcile request that named none."""
    return date.today().isoformat()
