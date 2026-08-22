# Features FAQ

For product, finance-operations and delivery teams: what this engine produces, what is
deterministic versus drafted, and where its responsibilities **stop** and a sibling catalog
system takes over. Cross-references: [`../../README.md`](../../README.md),
[`../../DEMO.md`](../../DEMO.md), [`../../SPEC.md`](../../SPEC.md),
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).

### What does F1 actually produce?

From two named feed sets and an explicit `as_of` date it produces a `ReconRun`:

- **Matches**: the reconciled groups, each stamped with the pass that reconciled it and the
  residual it left (0 for an exact match, a fee, a tolerance drift, an FX drift).
- **Typed breaks**: the residue no pass could reconcile, classified by the engine as `timing`,
  `missing`, `duplicate`, `fx` or `fee`.
- **A ranked break worklist**: every break scored and ordered, carrying the per-signal
  contributions that produced its position.
- **A drafted resolution per break**: a severity, a proposed journal line, a prose hypothesis,
  the citations, and `requires_human_review` set.

Every artifact carries a `Citation` back to the feed and line it came from. The run is written to
a WORM audit trail already redacted, and the whole thing replays byte for byte from the same
inputs and the same `as_of`.

### How does the matching actually work?

`domain/match_engine.py` runs four pass families in a FIXED order, and an entry a pass consumes is
never offered to a later pass, so a looser pass can never claim a pair a stricter one would have
matched:

1. **exact**: same currency, same amount and same reference key, dated inside the timing window.
2. **tolerance**: same currency and same reference key, dated inside the window, with the
   difference inside the policy allowance, which is the LARGER of the per-currency basis points
   on the bigger leg and the per-currency absolute cap. The bps allowance covers a large ticket
   that may legitimately drift; the absolute cap covers a small ticket whose bps allowance rounds
   down to almost nothing.
3. **many_to_one**: a bounded subset search over same-currency, same-counterparty candidates
   inside the window, reconciling several entries on one side against one on the other and taking
   the lexicographically first exact subset so the result is stable. Two ceilings bound it, the
   policy's subset-size cap and a hard candidate-pool ceiling, past which the pass declines rather
   than hangs on a pathological feed. It runs in both directions.
4. **fx / fee**: same reference key inside the window. A cross-currency counterpart converted at
   the policy rate and landing inside the drift window is an `fx` match; a same-currency
   counterpart differing by more than nothing and no more than the fee cap is a `fee` match.
   Beyond either bound it is a real break for a human.

Money is an integer count of MINOR units throughout, so every comparison is exact and no float
rounding ever enters a consequential decision. The FX rates are fixed policy data rather than a
live feed, deliberately: a reconciliation must replay byte for byte, and a moving rate would
defeat that.

### How is the worklist ordered?

`domain/break_ranking.py` sums four integer factors: age times the age weight, a log-scaled
amount BAND times the amount weight, the repeat count above one times the repeat weight, and a
per-account criticality bonus. Ties break on `break_id`, so the ordering is total and
replay-stable. The amount contributes by band rather than linearly so one very large break cannot
swamp every aging signal, and every factor travels on the `RankedBreak` so a console can show WHY
a break sits where it does. Integer arithmetic throughout: a float score would make the ordering
sensitive to summation order, and a worklist that reorders itself on replay is not a worklist.

### What is deterministic, and what does the model do?

The consequential decisions are all deterministic, pure stdlib and unit-tested: canonicalisation
(`domain/normalise.py`), which entries reconcile and what kind of break the residue is
(`domain/match_engine.py`), the rank score (`domain/break_ranking.py`), the severity band, the
breach decision and the journal note (`domain/resolution_service.py`). The engine authors every
figure a human acts on.

The model narrates ONE field: the prose `hypothesis`. It is prompted only with engine-decided
facts, its output is redacted, and then it is groundedness-checked. Any digit run in the draft
that is not one of the engine's own figures discards the whole draft in favour of a deterministic
engine-authored line. A model that invents a number therefore changes nothing, because the
numbers a human acts on never came from it. See [`../model-card.md`](../model-card.md).

### Is anything auto-approved? Does it post a journal?

No, twice over. `requires_human_review` is set on every resolution, and the resolution is ROUTED
to the **Hrz7** human-review console in the same call that produced it (rule R8), through the
shared `review-kit`, with the payload redacted before the wire. A break that BREACHES its
aging or amount threshold additionally opens an escalation case on the Hrz7 case spine with a
clock taken from policy.

More fundamentally: **this service ships no posting port at all**. A drafted journal is text a
human keys into the ledger. There is nothing here that could auto-post even if someone wanted it
to.

### How many ways can I reach it?

Five, and they behave the same because they share the domain service rather than reimplementing
it: the FastAPI app (`POST /v1/reconcile`, `GET /v1/worklist/{worklist_id}`), the argparse CLI
(`recon_breaks_engine reconcile <feed_a> <feed_b>`), the agent tools (`reconcile_feeds` and
`verify_audit_trail`, advertised on the A2A card at `/.well-known/agent-card.json`), the
embeddable micro-frontend in `ui/`, and the eval harness. Each of them routes an escalated result
to human review in the same call that produced it, so rule R8 does not hold on four surfaces out
of five.

**Honest exception.** The `ui/` micro-frontend is fully built as a security boundary but its page
still calls the template's `/v1/triage` endpoint, which this service does not serve. The console
is not yet wired to this vertical's `/v1/reconcile` route, so treat the UI as a hardened shell
awaiting its views, not as a working break worklist.

### Which capabilities does this repo own versus integrate?

This is one system in a catalog of composable GRC systems. It **owns** the reconciliation domain
logic, the break taxonomy, the ranking and the ops-worklist export schema. It **integrates**
several cross-cutting concerns owned by sibling systems, and it is honest about the ones that are
not wired yet.

| Concern | Owner | This repo's role |
|---|---|---|
| Human review and maker-checker console | **Hrz7** | Routes every escalation to it (rule R8) over the shared review kit. Does not implement the console. |
| Escalation cases with an aging clock | **Hrz7** case spine | Opens a case when the engine decides a break has breached. The BREACH decision is this engine's; the workflow and the clock are configuration. |
| AI-quality and promotion gate | **Hrz4** | `eval/run_eval.py --mode gate` asks it for the promotion verdict and refuses to run off the managed profile. Registering the bundle is still open. |
| Observability and tracing | **Hrz5** | Exports OTLP to the Hrz5 collector when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. The shared immutable audit sink is NOT bound yet. |
| Agent registry, identity and entitlements | **Hrz3** | Publishes an A2A card built from the same tool table the runtime binds. Registration is NOT done. |
| Runtime guardrail: prompt-injection defence, output filtering | **Hrz1** | NOT wired. There is no `GuardrailPort` here. Redaction through `pii-kit` is a different control. |
| Governed knowledge base and grounded retrieval | **Hrz2** | Not used: this vertical performs no retrieval. A fork that adds one must integrate Hrz2. |
| The operations control room and handover view | **F5** (`control-room-handover`) | F1 OWNS the ops-worklist export schema and F5 consumes it. Do not rebuild the queue view here. |
| Disputes and chargebacks | **F2** | A sibling producer that conforms to the SAME export schema. A dispute is its journey, not this one's. |

So the guardrail, the audit sink, the eval platform, the review console and the control-room view
are *dependencies*, not features of this repo. See
[`../ADOPTING.md`](../ADOPTING.md) section 5 for the same map from a fork's point of view.

### What is the cross-repo metrics contract?

One versioned payload per reconciliation run, pinned at `ops-worklist-export/v1`, carrying
`feed_id`, `as_of`, `queue_depth`, `throughput`, aging buckets and the SLA clock state. It is a
DATA CONTRACT rather than a shared package: F1 owns the schema, F2 and F5 pin it, and each side
carries a drift guard. Every number is engine-computed and a consumer never recomputes one. See
[`../ops-metrics-contract.md`](../ops-metrics-contract.md).

### How do I see it working?

`make demo` runs the presenter-paced walkthrough: it starts its own loopback server, narrates each
step on the terminal (never on the page) and waits for you, then asserts the service really
reached the state the narration claimed. `make demo-selftest` is the same arc, headless and
unattended, exiting non-zero when a claim stops being true. `make demo-static` renders the
audit-first panels as dependency-free static HTML for screenshots. Everything runs offline on
synthetic, obviously fictional data with no cloud, no credentials and no API key. See
[`../../DEMO.md`](../../DEMO.md).
