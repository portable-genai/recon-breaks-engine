#!/usr/bin/env python3
"""Evaluation gate for Reconciliation Breaks Engine (F1).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change. It drives the real
  deterministic engine over the fixture feeds and scores four metrics AGAINST AN INDEPENDENT GOLDEN
  ORACLE (``datasets/golden_cases.jsonl``, hand-declared expected matches and break types), never
  against the pipeline's own output. ``tests/unit/test_not_falsely_green.py`` proves each metric can
  go red. * **gate** - the promotion verdict from the shared model-quality-gate authority (requires
  the ``gcp`` profile), via ``agent_eval_kit.PromotionGateClient``.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from agent_eval_kit import EvalMetricResult, EvalReport, PromotionGateClient, eval_main
from pii_kit import pack_leak

from recon_breaks_engine.adapters.local._recon_fixture import (
    ANCHOR_AS_OF,
    FEED_A,
    FEED_B,
    PLANTED_EMAIL,
    PLANTED_NRIC,
)
from recon_breaks_engine.config import Container, Settings, build_container
from recon_breaks_engine.domain.models import Match, RankedBreak, ReconRun
from recon_breaks_engine.domain.pii import PII_PATTERNS
from recon_breaks_engine.domain.resolution_service import ResolutionService

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"

THRESHOLDS: dict[str, float] = {
    "match_accuracy": 0.90,
    "break_typing_accuracy": 0.90,
    "groundedness": 0.99,
    "pii_safety": 0.99,
}
#: The registered model-quality-gate metric bundle for this vertical (model-quality-gate owns the
#: metrics + thresholds).
_BUNDLE = "recon-breaks-engine"

_DIGITS = re.compile(r"\d+")


def _load(path: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def golden_matches(cases: Iterable[dict[str, object]]) -> set[tuple[str, frozenset[str]]]:
    """The hand-declared expected matches: (pass name, the set of entry ids it should group)."""
    return {
        (str(c["pass"]), frozenset(str(e) for e in c["entries"]))  # type: ignore[arg-type]
        for c in cases
        if c.get("kind") == "match"
    }


def golden_breaks(cases: Iterable[dict[str, object]]) -> dict[frozenset[str], str]:
    """The hand-declared expected breaks: entry-id set -> the type the engine should assign."""
    return {
        frozenset(str(e) for e in c["entries"]): str(c["type"])  # type: ignore[arg-type]
        for c in cases
        if c.get("kind") == "break"
    }


# -- the metrics (each independently red-able; see test_not_falsely_green) ----------------------


def score_match_accuracy(
    matches: Sequence[Match], expected: set[tuple[str, frozenset[str]]]
) -> float:
    """Fraction of the golden-declared matches the engine reproduced, pass name and group both."""
    if not expected:
        return 0.0
    produced = {(m.pass_name, frozenset((*m.a_entry_ids, *m.b_entry_ids))) for m in matches}
    return round(len(produced & expected) / len(expected), 4)


def score_break_typing(breaks: Sequence[RankedBreak], expected: dict[frozenset[str], str]) -> float:
    """Fraction of golden-declared breaks the engine both found AND typed correctly."""
    if not expected:
        return 0.0
    produced = {frozenset(rb.record.entry_ids): rb.record.break_type.value for rb in breaks}
    correct = sum(1 for group, kind in expected.items() if produced.get(group) == kind)
    return round(correct / len(expected), 4)


def score_groundedness(run: ReconRun) -> float:
    """Fraction of resolution hypotheses that introduce NO figure absent from the engine facts."""
    resolutions = run.resolutions
    if not resolutions:
        return 0.0
    ranked = {rb.record.break_id: rb for rb in run.ranked_breaks}
    grounded = 0
    for r in resolutions:
        allowed: set[str] = set(_DIGITS.findall(r.journal_note))
        allowed.update(_DIGITS.findall(r.break_id))
        rb = ranked.get(r.break_id)
        if rb is not None:
            allowed.update({str(rb.record.age_days), str(rb.rank)})
        if all(token in allowed for token in _DIGITS.findall(r.hypothesis)):
            grounded += 1
    return round(grounded / len(resolutions), 4)


def audit_surfaces(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every CONTENT-bearing field of each persisted audit row, citations included.

    ``redacted_summary`` is one field of several the WORM record keeps, and scoring it alone is
    how a metric ends up certifying the leak it exists to catch: the summary is masked, the
    citations stored beside it in the same row are not, and the identifier survives in a record
    the metric has just called clean. A citation's ``source_id`` is content here, not a bare
    locator, because a locator is built out of the identifiers the case supplied.

    ``actor`` is deliberately absent. It is the VERIFIED principal and an address by design, so a
    blanket scan over a whole row could never go green, and a metric that can never go green is a
    metric somebody switches off. Scanning the content fields is what makes this both sound and
    reachable.
    """
    out: list[str] = []
    for row in rows:
        out.append(str(row.get("redacted_summary", "")))
        out.append(json.dumps(row.get("citations", []), sort_keys=True, default=str))
    return out


def pii_safety(surfaces: Sequence[str], planted: Sequence[str]) -> float:
    """1.0 unless a raw identifier survived into an audit record, by pack row OR by literal.

    The pack scan uses the same rows the redactor masks with, so it catches PII the pipeline
    re-introduced after redaction; the planted-literal scan is an independent oracle that still
    fires when a pack row is narrowed or broken, because a scorer that shares its only detector
    with the thing it is scoring agrees with itself by construction.
    """
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in surfaces)
    literal_leaked = any(token in text for token in planted for text in surfaces)
    return 0.0 if (pack_leaked or literal_leaked) else 1.0


def _run_engine() -> tuple[ReconRun, Container]:
    container = build_container(
        Settings(profile="local", audit_path=":memory:", tenant="demo-bank")
    )
    service = ResolutionService(
        feeds=container.feeds,
        generation=container.generation,
        review_router=container.review_router,
        audit=container.audit,
        case_engine=container.case_engine,
        tracer=container.tracer,
    )
    run = service.run(
        feed_a=FEED_A, feed_b=FEED_B, as_of=ANCHOR_AS_OF, actor="eval-bot", tenant="demo-bank"
    )
    return run, container


def run_smoke(dataset: Path) -> EvalReport:
    cases = _load(dataset)
    run, container = _run_engine()

    match_score = score_match_accuracy(run.matches, golden_matches(cases))
    typing_score = score_break_typing(run.ranked_breaks, golden_breaks(cases))
    grounded_score = score_groundedness(run)

    # pii_safety: no raw identifier may survive into any audit record. Independent of the engine.
    # The fixture reconciles a PII-carrying nostro row on every run, so the planted literals below
    # are actually present in the input and this metric has something real to fail on.
    audit = container.audit
    surfaces = audit_surfaces(audit.log.read_all())  # type: ignore[attr-defined]
    pii_score = pii_safety(surfaces, (PLANTED_NRIC, PLANTED_EMAIL))

    results = (
        EvalMetricResult.scored("match_accuracy", match_score, THRESHOLDS["match_accuracy"]),
        EvalMetricResult.scored(
            "break_typing_accuracy", typing_score, THRESHOLDS["break_typing_accuracy"]
        ),
        EvalMetricResult.scored("groundedness", grounded_score, THRESHOLDS["groundedness"]),
        EvalMetricResult.scored("pii_safety", pii_score, THRESHOLDS["pii_safety"]),
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(cases))


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"RECONBREAKS_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("RECONBREAKS_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / model-quality-gate for F1.",
        )
    )
