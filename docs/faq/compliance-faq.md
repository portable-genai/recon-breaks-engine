# Compliance FAQ

For compliance, operational-risk and model-risk teams assessing this repo's posture.
Cross-references: [`../../COMPLIANCE.md`](../../COMPLIANCE.md) (the full P-01 to P-13 and R1 to R8
map with an evidence file per row, plus the adopter-owned regulator crosswalk),
[`../../SPEC.md`](../../SPEC.md), [`../practices-audit.md`](../practices-audit.md) (the per-check
verdict).

### Is this making posting decisions autonomously?

No, and the reason is structural rather than a setting. Every drafted resolution sets
`requires_human_review`, and setting it is not the escalation: the `ReviewRouterPort.route` call
in the SAME act is, and the API, the CLI and the agent tool all route in the same call that
produced the result (`tests/unit/test_review_routing.py` is the standing gate). A break that
BREACHES its aging or amount threshold additionally opens an escalation case on the `human-review-console` case
spine with a clock taken from policy. A `CRITICAL` band asks the console for TWO approvals rather
than one (`adapters/_review_payload.py`).

Underneath all of that, **there is no posting port in this repository**. A drafted journal line is
text a human keys into the ledger. Nothing here could auto-post.

### How is customer and counterparty data handled?

This service reads feed rows carrying amounts, references, counterparties and accounts, so the
identifying surface is real and is treated as such. The shared `pii-kit` redacts with a
jurisdiction selection this deployment owns (`domain/pii.py`, shipped as `SG`, `HK`, `JP`, `AU`,
national-ID rows ordered before universal email and phone rows), and redaction happens before
each boundary rather than once: before the model draft is used, before the review payload leaves
the process, and before the audit write. Agent tool results are masked too, because a tool result
becomes a model's context.

The safety metric is scored two ways in the eval, and `tests/unit/test_not_falsely_green.py`
proves it can go RED, which is what stops a redaction claim from being a number that always reads
1.0.

Cross-tenant reads are refused in the DOMAIN and answer 403, never 404, because a 404 would leak
whether an id is in use across the tenant boundary.

### How is the work auditable and reproducible?

Every run writes already-redacted `AuditEvent` records whose actor is the VERIFIED principal,
never the request body. Every artifact carries a `Citation` back to the feed and line it came
from. The consequential decisions are pure stdlib over an explicit `as_of`, so a reviewer can
recompute any match, any break type, any rank score and any severity band from the same inputs
and get the same bytes.

Tamper evidence is stated with its limits. The offline sink is hash-chained AND externally
anchored: the chain catches an edit, a deletion or a reorder, and only the anchor catches a
TRUNCATED TAIL, because a truncated chain verifies perfectly on its own.
`tests/unit/test_audit_anchor.py` proves the detection and proves the control case goes undetected
without an anchor. In a managed deployment the trail lands in a LOCKED Cloud Logging bucket
(`infra/terraform/logging_worm.tf`, `worm_locked` defaults to true at a 180-day retention floor,
and the lock is irreversible), with `DATA_READ` audit logging enabled so a read of the evidence is
itself recorded.

### Is data residency actually enforced, or just documented?

Enforced at deploy time, in four independent layers, all in `infra/terraform/`:

- `variables.tf` validates the EFFECTIVE region against `var.allowed_regions` at PLAN time, so an
  unvetted region fails before an apply. The default allowlist is exactly the region this repo was
  rendered for, `asia-southeast1`.
- `org_policy.tf` applies `constraints/gcp.resourceLocations` restricted to the selected region's
  location group, plus `iam.disableServiceAccountKeyCreation` and
  `storage.uniformBucketLevelAccess`. Gated on `var.enable_org_policies`, default true.
- `kms.tf` creates a REGIONAL CMEK key ring and key with 90-day rotation, with a per-service-agent
  binding for each managed service, because CMEK does not cascade.
- `vpc_sc.tf` stands up a VPC Service Controls perimeter that starts in DRY RUN
  (`var.vpc_sc_enforce` defaults to false) and is flipped to enforcing only after the dry-run
  violations have been watched. Gated on `var.enable_vpc_sc`, default true.

The runtime half agrees: the region is one value in `config/settings.yaml`, reported by `/healthz`
and printed on the agent card, so a drifting deployment is visible.

**The honest caveat.** `infra/terraform/production_edge.tftest.hcl` encodes these claims as
credential-free `terraform test` runs, and it is a real suite. But no `make` target and no
workflow in this repo invokes it, so the residency posture is asserted in Terraform rather than
guarded by a build that goes red on a regression. That is why the P-03 row in `COMPLIANCE.md` is
`Partial` rather than `Covered`: the legend reserves `Covered` for a control a test fails the
build over.

### What is the model-risk story?

The model's job is one prose field and nothing else. See [`../model-card.md`](../model-card.md)
for the full boundary; the short version is that the matching, the break typing, the ranking, the
severity band and the breach decision are all deterministic, and a drafted narration carrying a
digit the engine did not produce is DISCARDED for an engine-authored line.

The offline eval gate (`eval/run_eval.py`) scores four metrics against an INDEPENDENT golden
oracle rather than against the pipeline's own output: `match_accuracy` and
`break_typing_accuracy` at 0.90, `groundedness` and `pii_safety` at 0.99. It runs on every merge
in `make gate` and in its own required workflow. `--mode gate` is the promotion path and delegates
the verdict to the `model-quality-gate` AI-quality service, refusing to run off the managed profile, because
a promotion certified by a laptop with no quality service is certified by nothing.

Two open items to record in a risk assessment: this repo's metric bundle and thresholds are NOT
yet registered with `model-quality-gate` (P-08 and R5), and the managed generation adapter is still a placeholder
that the process preflight refuses to serve, so there is no live-model eval to review.

### Which controls are still open?

`COMPLIANCE.md` is the authority and marks each row explicitly. In summary, as of this writing:

- **P-05 grounding, P-10 resilience, P-11 cost and latency**: `TODO (repo owner)`. There is no
  retrieval port and no live model call yet, so there is nothing to ground, route or cache;
  timeouts, a circuit breaker and a documented kill switch per outbound dependency are owed.
- **R1 guardrail (`agent-guardrail-gateway`)**: not wired. No `GuardrailPort` exists. Redaction is a different control.
- **R2 shared audit sink and traces (`agent-observability`)**: half wired. Tracing exports OTLP to the `agent-observability`
  collector when configured; the audit stream does not reach the shared sink.
- **R3 knowledge base (`enterprise-knowledge-base`)**: not applicable today, mandatory the moment retrieval appears.
- **R4 agent registry (`agent-registry`)**: the A2A card is published but not registered.
- **R6 intake validation (`architecture-validator`)**: an intake action, not a code control. Record the reference.
- **Tenant isolation**: the domain boundary and the store-side filter exist and are tested; the
  `COMPLIANCE.md` row still describes the earlier state and should be re-read against
  `worklist_access.py` and `tests/unit/test_worklist_store_authz.py`.

A control marked `TODO (repo owner)` is NOT coverage. Do not cite a TODO row as evidence to a
second or third line of defence.

### Which regulators does this map to?

The in-repo mapping is to the catalog's own principles and dependency rules, aligned to MAS TRM,
APRA CPS 234 and CPS 230, HKMA and PDPA-class regimes. The mapping from those to a SPECIFIC
regulation, and the judgement that a control is SUFFICIENT for it, is deliberately adopter-owned:
it depends on the institution's risk appetite, its regulator, its licence conditions and its
existing control library. This repo does not make that claim on an adopter's behalf, and no row
in `COMPLIANCE.md` should be quoted as regulatory assurance. The last section of that file lists
what an adopter is expected to add in their own control library, including the risk acceptance
for every row still `Partial` or `TODO` at go-live.

Note also that the deterministic policy in `domain/` is BANK-OWNED logic: the tolerances, the fee
caps, the FX window, the ranking weights and the aging thresholds are a vendor default to be
examined and replaced, not inherited unexamined. Second-line review of those numbers is an
adoption step, not an optional one.

### Can we run it against real ledgers today?

Not without your own legal, security and model-risk sign-off. Every fixture, the demo feeds and
the golden set use invented counterparties and a documented synthetic national id that exists only
so the redaction check has an independent literal to find. The adoption checklist in
[`../ADOPTING.md`](../ADOPTING.md) section 6 lists the steps that must precede any live use:
your region, your IdP, your policy numbers, your PII jurisdictions, your data, your golden set,
and a review of the deploy posture.
