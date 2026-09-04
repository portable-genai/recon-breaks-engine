# Security FAQ

For an AppSec reviewer sizing up this repo. It explains what the attack surface is, what is
deliberately out of scope (and why that is honest rather than a gap), and where the evidence
lives. Where a control is not implemented, this file says so.

## What does this system actually process?

Two named feed sets of raw, cited financial rows: an entry id, a decimal amount string, a
currency, a value date string, a reference, a counterparty and an account, each carrying a
`Citation` naming the feed and line it came from (`domain/models.py::FeedRow`). It reconciles
them and produces reconciled groups, typed breaks, a ranked break worklist and one drafted
maker-checker resolution per break. It never posts a journal: there is no posting port in the
tree at all.

The counterparty and account strings are the part a reviewer should care about. They can carry
identifying text, which is why redaction is not optional here.

## How is PII handled? What exactly is redacted, and when?

Redaction runs before anything leaves the process, using the shared `pii-kit` with a
jurisdiction selection this deployment owns (`domain/pii.py`; the shipped tuple is `SG`, `HK`,
`JP`, `AU`, with national-ID rows ordered before the universal email and phone rows).

Three boundaries are covered, in `domain/resolution_service.py` and around it:

- the model prompt: the drafted hypothesis is redacted immediately after the generation call and
  before it is used;
- the review payload: `adapters/_review_payload.py` redacts before the wire, against every
  jurisdiction's rows because the review console is a shared sink;
- the audit write: the `AuditEvent` carries only `redacted_summary`, and the summary and the
  subject are both passed through `redact(...)` when the resolution is built.

Agent tool results are masked as well (`agent/tools.py`), because a tool result becomes a model's
context. The API response is deliberately not masked in the same way: it answers an authenticated
end user, and principle P-04 is about what reaches a model.

`tests/unit/test_not_falsely_green.py` proves the `pii_safety` metric can go RED, which is what
stops the redaction claim from being a metric that always reads 1.0.

## How is identity handled? Can a caller spoof the actor?

No. Identity is resolved server-side on every route. `api/schemas.py::ReconcileRequest` carries
no `actor` field, and `api/app.py::get_principal` builds a `RequestContext` from headers and
resolves a verified `Principal` through the bound `IdentityPort`. The verified principal is the
audit actor and the review maker; a client-supplied value never becomes either.

The three families differ, and each declares what it can do:

- `local`: seeded dev personas, an UNAUTHENTICATED grant, offline only. The adapter refuses to
  construct unless `RECONBREAKS_PROFILE` was set to `local` DELIBERATELY, so a deployment that
  simply lost the variable cannot hand out an approver persona.
- `gcp`: `adapters/gcp/identity.py` verifies the IAP assertion against IAP's own key set, the
  configured `RECONBREAKS_IAP_AUDIENCE` (unset or emptied REFUSES, because `audience=None` means
  the audience is not verified at all), the expiry and the issuer, which `verify_token` does not
  check for you. `tests/unit/test_iap_identity.py` runs in every gate, and
  `tests/unit/test_iap_crypto_matrix.py` runs the real verifier over locally minted assertions in
  its own CI job that fails if it skips.
- `onprem`: raises rather than pretending.

## What stops the service serving an unauthenticated posture on a network?

An exposure guard bound at MODULE scope in `api/app.py`, because the Dockerfile `CMD` and
`make run-api` serve the app OBJECT and a bound that lived only in `main()` would never run in a
shipped process (`tests/unit/test_serving_path_exposure.py`). Its posture is derived from the
identity BINDING and from nothing else: the adapter declares `VERIFIED`, `CLIENT_ASSERTED` or
`UNIMPLEMENTED` in `ports/identity.py`, and silence reads as client-asserted.

A service credential may never enter that decision. `tests/unit/test_end_user_auth_posture.py`
walks the guard's argument through the constants it names and fails the build if
`RECONBREAKS_S2S_TOKEN` reappears at any depth, because setting a token that authenticates a
calling SERVICE must not stand the guard down for END-USER routes.

Related: `/docs`, `/redoc` and `/openapi.json` are registered only when the exposure profile is
the deliberate `local`. Under `gcp` they are ABSENT rather than guarded, because a guard the
profile has switched off is no guard.

## Is there object-level authorisation, or only a tenant field?

There is a real boundary and it lives in the domain. `WorklistStorePort.list_for_tenant` filters
on tenant IN THE STORE, so a listing can never span tenants; `get` is a raw fetch that
`worklist_access.read_worklist` authorizes against the VERIFIED principal's tenant. A worklist
owned by another tenant is a **403, never a 404**, because a 404 would leak whether an id is in
use across the boundary (`domain/kernel.py::authorize_tenant`).
`tests/unit/test_worklist_store_authz.py` proves the raw `get` leaks without the domain check, so
the guard can go red rather than passing vacuously.

## What about outbound service-to-service calls?

The routed review and the escalation case both go to `human-review-console`. The managed review router submits over
the shared `review-kit` with the OUTBOUND credentials `HUMAN_REVIEW_S2S_TOKEN` and
`HUMAN_REVIEW_S2S_SIGNING_KEY`, deliberately distinct variables from this service's own INBOUND
`RECONBREAKS_S2S_TOKEN`. The kit refuses a plaintext non-loopback URL and a missing bearer at
construction, and the managed router REFUSES when no console is configured rather than swallowing
the escalation.

## Are there secrets in the repo?

No secret value. `config/settings.yaml` holds environment variable NAMES and non-secret defaults
only; `.env.example` documents the non-secret variables and `.env.secrets.example` documents the
secret NAMES with placeholders; `.gitignore` excludes the real files. Every security-relevant read
resolves three states, and `tests/unit/test_three_state_env_reads.py` walks the AST of `src/`,
`scripts/` and `eval/` and fails the build on any two-state read that ships. The UI half is
scanned by `ui/tests/three-state-env-reads.test.mjs` for the same rule.

## What is the supply-chain posture?

Two committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`) installed with
`--no-deps` by `make install`, CI and the Dockerfile, with the catalog commons pinned to
40-character commit shas rather than tags; a digest-pinned, multi-stage, non-root
(uid 10001) image with a `HEALTHCHECK`; SHA-pinned GitHub Actions; dependabot per ecosystem; and
`pip-audit` over both locks plus `npm audit --audit-level=high` as HARD CI failures.
`tests/unit/test_repo_artifacts.py` asserts each of these from inside the repo, so the claim is
checked rather than described.

## Is the audit trail tamper-evident?

Yes, within stated limits. The offline sink is the commons hash-chained WORM log AND an external
head anchor: `audit_anchor_path` (`RECONBREAKS_AUDIT_ANCHOR`) writes the chain head to a file that
should live on a different volume under different credentials. The chain alone catches an in-place
edit, an interior deletion and a reorder; only the anchor catches a TRUNCATED TAIL, because a
truncated chain still verifies perfectly. `tests/unit/test_audit_anchor.py` proves the detection,
proves the control case goes undetected without an anchor, and proves an append after truncation
refuses rather than re-anchoring.

The anchor defaults to empty, which is correct for the ephemeral `:memory:` store and WRONG for a
durable one. Set it when you set a durable `RECONBREAKS_AUDIT_PATH`. Operating rules are in
[`../runbook.md`](../runbook.md).

## What is explicitly out of scope for this repo?

- The runtime guardrail: prompt-injection defence and output filtering. That is `agent-guardrail-gateway`, and it
  is **not wired here**: there is no `GuardrailPort` in `ports/`. In-repo redaction is not the
  same control. This is the open R1 item in [`../../COMPLIANCE.md`](../../COMPLIANCE.md).
- The governed knowledge base (`enterprise-knowledge-base`). Not applicable today: this service performs no
  retrieval.
- Agent registration, identity and entitlements (`agent-registry`). The A2A card is published at
  `/.well-known/agent-card.json`, but nothing registers it. Open R4 item.
- The shared immutable audit sink and the trace store (`agent-observability`). Tracing exports OTLP to the `agent-observability`
  collector when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; the audit sink is local or a locked Cloud
  Logging bucket, not the shared sink. Open R2 item.
- The human-review console itself (`human-review-console`). This repo routes to it; it does not implement it.

See [features-faq.md](features-faq.md) for the full boundary map and
[compliance-faq.md](compliance-faq.md) for what that means for a control assessment.
