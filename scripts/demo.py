"""The scripted, offline demo: the REAL services, synthetic data, an audit-first output view.

This is the demo as CODE (practices check F1), not a slide deck and not a recording. Every step
below drives the actual triage service, the actual hash-chained audit store and the actual
rule-R8 review router over the ``local`` profile, so a step that stops being true stops passing
rather than stops being mentioned.

Three properties make it worth running in front of somebody:

* **Nothing is faked.** No stub service, no pre-baked JSON. The severity bands, the audit
  records, the routing references and the tamper verdict are produced by the shipped code.
* **It is bounded.** The demo proves an offline, single-process seam. It does not prove
  cross-host deployment, a live console, or the managed profile; those need a cloud project and
  live in ``tests/integration/``.
* **It is replayable.** Same inputs, same output, every time, because the consequential decision
  is deterministic. That is what makes it safe to run live.

Run it directly to write the audit-view JSON, then render that JSON to static pages::

    make demo-static

or drive it one step at a time with ``demo_server.py`` and ``walkthrough.py`` (``make demo``).

Every party, address and identifier here is obviously fictional: ``.example`` domains, RFC 5737
and RFC 3849 literals, and a synthetic national id that exists only to prove redaction happened.

MAINTAINER NOTE: this file is rendered from a template, so no line may change length with the
package or service name. Every cookiecutter value is bound to a short module constant below and
referenced through it, and every import line is short enough that a long package name cannot
push it past the formatter's limit.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hex_service_kit.audit import HashChainedAuditLog
from hex_service_kit.identity import RequestContext
from hex_service_kit.serialization import to_jsonable

from recon_breaks_engine.adapters.local._recon_fixture import (
    ANCHOR_AS_OF,
    FEED_A,
    FEED_B,
    PLANTED_EMAIL,
    PLANTED_NRIC,
)
from recon_breaks_engine.config import (
    Settings,
    build_container,
)
from recon_breaks_engine.domain import (
    kernel,
    models,
)
from recon_breaks_engine.domain.pii import (
    JURISDICTIONS,
)
from recon_breaks_engine.domain.resolution_service import (
    ResolutionService,
)


def loaded_cloud_sdks() -> tuple[str, ...]:
    """Every managed-SDK module currently importable in THIS interpreter, sorted.

    Public because the demo, the walkthrough's checks and the test suite all ask the same
    question and must not each answer it slightly differently.
    """
    return tuple(sorted(name for name in sys.modules if name.split(".")[0] == "google"))


#: Rendered identity, bound once so no other line's length depends on how long a name is.
SERVICE_NAME = "Reconciliation Breaks Engine"
CATALOG_ID = "F1"
REPOSITORY = "recon-breaks-engine"

# --------------------------------------------------------------------------------------- #
# Synthetic data. Fictional parties, .example domains, RFC 5737 / RFC 3849 literals only.
# --------------------------------------------------------------------------------------- #

#: The VERIFIED principal the demo attributes work to. A client never asserts this.
ACTOR = "analyst@bank.example"
TENANT = "demo-bank"

# ``PLANTED_NRIC`` and ``PLANTED_EMAIL`` are re-exported from the offline fixture above, so the
# redaction panel has independent literals to look for rather than trusting the pattern pack to
# agree with itself. They ride on the fixture's own PII-carrying nostro row (its reference, its
# counterparty name and its warehouse citation), so the deterministic engine carries them into a
# resolution and the redaction pass masks them. Single-sourced deliberately: the demo used to
# keep its own copy of that row, and a demo reconciling different rows from the eval can narrate
# a clean run while the gate scores a run that never saw an identifier at all.


# --------------------------------------------------------------------------------------- #
# The presenter arc
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Step:
    """One presenter beat: what it shows, and the sentence the presenter reads aloud."""

    key: str
    label: str
    narration: str


#: The scripted arc, in order. ``walkthrough.py`` asserts the server reaches each key in turn
#: and carries an expectation per key, so a step added here without an expectation there fails
#: the self-test rather than silently extending the demo.
STEPS: tuple[Step, ...] = (
    Step(
        key="opened",
        label="Service bound on the offline profile",
        narration=(
            "The whole stack is bound from one settings file: no cloud project, no credentials, "
            "no SDK. Every port has an offline implementation, which is why this demo and the "
            "gate both run on a plane."
        ),
    ),
    Step(
        key="routine",
        label="A reconciled line: matched, cited, NOT a break",
        narration=(
            "One reconciled pair, from the multi-pass matcher. Which pass matched it, and the "
            "residual it left, are computed by pure stdlib code, never by a model. A clean match "
            "is not routed for review, because manufacturing a review for it trains reviewers to "
            "rubber-stamp."
        ),
    ),
    Step(
        key="escalation",
        label="The ranked break worklist: routed for review (rule R8)",
        narration=(
            "The residual breaks, ranked by a deterministic score. Setting a flag is not the "
            "escalation; routing is. Every break is handed to the human-review console in the "
            "same call that drafted it, and an aged or high-value break also opens a case on the "
            "Hrz7 case spine. Nothing posts to a ledger: there is no posting port."
        ),
    ),
    Step(
        key="redaction",
        label="Personal data is masked BEFORE the audit write",
        narration=(
            "A break whose counterparty carries a national id and whose warehouse citation "
            "quotes the raw statement line. Every content field of the record is masked before "
            "anything is written, the citations included, so the immutable record never contains "
            "either identifier. Redacting afterwards would be too late: the record is already "
            "immutable, and a check that read only the summary would call it clean."
        ),
    ),
    Step(
        key="review_queue",
        label="What the reviewer receives, already redacted on the wire",
        narration=(
            "The outbound review queue. The console is a SHARED sink, so payloads are redacted "
            "against every configured jurisdiction, not only the one this case came from."
        ),
    ),
    Step(
        key="audit",
        label="The audit trail verifies, and exports in an open format",
        narration=(
            "The trail is append-only and hash-chained, with an external head anchor on a "
            "separate volume. It exports to JSON Lines and reloads into a fresh store with "
            "every link intact: the record is yours, not this codebase's."
        ),
    ),
    Step(
        key="tamper",
        label="A rewritten record is DETECTED, not merely discouraged",
        narration=(
            "An attacker with file access drops the append-only triggers and rewrites one "
            "record. The store cannot prevent that. The hash chain names the exact record that "
            "broke, which is the honest guarantee: tamper-EVIDENT, not tamper-proof."
        ),
    ),
    Step(
        key="portability",
        label="The exit path fails fast instead of failing silently",
        narration=(
            "The same calls on the on-premises profile, with no code edited and no domain "
            "module touched. Every unimplemented seam refuses loudly. A placeholder that "
            "returned successfully would convert an escalation into an unreviewed decision."
        ),
    ),
)

STEP_KEYS: tuple[str, ...] = tuple(step.key for step in STEPS)


# --------------------------------------------------------------------------------------- #
# Panels: the audit-first output view (the result, its evidence, the findings, what is next)
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Row:
    """One labelled fact in a panel. ``tone`` drives the colour, never the meaning."""

    label: str
    value: str
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Panel:
    """One block of the output view: a title, labelled facts, and an interpretation."""

    title: str
    rows: tuple[Row, ...] = ()
    note: str = ""
    tone: str = ""


@dataclass(frozen=True, slots=True)
class StepResult:
    """Everything one step produced, ready to render or to assert against."""

    key: str
    label: str
    narration: str
    panels: tuple[Panel, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)


Produced = tuple[list[Panel], dict[str, Any]]


class DemoRun:
    """A live demo, advanced one step at a time over the real services.

    The run owns a working directory holding the durable audit store and its external anchor.
    They are separate directories on purpose: an anchor that lives beside the store it witnesses
    is rewritten by whatever rewrites the store.
    """

    def __init__(self, workdir: Path | None = None) -> None:
        # What was ALREADY loaded before this run began. The offline claim is that the demo
        # imports no cloud SDK, and in a live `python scripts/demo.py` nothing else has loaded
        # one, so the delta and the absolute set are the same list. In a shared pytest process
        # they are not: any other module in the suite may legitimately have imported google for
        # its own reasons (the IAP negative matrix does), and a claim measured as an absolute
        # would then be decided by test ordering rather than by the demo. The absolute form of
        # the claim is still made, in fresh interpreters, by `scripts/portability_demo.py`, by
        # the headless walkthrough and by `tests/unit/test_demo_surface.py`.
        self._cloud_sdk_before = frozenset(loaded_cloud_sdks())
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        if workdir is None:
            self._tempdir = tempfile.TemporaryDirectory(prefix="demo-run-")
            workdir = Path(self._tempdir.name)
        self.workdir = workdir
        self.audit_path = workdir / "store" / "audit.sqlite3"
        self.anchor_path = workdir / "anchor" / "head.json"
        # The audit store creates its own parent; the ANCHOR does not, because it is meant to
        # live on a volume somebody provisioned deliberately rather than one a library invented.
        # An operator therefore has to create that directory too; the demo does it here so the
        # first run of `make demo` in a fresh checkout does not fail on a missing path.
        self.anchor_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(
            profile="local",
            audit_path=str(self.audit_path),
            audit_anchor_path=str(self.anchor_path),
            tenant=TENANT,
        )
        self.container = build_container(self.settings)
        self.service = ResolutionService(
            feeds=self.container.feeds,
            generation=self.container.generation,
            review_router=self.container.review_router,
            audit=self.container.audit,
            case_engine=self.container.case_engine,
            tracer=self.container.tracer,
        )
        # The pure half of a run: match and rank, but route nothing yet. The escalation and
        # redaction beats route selected breaks, so the presenter sees routing happen live rather
        # than as an already-finished side effect.
        self.matches, self.ranked = self.service.reconcile_only(
            feed_a=FEED_A, feed_b=FEED_B, as_of=ANCHOR_AS_OF
        )
        self._pii_break = next(rb for rb in self.ranked if "A-PII" in rb.record.entry_ids)
        self._other_breaks = [rb for rb in self.ranked if rb is not self._pii_break]
        self.results: list[StepResult] = []
        self.cases = len(self.matches) + len(self.ranked)
        self.escalated = 0
        self.routed = 0
        self.chain_ok = True
        self._perform(STEPS[0])

    # -------------------------------------------------------------- control

    @property
    def index(self) -> int:
        """Index of the step most recently performed."""
        return len(self.results) - 1

    @property
    def done(self) -> bool:
        return len(self.results) >= len(STEPS)

    def advance(self) -> StepResult:
        """Perform the next step, or re-return the last one when the arc is finished."""
        if self.done:
            return self.results[-1]
        return self._perform(STEPS[len(self.results)])

    def run_to_end(self) -> None:
        while not self.done:
            self.advance()

    def _perform(self, step: Step) -> StepResult:
        handler: Callable[[], Produced] = getattr(self, "_step_" + step.key)
        panels, facts = handler()
        result = StepResult(
            key=step.key,
            label=step.label,
            narration=step.narration,
            panels=tuple(panels),
            facts=facts,
        )
        self.results.append(result)
        return result

    # -------------------------------------------------------------- steps

    def _step_opened(self) -> Produced:
        bindings = [
            Row(port, self.settings.adapters[port][self.settings.profile].split(":")[-1])
            for port in sorted(self.settings.adapters)
        ]
        profiles = sorted({name for table in self.settings.adapters.values() for name in table})
        sdk = [name for name in loaded_cloud_sdks() if name not in self._cloud_sdk_before]
        deployment = Panel(
            title="Deployment",
            rows=(
                Row("Service", SERVICE_NAME),
                Row("Catalog id", CATALOG_ID),
                Row("Profile", self.settings.profile, "ok"),
                Row("Profiles bound for every port", ", ".join(profiles)),
                Row("Residency region", self.settings.region),
                Row("Jurisdiction PII packs", ", ".join(JURISDICTIONS)),
            ),
            note=(
                "One environment variable selects the adapter family for every port. Nothing "
                "below was edited to make the service run offline."
            ),
        )
        adapters = Panel(
            title="Bound adapters",
            rows=tuple(bindings),
            note="The binding map lives in config/settings.yaml, not in the code.",
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Cloud SDK modules imported", ", ".join(sdk) or "none", "bad" if sdk else "ok"),
                Row("Credentials required", "none", "ok"),
                Row("Network required", "none", "ok"),
            ),
            note=(
                "The managed adapters import their SDK lazily, so this profile runs with none "
                "installed at all."
            ),
            tone="bad" if sdk else "ok",
        )
        facts = {"profile": self.settings.profile, "sdk_modules": sdk, "profiles": profiles}
        return [deployment, adapters, findings], facts

    def _step_routine(self) -> Produced:
        match = next((m for m in self.matches if m.pass_name == "exact"), self.matches[0])
        decision = Panel(
            title="Reconciled: " + match.pass_name + " pass",
            rows=(
                Row("Pass", match.pass_name, "ok"),
                Row("Feed A entries", ", ".join(match.a_entry_ids)),
                Row("Feed B entries", ", ".join(match.b_entry_ids)),
                Row("Residual (minor units)", str(match.residual_minor)),
                Row("Routed to review", "not routed (clean match)", "ok"),
            ),
            note=(
                "The pass name and the residual are computed by pure stdlib code and replay "
                "byte for byte. A clean match is not a break, so nothing is routed."
            ),
        )
        evidence = Panel(
            title="Evidence",
            rows=tuple(Row(c.title, c.snippet or c.source_id) for c in match.citations)
            or (Row("citations", "NONE", "bad"),),
            note="Every match cites the exact feed lines it reconciled.",
        )
        facts = {
            "pass": match.pass_name,
            "requires_human_review": False,
            "review_ref": "",
        }
        return [decision, evidence], facts

    def _step_escalation(self) -> Produced:
        rows: list[Row] = []
        top_ref = ""
        for ranked_break in self._other_breaks:
            resolution, ref = self.service.resolve_and_route(
                ranked_break, as_of=ANCHOR_AS_OF, actor=ACTOR, tenant=TENANT
            )
            self.escalated += 1
            self.routed += 1
            top_ref = top_ref or ref
            brk = ranked_break.record
            rows.append(
                Row(
                    "#" + str(ranked_break.rank) + " " + brk.break_type.value,
                    brk.currency
                    + " "
                    + str(brk.amount_minor)
                    + " minor, age "
                    + str(brk.age_days)
                    + "d, score "
                    + str(ranked_break.score),
                    "bad",
                )
            )
        worklist = Panel(
            title="Ranked break worklist",
            rows=tuple(rows),
            note=(
                "Ranked by a deterministic integer score (age, amount band, repeat, account "
                "criticality). Every break is routed for review in the same call that drafted it."
            ),
            tone="bad",
        )
        cases = Panel(
            title="Escalation cases opened (aged or high value)",
            rows=tuple(
                Row(h.case_id, "workflow " + h.workflow + ", deadline " + h.deadline.isoformat())
                for h in self.container.case_engine.opened
            )
            or (Row("cases", "none breached the clock", "ok"),),
            note="A breaching break opens a case on the Hrz7 case spine with an aging clock.",
        )
        facts = {
            "requires_human_review": True,
            "review_ref": top_ref,
            "routed": self.routed,
            "cases_opened": len(self.container.case_engine.opened),
        }
        return [worklist, cases], facts

    def _step_redaction(self) -> Produced:
        resolution, ref = self.service.resolve_and_route(
            self._pii_break, as_of=ANCHOR_AS_OF, actor=ACTOR, tenant=TENANT
        )
        self.escalated += 1
        self.routed += 1
        row = self.container.audit.log.read_all()[-1]
        recorded = str(row["redacted_summary"])
        # Scan every CONTENT-bearing field of the row, not just the summary. Reading the summary
        # alone is how this panel could have shown "absent" with the identifier sitting in the
        # citations of the same immutable record: the summary is the one field the redaction pass
        # used to touch. ``actor`` is left out on purpose, because the verified principal is an
        # address by design and flagging it would make the check impossible to ever satisfy.
        stored = recorded + json.dumps(row.get("citations", []), sort_keys=True, default=str)
        leaked = any(
            planted in text
            for planted in (PLANTED_NRIC, PLANTED_EMAIL)
            for text in (stored, resolution.subject, resolution.journal_note)
        )
        panel = Panel(
            title="Redact before the write",
            rows=(
                Row("Identifier on the counterparty record", PLANTED_NRIC, "warn"),
                Row("Identifier in the warehouse citation", PLANTED_EMAIL, "warn"),
                Row(
                    "Identifier in the immutable record",
                    "PRESENT" if leaked else "absent",
                    "bad" if leaked else "ok",
                ),
                Row("Stored summary", recorded),
                Row("Routed to review", ref, "ok"),
            ),
            note=(
                "The engine carried the counterparty and the warehouse's own citation into the "
                "drafted resolution; the redaction pass masked both before the audit write, "
                "which is immutable and so cannot be cleaned afterwards."
            ),
            tone="bad" if leaked else "ok",
        )
        facts = {
            "planted_identifier_leaked": leaked,
            "requires_human_review": True,
            "review_ref": ref,
        }
        return [panel], facts

    def _step_review_queue(self) -> Produced:
        pending = list(self.container.review_router.outbox.pending())
        rows: list[Row] = []
        leaked = False
        for item in pending:
            payload = to_jsonable(item)
            wire = json.dumps(payload, sort_keys=True)
            leaked = leaked or PLANTED_NRIC in wire or PLANTED_EMAIL in wire
            rows.append(Row(str(getattr(item, "source_key", "review")), _summarise(payload)))
        queue = Panel(
            title="Outbound review queue",
            rows=tuple(rows) or (Row("queue", "empty", "bad"),),
            note=(
                "Queued, not submitted. The reference the caller received says exactly that, so "
                "a buffered escalation is never mistaken for a reviewed one."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Escalated results", str(self.escalated)),
                Row(
                    "Routed to review",
                    str(self.routed),
                    "ok" if self.routed == self.escalated else "bad",
                ),
                Row(
                    "Personal data on the wire",
                    "LEAKED" if leaked else "none",
                    "bad" if leaked else "ok",
                ),
            ),
            note=(
                "Every escalation is accounted for. A flag with no routing reference is "
                "auto-execution with extra steps."
            ),
            tone="bad" if leaked or self.routed != self.escalated else "ok",
        )
        actions = Panel(
            title="Next actions",
            rows=(
                Row("Reviewer", "open the queued item and approve or reject it"),
                Row("Operator", "point HUMAN_REVIEW_URL at the console and flush the outbox"),
            ),
        )
        return [queue, findings, actions], {"pending": len(pending), "wire_leak": leaked}

    def _step_audit(self) -> Produced:
        log = self.container.audit.log
        report = self.container.audit.verify()
        self.chain_ok = report.ok
        export = self.workdir / "export" / "audit.jsonl"
        export.parent.mkdir(parents=True, exist_ok=True)
        written = log.export_jsonl(export)
        restored = HashChainedAuditLog(":memory:")
        reloaded = restored.import_jsonl(export)
        round_trip = restored.verify_chain()
        anchored = bool(self.settings.audit_anchor_path) and self.anchor_path.exists()
        trail = Panel(
            title="Audit trail",
            rows=(
                Row("Records", str(report.entries)),
                Row("Hash-chained", str(report.chained)),
                Row(
                    "Unverifiable (unchained)",
                    str(report.legacy),
                    "ok" if report.legacy == 0 else "bad",
                ),
                Row("Verdict", report.detail, "ok" if report.ok else "bad"),
                Row(
                    "External head anchor",
                    "configured" if anchored else "absent",
                    "ok" if anchored else "warn",
                ),
            ),
            note=(
                "The chain alone cannot detect a truncated tail: dropping the newest rows leaves "
                "a shorter chain that verifies perfectly. The anchor, kept on a different "
                "volume, is what closes that gap."
            ),
            tone="ok" if report.ok else "bad",
        )
        portable = Panel(
            title="Open-format round trip",
            rows=(
                Row("Exported records", str(written)),
                Row("Reloaded into a fresh store", str(reloaded)),
                Row(
                    "Chain after reload",
                    round_trip.detail,
                    "ok" if round_trip.ok else "bad",
                ),
            ),
            note=(
                "JSON Lines with the hashes included, so a consumer can re-verify the trail "
                "without this codebase. That is what makes the record portable."
            ),
            tone="ok" if round_trip.ok else "bad",
        )
        facts = {
            "chain_ok": report.ok,
            "entries": report.entries,
            "exported": written,
            "round_trip_ok": round_trip.ok,
            "anchored": anchored,
        }
        return [trail, portable], facts

    def _step_tamper(self) -> Produced:
        before = self.container.audit.verify()
        target = _rewrite_a_record(self.audit_path)
        after = self.container.audit.verify()
        self.chain_ok = after.ok
        detected = (not after.ok) and after.first_bad_seq == target
        attack = Panel(
            title="The tamper",
            rows=(
                Row("Append-only triggers", "dropped by the attacker", "warn"),
                Row("Record rewritten in place", "seq " + str(target), "warn"),
                Row("Verdict before the rewrite", before.detail, "ok"),
            ),
            note=(
                "File access beats a database trigger. A store that claims otherwise is "
                "describing a policy, not a control."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Chain intact", "YES" if after.ok else "no", "bad" if after.ok else "ok"),
                Row("First broken record", str(after.first_bad_seq), "ok"),
                Row("Detail", after.detail),
                Row(
                    "Named the exact rewritten record",
                    "yes" if detected else "no",
                    "ok" if detected else "bad",
                ),
            ),
            note=(
                "Tamper-EVIDENT, not tamper-proof. The guarantee is that a rewrite cannot pass "
                "unnoticed, and that the report names which record broke."
            ),
            tone="ok" if detected else "bad",
        )
        actions = Panel(
            title="Next actions",
            rows=(
                Row("Operator", "restore from the exported JSONL and re-anchor deliberately"),
                Row("Auditor", "treat every record from seq " + str(target) + " on as suspect"),
            ),
        )
        facts = {"tampered_seq": target, "detected": detected, "chain_ok": after.ok}
        return [attack, findings, actions], facts

    def _step_portability(self) -> Produced:
        onprem = build_container(Settings(profile="onprem", tenant=TENANT))
        rows: list[Row] = []
        refused: list[str] = []
        absent: list[str] = []
        for port, call in EXIT_CALLS.items():
            expected_absent = port in EXIT_ABSENT
            try:
                call(onprem)
            except NotImplementedError as exc:
                if expected_absent:
                    rows.append(Row(port, "REFUSED, but is meant to be absent", "bad"))
                else:
                    refused.append(port)
                    rows.append(Row(port, "refused: " + str(exc).split(":")[0], "ok"))
            else:
                if expected_absent:
                    absent.append(port)
                    rows.append(Row(port, "absent, by design (a diagnostic, not a control)", "ok"))
                else:
                    rows.append(Row(port, "SUCCEEDED SILENTLY", "bad"))
        exit_panel = Panel(
            title="Exit profile (onprem)",
            rows=tuple(rows),
            note=(
                "Selected by one environment variable. No domain module was edited and no "
                "import changed."
            ),
            tone="ok" if len(refused) + len(absent) == len(EXIT_CALLS) else "bad",
        )
        bounds = Panel(
            title="What this does and does not prove",
            rows=(
                Row("Proved", "every port is swappable and every seam is named"),
                Row("Proved", "an unimplemented seam refuses instead of dropping work"),
                Row("NOT proved", "a running on-premises deployment exists"),
                Row("NOT proved", "model, infrastructure or whole-system portability"),
            ),
            note=(
                "Bounded claims are the point. Run scripts/portability_demo.py for the full "
                "seam tour, with a pass or fail per named check."
            ),
        )
        return [exit_panel, bounds], {
            "refused": sorted(refused),
            "absent": sorted(absent),
        }

    # -------------------------------------------------------------- state

    def state(self) -> dict[str, Any]:
        """The whole run as JSON-safe data: what the UI renders and the walkthrough asserts."""
        current = self.results[-1]
        return {
            "service": SERVICE_NAME,
            "catalog_id": CATALOG_ID,
            "repository": REPOSITORY,
            "profile": self.settings.profile,
            "region": self.settings.region,
            "step": current.key,
            "step_index": self.index,
            "step_count": len(STEPS),
            "label": current.label,
            "next": "" if self.done else STEPS[len(self.results)].label,
            "done": self.done,
            "totals": {
                "cases": self.cases,
                "escalated": self.escalated,
                "routed": self.routed,
                "chain_ok": self.chain_ok,
            },
            "steps": [_step_to_dict(result) for result in self.results],
        }


def _step_to_dict(result: StepResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "label": result.label,
        "narration": result.narration,
        "facts": result.facts,
        "panels": [
            {
                "title": panel.title,
                "note": panel.note,
                "tone": panel.tone,
                "rows": [
                    {"label": row.label, "value": row.value, "tone": row.tone} for row in panel.rows
                ],
            }
            for panel in result.panels
        ],
    }


def _summarise(payload: Any) -> str:
    """One readable line for a queued review, without dumping the whole payload."""
    if isinstance(payload, dict):
        parts = [
            str(payload[key])
            for key in ("title", "severity", "maker", "tenant")
            if payload.get(key)
        ]
        if parts:
            return " / ".join(parts)
    return json.dumps(payload, sort_keys=True)[:120]


def _rewrite_a_record(store: Path) -> int:
    """Drop the append-only triggers and rewrite one INTERIOR record, as an attacker would.

    Returns the ``seq`` that was rewritten. An interior row is chosen deliberately: rewriting
    the newest row is the easy case, and the chain has to catch a rewrite in the middle of the
    trail too.
    """
    conn = sqlite3.connect(store)
    try:
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
        rows = conn.execute("SELECT seq, event_json FROM audit_log ORDER BY seq ASC").fetchall()
        if len(rows) < 3:
            raise RuntimeError("the tamper step needs an interior record to rewrite")
        middle = rows[len(rows) // 2]
        payload = json.loads(middle[1])
        payload["decision"] = "allowed"
        payload["severity"] = "low"
        conn.execute(
            "UPDATE audit_log SET event_json = ? WHERE seq = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), int(middle[0])),
        )
        conn.commit()
        return int(middle[0])
    finally:
        conn.close()


_EXIT_RESOLUTION = models.BreakResolution(
    subject="break BRK-missing-A6 (ZETA INC FICTIONAL)",
    severity=kernel.Severity.HIGH,
    decision=kernel.Decision.ESCALATED,
    summary="One feed carries this item with no counterpart on the other.",
    requires_human_review=True,
    break_id="BRK-missing-A6",
    break_type=models.BreakType.MISSING,
    hypothesis="One feed carries this item with no counterpart on the other.",
    journal_note="Investigate missing break; do NOT post until a checker confirms.",
    citations=(kernel.Citation(source_id="nostro:7", title="Feed nostro line 7", snippet="A6"),),
)


def _exit_audit(container: Any) -> Any:
    return container.audit.record(
        kernel.AuditEvent(
            action="recon_resolution",
            actor=ACTOR,
            decision=kernel.Decision.ESCALATED,
            severity=kernel.Severity.HIGH,
            redacted_summary="break BRK-missing-A6: missing counterpart",
        )
    )


def _exit_review(container: Any) -> Any:
    return container.review_router.route(_EXIT_RESOLUTION, maker=ACTOR, tenant=TENANT)


def _exit_identity(container: Any) -> Any:
    # The persona header is deliberately present. It is what the OFFLINE family answers, so
    # sending it proves the exit family refuses the call itself rather than merely lacking an
    # input: a placeholder that returned a principal for a client-written header would be worse
    # than one that raises.
    return container.identity.resolve(RequestContext(headers={"x-dev-persona": "approver"}))


def _exit_feeds(container: Any) -> Any:
    return container.feeds.fetch(FEED_A)


def _exit_generation(container: Any) -> Any:
    return container.generation.draft("break_type: missing")


def _exit_worklist_store(container: Any) -> Any:
    return container.worklist_store.get("wl:demo-bank:nostro:scheme")


def _exit_case_engine(container: Any) -> Any:
    from recon_breaks_engine.ports.case_engine import CaseRequest

    return container.case_engine.open_case(
        CaseRequest(
            break_id="BRK-missing-A6",
            break_type="missing",
            workflow="recon-break-missing",
            clock_days=3,
            as_of=ANCHOR_AS_OF,
            amount_minor=9000,
            currency="USD",
            counterparty_key="ZETA INC",
            opened_by=ACTOR,
            tenant=TENANT,
        )
    )


def _exit_tracer(container: Any) -> Any:
    with container.tracer.span("exit.tour", action="portability"):
        return None


def _exit_evaluation(container: Any) -> Any:
    return container.evaluation.gate("eval/datasets/golden_cases.jsonl")


#: The calls the exit profile must REFUSE, one per port with an exit placeholder. Add a port,
#: add a row: a seam nobody calls is a seam nobody knows is unimplemented.
#:
#: IDENTITY is the load-bearing one. What the bound identity adapter DECLARES is the single flag
#: the exposure guard reads before it stands down and lets the process bind every interface, so a
#: portability tour that toured every seam except that one would skip the one that matters most.
EXIT_CALLS: dict[str, Callable[[Any], Any]] = {
    "audit": _exit_audit,
    "identity": _exit_identity,
    "review_router": _exit_review,
    "tracer": _exit_tracer,
    "evaluation": _exit_evaluation,
    "feeds": _exit_feeds,
    "generation": _exit_generation,
    "case_engine": _exit_case_engine,
    "worklist_store": _exit_worklist_store,
}


#: Diagnostic seams that complete as an honest no-op under the exit profile.
EXIT_ABSENT: frozenset[str] = frozenset({"tracer"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scripted offline demo end to end.")
    parser.add_argument(
        "output",
        nargs="?",
        default="demo.json",
        help="where to write the audit-view JSON (default: demo.json)",
    )
    parser.add_argument("--quiet", action="store_true", help="write the JSON and print nothing")
    args = parser.parse_args(argv)

    run = DemoRun()
    run.run_to_end()
    state = run.state()
    Path(args.output).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        for step in state["steps"]:
            print("[" + step["key"] + "] " + step["label"])
        totals = state["totals"]
        print(
            "cases="
            + str(totals["cases"])
            + " escalated="
            + str(totals["escalated"])
            + " routed="
            + str(totals["routed"])
        )
        print("wrote " + args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
