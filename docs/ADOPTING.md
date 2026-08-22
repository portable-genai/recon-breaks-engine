# Adopting this repo as your base

This repository (F1, the Reconciliation Breaks Engine) is a **common base** that a bank, a PSP or
another regulated institution forks to build its own **reconciliation and breaks service**: a
deterministic multi-pass matcher over two feeds, a ranked break worklist, and a drafted
maker-checker resolution per break that is routed to a human and never auto-posted. It ships a
reusable hexagonal core (a pure-stdlib domain, typed ports, three swappable adapter profiles, a
green offline gate) plus a fully worked reconciliation vertical you can keep, retune, or replace
with your own feed pairing.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the layout, the port table and the
> request pipeline), [`CONTRIBUTING.md`](../CONTRIBUTING.md) (the file-by-file touch list for a
> new adapter and a new port), [`COMPLIANCE.md`](../COMPLIANCE.md) (the principle and rule map),
> the [`faq/`](faq/) directory, and [`model-card.md`](model-card.md) for the model boundary.

---

## 1. What you keep vs what you rewrite

The core is hexagonal, and the boundary between reusable machinery and this reconciliation
vertical is a physical module split with an enforced dependency direction (practices-audit check
A7). `domain/kernel.py` owns the vertical-neutral contracts and imports nothing from
`recon_breaks_engine`, so you can import it without loading a line of matching logic;
`domain/models.py` holds only the F1 artifacts and imports `kernel`, never the reverse.

| Layer | Where | For a new vertical |
|---|---|---|
| **Kernel** (vertical-neutral) | `domain/kernel.py` (`Citation`, `AuditEvent`, `Severity`, `Decision`, `utcnow`, `TenantAccessDeniedError`, `authorize_tenant`), every Protocol in `ports/` including `ports/identity.py`, `worklist_access.py`, the container wiring in `config.py`, `managed_readiness.py` | keep untouched |
| **Policy** (your numbers) | `domain/policy.py`: `TolerancePolicy` (per-currency bps and absolute caps), `FeeSchedule`, `FxRateWindow` (fixed rates plus the drift window), `RankingPolicy` (age, amount-band, repeat and per-account criticality weights), `AgingPolicy` (escalation age and amount, the timing window, the many-to-one candidate cap). Also `JURISDICTIONS` in `domain/pii.py` and `THRESHOLDS` in `eval/run_eval.py` | change deliberately (see section 4) |
| **Vertical** (the reconciliation artifacts) | `domain/models.py` (`FeedSide`, `BreakType`, `FeedRow`, `CanonicalEntry`, `Match`, `Break`, `RankedBreak`, `BreakResolution`, `ReconRun`, `StoredWorklist`), `domain/normalise.py`, `domain/match_engine.py`, `domain/break_ranking.py`, `domain/resolution_service.py`, `domain/metrics_export.py`, the fixture feeds in `adapters/local/_recon_fixture.py`, the eval golden set, the UI views | rewrite or reseed for your feeds |

If your product is another *back-office reconciliation or exception-queue* service, most of the
hexagon transfers directly: the three profiles, the deterministic-decision pattern, the ranked
worklist, the tenant boundary, the eval gate and the Hrz7 review routing. You replace the feed
shape and the break taxonomy, and you retune the policy numbers.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): `domain/kernel.py`, every Protocol in `ports/`,
  `worklist_access.py`, the `Container` wiring in `config.py`, `managed_readiness.py`,
  `tests/contract/`, the eval harness mechanics in `eval/run_eval.py`, the demo mechanics in
  `scripts/`, the CI workflows, and the two UI security modules (`ui/lib/embed-policy.mjs`,
  `ui/lib/server/identity.ts`).
- **Adopter-owned** (yours; expect to edit): the *values* in `config/settings.yaml`, every number
  in `domain/policy.py`, `JURISDICTIONS` in `domain/pii.py`, the fixture feeds in
  `adapters/local/_recon_fixture.py` and `tests/fixtures/sample_cases.py`, `adapters/onprem/*`,
  the golden set in `eval/datasets/golden_cases.jsonl`, the tfvars values built from
  [`terraform.tfvars.example`](../infra/terraform/terraform.tfvars.example), UI theming, and the
  jurisdiction rows in `COMPLIANCE.md`.

Track upstream via git tags; rebase your adopter-owned changes onto each release rather than
merging `main` continuously, so conflicts stay in files you were told to expect.

## 3. The mechanical rebrand (one script)

[`scripts/rename_fork.py`](../scripts/rename_fork.py) rewrites the python package
(`recon_breaks_engine`), the console-script name (also `recon_breaks_engine`, since
`[project.scripts]` names the command after the package), the `RECONBREAKS` env-var prefix, the
Terraform `name_prefix` stem (`f1-svc`) and the distribution / git id
(`recon-breaks-engine`) across the tree. Every rule runs in ONE simultaneous pass, so no rule
can rewrite another rule's output. Preview first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_recon --cli acme-recon \
    --env-prefix ACME --resource acme-recon --dry-run

# Apply, sweeping Markdown prose as well:
python scripts/rename_fork.py --package acme_recon --cli acme-recon \
    --env-prefix ACME --resource acme-recon --include-docs --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
make docs-check
```

`--dist` defaults to the package name with underscores turned into hyphens (`acme-recon` above);
pass it explicitly if your git id follows a different convention, for example
`--dist acme-recon-breaks`. Without `--include-docs` the script leaves `.md` files alone, which
is the safer default when you only want the code renamed. `--dry-run` always wins over `--yes`.

`--resource` is validated here against the same pattern the Terraform variable validates at plan
time (`^[a-z][a-z0-9-]{2,18}$`, see [`infra/terraform/variables.tf`](../infra/terraform/variables.tf)),
so a bad stem fails in a second rather than at `terraform plan`.

The script deliberately does NOT touch the human decisions below.

## 4. The human decisions (the script cannot make these)

1. **Region and residency.** The region is chosen once and shared by the runtime and Terraform.
   Set `GCP_REGION` (read by `region:` in [`config/settings.yaml`](../config/settings.yaml)) and,
   in your tfvars, BOTH `region` and `allowed_regions` (the residency allowlist the region is
   validated against at plan time). The build defaults to `asia-southeast1` (MAS / Singapore),
   with the rendered defaults living in `infra/terraform/render.tf.json`. See
   [`runbook.md`](runbook.md).
2. **Identity and your IdP.** This repo owns no login flow. Under `gcp` the only adapter that
   declares itself VERIFIED is `adapters/gcp/identity.py`, which checks the IAP assertion against
   IAP's own key set, the configured `RECONBREAKS_IAP_AUDIENCE`, the expiry and the issuer; under
   `local` the seeded dev personas authenticate nobody and are offline-only; under `onprem` the
   adapter raises so you must wire your own. Configure IAP on the deployed service and set the
   audience, or implement the on-premises adapter against your issuer. The runbook's
   "The IAP audience" section is the operational half.
3. **The matching tolerances and the ranking weights.** These are the consequential numbers your
   finance-operations and second-line functions must own, and they all live in one frozen place,
   [`domain/policy.py`](../src/recon_breaks_engine/domain/policy.py):
   - `TolerancePolicy`: `per_currency_bps` / `default_bps` and `per_currency_abs_cap_minor` /
     `default_abs_cap_minor`. A pair passes tolerance when the difference is inside EITHER the
     bps allowance on the larger leg OR the absolute cap, whichever is larger.
   - `FeeSchedule.per_currency_max_fee_minor`: above this a same-currency difference is a FEE
     break rather than a fee-explained match.
   - `FxRateWindow.rates_scaled` and `window_bps`: the rates are deliberately fixed policy data,
     not a live feed, because a reconciliation must replay byte for byte. Refreshing them is a
     reviewed policy change, not a runtime lookup.
   - `RankingPolicy`: `age_weight`, `amount_band_weight`, `repeat_weight` and the per-account
     `account_criticality` bonus. All integers, because a float score would reorder the worklist
     on replay.
   - `AgingPolicy`: `escalate_age_days`, `escalate_amount_minor`, `timing_window_days` and
     `many_to_one_candidate_cap`. The first two are what decide whether a break opens a case.

   **Honest limitation.** `ReconPolicy` is a frozen dataclass and every engine takes it by
   injection, but there is no `policy:` block in `config/settings.yaml` yet: each surface
   constructs `ResolutionService(...)` without a `policy=` argument, so `ReconPolicy.default()`
   applies. Retuning today means constructing your own `ReconPolicy` and passing it at that one
   call site in `api/app.py`, `cli/main.py`, `agent/tools.py` and `eval/run_eval.py`. Wiring a
   settings block is the open practices-audit item B4. Whichever route you take, add a test that
   pins your numbers: the shipped values are an obviously-synthetic reference, not your policy.
4. **PII jurisdictions.** `JURISDICTIONS` in `domain/pii.py` selects and ORDERS the pattern rows
   from the shared `pii-kit` (national-ID rows first, universal email and phone rows last). The
   shipped tuple is `SG`, `HK`, `JP`, `AU`. Set the jurisdictions you actually serve, and keep the
   ordering rule in mind if you add a bare-digit account catch-all.
5. **Reference data is fictional.** The fixture feeds (`adapters/local/_recon_fixture.py`), the
   test fixtures and the golden set use invented counterparties and a documented synthetic
   national id that exists only so the redaction check has an independent literal to find.
   **Do not run against real ledgers or statements without your own security, legal and
   model-risk sign-off.**
6. **Eval golden set.** Rebuild [`eval/datasets/golden_cases.jsonl`](../eval/datasets/golden_cases.jsonl)
   for your feeds: a fork inherits a green gate that measures the WRONG reconciliation until you
   do. The harness structure and the four metrics (`match_accuracy`, `break_typing_accuracy`,
   `groundedness`, `pii_safety`) are generic; the expected matches and break types are yours. The
   Hrz4 bundle name in `eval/run_eval.py` is also renamed by the script, and registering it with
   Hrz4 is a separate step (see section 5).
7. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001,
   `HEALTHCHECK` on `/healthz`), the whole of `infra/terraform/` (the residency allowlist in
   `variables.tf`, the Org Policy guardrails in `org_policy.tf`, the regional CMEK ring in
   `kms.tf`, the dry-run-first perimeter in `vpc_sc.tf`, the locked WORM bucket in
   `logging_worm.tf`, the internal-load-balancer-only serving edge in `production_edge.tf`), and
   the loopback exposure guard before you expose anything. Note that the managed profile refuses
   to serve while any operation named in `managed_readiness.py` is still a placeholder, so a
   `gcp` deploy of an unmodified fork will fail its preflight on purpose.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it *touches* are
owned by sibling systems; integrate rather than rebuild them. The list below is what is actually
wired in this tree today, checked against `config/settings.yaml` and the R1 to R8 rows in
[`COMPLIANCE.md`](../COMPLIANCE.md), and it says plainly where a dependency is NOT wired.

| Concern | Owner | State in this repo |
|---|---|---|
| Human review and maker-checker console | **Hrz7** | **Wired.** `ports/review_router.py` with an adapter in all three families over the shared `review-kit`; the console base URL is `HRZ_HUMAN_REVIEW_URL`. Every escalation is routed in the same call that produced it (rule R8). |
| Escalation cases with an aging clock | **Hrz7** (case spine) | **Wired.** `ports/case_engine.py`; the managed adapter opens the case on Hrz7's `/v1/cases` and refuses when no console is configured. The BREACH decision is the engine's, made before the port is called. |
| AI-quality and promotion gate | **Hrz4** | **Client half wired.** `eval/run_eval.py --mode gate` uses the shared `PromotionGateClient` and refuses to run off the managed profile. Registering this repo's metric bundle and thresholds with Hrz4 is still open (P-08 / R5 in `COMPLIANCE.md`). |
| Tracing | **Hrz5** | **Wired by configuration.** `adapters/gcp/tracer.py` exports OTLP to the Hrz5 collector when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, and straight to Cloud Trace when it is not. |
| Shared immutable audit sink | **Hrz5** | **NOT wired.** The audit trail is local (hash-chained and anchored) or a locked Cloud Logging bucket. Binding the shared sink is the open R2 item. |
| Agent registry, identity and entitlements | **Hrz3** | **NOT wired.** The A2A card is published at `/.well-known/agent-card.json` and built from the same tool table the runtime binds, but nothing registers it. Open R4 item. |
| Runtime guardrail: prompt-injection defence and output filtering | **Hrz1** | **NOT wired.** There is no `GuardrailPort`. Redaction is in-repo through the shared `pii-kit`, which is not the same control. Open R1 item, and it becomes mandatory the moment untrusted text reaches a model. |
| Governed knowledge base and grounded retrieval | **Hrz2** | **Not applicable today.** This service reconciles feed rows and performs no retrieval, so there is nothing to ground. Adding a retrieval port makes Hrz2 mandatory (R3) together with P-05. |
| Project intake validation | **Rsk3** | An intake action, not a code control. Record the validation reference in `COMPLIANCE.md` when the project passes it (R6). |
| The downstream ops worklist view | **F5** (control room and handover), with **F2** conforming | This repo OWNS the export schema and F5 consumes it. Do not re-implement the queue view here; see [`ops-metrics-contract.md`](ops-metrics-contract.md) and `schema/ops_worklist_export.schema.json`. |

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make gate` and `make docs-check` green.
- [ ] Set `GCP_REGION` and the Terraform `region` plus `allowed_regions` to your in-country region.
- [ ] Wired your IdP: IAP configured on the service and `RECONBREAKS_IAP_AUDIENCE` set, or the on-premises identity adapter implemented against your issuer.
- [ ] Owned the tolerances, the fee schedule, the FX window, the ranking weights and the aging thresholds in `domain/policy.py` with your finance-operations and second-line functions, and pinned them with a test.
- [ ] Set `JURISDICTIONS` in `domain/pii.py` to the jurisdictions you actually serve.
- [ ] Replaced the fixture feeds and every synthetic fixture with your own synthetic data.
- [ ] Rebuilt the eval golden set for your feed pairing and re-reviewed the four thresholds.
- [ ] Reviewed the deploy posture (Dockerfile, the whole of `infra/terraform/`, the bind address) and read the managed-profile preflight in `managed_readiness.py`.
- [ ] Decided which sibling systems you integrate versus stub, and wired your Hrz7 endpoint.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
