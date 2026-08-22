# Model card: Reconciliation Breaks Engine (F1)

This is a STARTER model card. It records the model boundary as built and the controls that must be
completed before a managed deployment. The deterministic engine is the system of record; the model
is a bounded, replaceable component that narrates one field.

## What the model does, and does not do

- **Does**: draft a one-sentence prose `hypothesis` describing the likely root cause of a single
  reconciliation break, from a prompt assembled entirely out of already-decided engine facts
  (`break_id`, `break_type`, `amount`, `currency`, `age_days`, `rank`, `entries`). That is the
  whole of its job, and `ports/generation.py` is the only seam it sits behind.
- **Does NOT**: produce any number, any classification or any verdict. Which entries reconcile,
  what residual a pass leaves, what KIND of break the residue is
  (`timing` / `missing` / `duplicate` / `fx` / `fee`), the integer rank score and its four
  factors, the severity band, whether the break BREACHES its aging or amount threshold, and the
  proposed journal line are all computed in pure stdlib by `domain/normalise.py`,
  `domain/match_engine.py`, `domain/break_ranking.py` and `domain/resolution_service.py`. With the
  generation adapter stubbed or failing, every figure in the run is byte-identical, so a model
  change cannot move a number a human acts on.

There is no posting port in this repository at all, so the model sits two removes from any ledger
effect: it narrates a draft, and a human keys the journal.

## Boundary and validation

The order in `domain/resolution_service.py::_grounded_hypothesis` is load-bearing:

1. The prompt is built by `_build_prompt` from the engine facts only, and it instructs the model
   not to invent any figure, amount, date or count that is not in those facts.
2. The returned draft is redacted with `pii-kit` (`domain/pii.py`) BEFORE it is inspected or
   used, so an identifier the model echoed never survives.
3. The draft is groundedness-checked: every digit run in it must be one of the engine's own
   figures (the amount, its digit groups, the age in days, the rank, or a digit group from the
   break id). An empty draft, or one carrying any other number, is DISCARDED for a deterministic
   engine-authored line from `_deterministic_hypothesis`.
4. Any exception from the generation port, including a lazy-import failure with no SDK present,
   falls back to the same deterministic line. A model outage degrades the prose and nothing else.
5. The resulting summary and subject are redacted again before they reach the audit write or the
   review payload, and the resolution sets `requires_human_review` and is ROUTED to Hrz7 in the
   same call (rule R8).

The offline eval scores `groundedness` at a 0.99 threshold alongside `pii_safety` at 0.99,
`match_accuracy` at 0.90 and `break_typing_accuracy` at 0.90, against an independent golden oracle
in `eval/datasets/golden_cases.jsonl` rather than against the pipeline's own output.
`tests/unit/test_not_falsely_green.py` proves the metrics can go red.

## Adapters and profiles

| Profile | Generation adapter | Behaviour |
|---|---|---|
| `local` | `adapters/local/generation.py` | A deterministic, digit-free narrator. It reads `break_type` out of the prompt facts and returns one fixed sentence per break type, with a generic fallback for an unknown type. Carrying no digits at all, its output always passes the caller's groundedness check, which is the correct behaviour for a narrator that invents nothing. SDK-free, and this is what the gate, the eval and the demo run. |
| `gcp` | `adapters/gcp/generation.py` | A placeholder with a REAL lazy import of `google.generativeai` inside `draft`, followed by a `RuntimeError` naming the missing piece: no model endpoint is wired. It is listed in `managed_readiness.py` as `generation.CloudGenerationAdapter.draft`, so the API preflight REFUSES to start a `gcp` process while this binding is active. There is no live model in this repository today. |
| `onprem` | `adapters/onprem/generation.py` | Fail-fast placeholder: raises `NotImplementedError` pointing at [`onprem-migration.md`](onprem-migration.md). The client binds their own model host. |

Because the caller enforces grounding on ANY generation adapter, swapping in a real model changes
only the prose, never the guarantee.

## Remaining controls (TODO, repo owner)

- **Model id, version and routing** for the `gcp` adapter (P-07): pin the exact model and record
  it here, wire the endpoint, and remove the entry from `INCOMPLETE_MANAGED_OPERATIONS` in
  `managed_readiness.py` only once an integration test proves the response mapping.
- **Budget, rate and a kill switch** (P-10, P-11): a per-tenant token budget, a request rate
  limit, and a switch that forces deterministic-only operation with the model disabled. The
  fallback path already exists (any exception yields the engine-authored line), but nothing
  exposes it as a deliberate control.
- **Evaluation of the live model**: today's `groundedness` score measures the deterministic
  offline narrator, which cannot fail the check by construction. Add a managed-profile eval run
  through the **Hrz4** promotion gate that scores a real model's drafts against the same golden
  cases, and register this repo's metric bundle and thresholds with Hrz4 (the open P-08 and R5
  items in [`../COMPLIANCE.md`](../COMPLIANCE.md)).
- **Prompt-injection screening** on the feed text before generation, through the **Hrz1**
  guardrail gateway, failing closed to deterministic-only when the screen is unavailable. There is
  no `GuardrailPort` in `ports/` today; this is the open R1 item.
- **Token and cost telemetry**: `ObservabilityTracerPort.record_token_usage` exists on the port
  and the managed tracer implements it, but no generation call reports usage, because no
  generation call reaches a model yet.

Until these are complete the system is safe to run offline (deterministic engine plus the
digit-free narrator) and the managed model path is not production-cleared. The preflight in
`managed_readiness.py` enforces that rather than leaving it to a reader.
