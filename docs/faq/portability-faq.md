# Portability FAQ

For architecture, cloud and exit-planning reviewers who want to know how real the "no lock-in"
claim is, and how an off-cloud or sovereign exit would actually work.

## What is the no-lock-in claim, concretely?

`src/recon_breaks_engine/domain/` is pure standard library plus the stdlib-only commons packages.
No FastAPI, no cloud SDK, no HTTP client, no pydantic. Every boundary is a `@runtime_checkable`
`Protocol` in `ports/`, and the whole adapter stack is selected by one environment variable.
`tests/unit/test_core_purity.py` is the standing gate on the domain's import set, so the claim is
enforced rather than described.

There are nine ports, all re-exported once from `ports/__init__.py` with the `PORT_PROTOCOLS`
map: `audit`, `identity`, `review_router`, `feeds`, `generation`, `case_engine`,
`worklist_store`, `tracer` and `evaluation`. `IdentityPort`, `ObservabilityTracerPort` and
`EvaluationGatePort` are re-exported from the commons rather than redeclared, because a Protocol
copied into N repositories is N Protocols and only one of them gets fixed when a defect is found.

## What are the three profiles?

`RECONBREAKS_PROFILE` selects the whole adapter stack from the `adapters:` block in
`config/settings.yaml`, which is the only place a binding lives:

- **`local`**: a real, working, SDK-free offline stack. Fixture feeds, a deterministic
  digit-free narrator, an in-memory tenant-scoped worklist store, the commons hash-chained WORM
  audit log with an external head anchor, seeded dev personas, and a review-kit outbox that is
  deliberately not a no-op. This is the dev, test and CI default and the working proof that the
  domain runs entirely off-cloud.
- **`gcp`**: the managed stack. BigQuery feeds and worklist store, a managed generation surface,
  Cloud Logging WORM audit, IAP identity, OpenTelemetry tracing, the Hrz4 promotion client and
  the Hrz7 review and case submissions. Every cloud import is LAZY, inside the method, so the
  other two profiles import this tree with no cloud SDK installed.
- **`onprem`**: fail-fast placeholders that satisfy the same Protocols and RAISE. That is the
  reversibility proof (P-12): a placeholder that returned quietly would make the portability
  claim silently false.

Three states, not two. UNSET is NO CHOICE rather than a silent `local`; SET-AND-EMPTY raises;
SET-AND-UNKNOWN raises, `Local` and `GCP` included. Both raises happen at import, so a process
fails to boot rather than serving on a posture nobody chose, and only `config.py` may read the
variable (`tests/unit/test_profile_single_source.py`).

## Is the portability claim tested, or just asserted?

Tested, and bounded. `make portability` runs eight named checks and exits non-zero on any
failure: port map complete, adapters construct and conform, the offline family ANSWERS, the exit
family REFUSES, an in-place rewrite is detected, truncation is detected when anchored, the record
leaves this codebase intact (JSON Lines export and foreign reload), and no cloud SDK was
imported. It prints its own bound at the end: offline seams and record portability only.

The contract suite is the other half. `tests/contract/test_port_parity.py` asserts set equality
across ALL FIVE homes of a port (the `PORT_PROTOCOLS` map, `config.DEFAULT_BINDINGS`, a
`Container` accessor, `config/settings.yaml` and `tests/contract/canonical.py`), so a port that is
bound but unregistered cannot run untested. `tests/contract/test_behavioral_parity.py` proves the
offline family answers, the exit family raises and the managed family refuses rather than
silently succeeding. The no-SDK claim is proved by BLOCKING the import in a fresh interpreter
(`tests/contract/_sdk_free_probe.py`), not by the SDK happening to be absent.

## How would a sovereign or on-premises exit actually go?

The `onprem` profile is the scaffold, and each placeholder marks a seam where a client supplies
their own component: their feed warehouse, their model host, their worklist store, their IdP,
their WORM store, their maker-checker queue and their case system. The domain never changes, so
the exit is an adapter exercise rather than a rewrite. The step-by-step is
[`../onprem-migration.md`](../onprem-migration.md).

Two seams deserve a note:

- **Identity.** The on-premises identity placeholder refuses with a STATUS and a REASON rather
  than a bare crash, and a replacement must set `end_user_auth = VERIFIED` on the new class. That
  declaration is what tells the exposure guard the end-user routes are authenticated; an adapter
  that omits it is read as client-asserted, which is the fail-closed default.
- **Review routing.** Rule R8 does not relax on exit. The placeholder RAISES rather than
  returning quietly, because an adapter that dropped the escalation would leave the service
  auto-executing with the appearance of review.

## Can the data be exported in an open format?

Yes. The audit trail exports to and restores from JSON Lines with the hash chain intact, which is
what the "record leaves intact" portability check proves: the exit is a file copy plus a reload,
not a migration project. The ranked worklist has a second open surface, the versioned
ops-worklist metrics export defined by `schema/ops_worklist_export.schema.json` and
[`../ops-metrics-contract.md`](../ops-metrics-contract.md), pinned at
`ops-worklist-export/v1`.

## How is data residency handled?

The region is chosen once and shared by the runtime and Terraform. In the application it is
`region:` in `config/settings.yaml` (`GCP_REGION`, default `asia-southeast1`), reported by
`/healthz` and printed on the agent card so a drifting deployment is visible. At deploy time
`infra/terraform/variables.tf` validates the effective region against an allowlist at PLAN time,
`org_policy.tf` pins `constraints/gcp.resourceLocations` to the selected region's location group,
`kms.tf` creates a REGIONAL CMEK key ring (never a multi-region one), `logging_worm.tf` creates
the WORM audit bucket in the same region, and `vpc_sc.tf` stands up a dry-run-first VPC Service
Controls perimeter. Moving to a second in-country region is a tfvars change, not a fork.

## What is honestly NOT portable, and what is not finished?

- **The managed profile does not serve yet.** `managed_readiness.py` lists the operations that
  are still construction-only placeholders (the BigQuery feed fetch, the managed generation draft
  and all three worklist-store methods), and the API preflight REFUSES to start a `gcp` or
  `platform` process while any of them is active. That is deliberate: a Cloud Run service must
  not become healthy while an operation on its primary journey is a placeholder.
- **Tamper evidence is scoped to what the local sink can prove.** `portability_demo.py` says so
  explicitly. Production tamper evidence is the locked Cloud Logging bucket's job, or Hrz5's.
- **The shared audit sink is not bound.** Traces can reach the Hrz5 collector by setting
  `OTEL_EXPORTER_OTLP_ENDPOINT`; the audit stream cannot yet. See the R2 row in
  [`../../COMPLIANCE.md`](../../COMPLIANCE.md).
- **The Terraform posture has no test in the offline gate.** `infra/terraform/production_edge.tftest.hcl`
  encodes the residency and fail-closed claims as executable `terraform test` runs, but nothing in
  `make gate` or in the workflows runs it today, so those claims are asserted in Terraform rather
  than guarded by a build.
