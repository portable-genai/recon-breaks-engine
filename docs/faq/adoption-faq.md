# Adoption FAQ

For an engineering lead forking this repo as their institution's reconciliation base. The
step-by-step is [`../ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?"
questions.

### How do I rebrand it for my organisation?

`scripts/rename_fork.py` rewrites the python package (`recon_breaks_engine`), the console-script
name (also `recon_breaks_engine`, because `[project.scripts]` names the command after the
package), the `RECONBREAKS` env prefix, the Terraform `name_prefix` stem (`f1-svc`) and the
distribution id (`recon-breaks-engine`) in one pass. Preview with `--dry-run`, apply with
`--yes`, add `--include-docs` to sweep Markdown prose too. Then recreate the venv, `make install`,
`make gate` and `make docs-check`.

Every rule runs in ONE simultaneous alternation so no rule can rewrite another rule's output.
That matters here specifically: the CLI name and the package name are the SAME token upstream, so
a sequential search and replace would rename the command twice. The CLI rules therefore match
only the two places a command NAME appears, and the package rule takes every other occurrence,
including the `from recon_breaks_engine import (...)` in `scripts/portability_demo.py` that a
naive "command followed by a word" rule would have mangled.

The script is deliberately not a `make` target: a rebrand is a one-time act, not something to run
by reflex. It does the mechanical rename only; the human decisions (region, IdP, the tolerances
and ranking weights, the fixtures, the eval golden set) are the checklist in `ADOPTING.md`.

### If several institutions fork this, how does each take upstream fixes?

Track upstream via git tags. The repo declares a core-versus-adopter-owned boundary
([`../ADOPTING.md`](../ADOPTING.md) section 2): upstream owns `domain/kernel.py`, `ports/`,
`worklist_access.py`, the container wiring, `tests/contract/`, the eval harness mechanics, the
demo mechanics and CI; you own the `config/settings.yaml` values, every number in
`domain/policy.py`, the PII jurisdictions, the fixture feeds, `adapters/onprem/*`, the eval golden
set, your tfvars and the jurisdiction rows in `COMPLIANCE.md`. Rebase your adopter-owned changes
onto each release rather than merging `main` continuously, so conflicts stay in files you were
told to expect.

### Is there a separate kernel module I keep untouched?

Yes, and the split is physical rather than described. `domain/kernel.py` holds the
vertical-neutral machinery (`Citation`, `AuditEvent`, `Severity`, `Decision`, `utcnow`, the tenant
boundary types) and imports nothing from this package; `domain/models.py` holds only the F1
artifacts and imports `kernel`, never the reverse. A fork building a different back-office
vertical rewrites `models.py` and the engines around it and leaves `kernel.py` alone. That is
practices-audit check A7, and it is a PASS here.

### Can I retune the matching tolerances and the ranking weights without touching engine code?

Partly today, and here is the honest shape of it. Every tunable is already a field on a FROZEN
dataclass in `domain/policy.py` rather than a magic constant buried in an engine, and the
matcher, the ranker and the aging clock all take `ReconPolicy` by INJECTION. So retuning never
means editing an engine.

What is missing is the settings block. There is no `policy:` section in `config/settings.yaml`,
and each surface constructs `ResolutionService(...)` without a `policy=` argument, so
`ReconPolicy.default()` applies everywhere. Retuning today means building your own `ReconPolicy`
and passing it at those call sites: `api/app.py`, `cli/main.py`, `agent/tools.py` and
`eval/run_eval.py`. Wiring a validated `policy:` block is the open practices-audit item B4. If
your finance or second-line function must own these numbers as reviewable configuration rather
than as code, plan that small addition as part of adoption, and add a test that pins your values
either way.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list and the contract test enforces it. A port must be registered in FIVE
places or it runs with no enforcement at all: `ports/__init__.py` (`PORT_PROTOCOLS`),
`config.DEFAULT_BINDINGS`, a `Container` accessor, `config/settings.yaml`, and a `PortCase` in
`tests/contract/canonical.py`. Then bind it in all three families.
`tests/contract/test_port_parity.py` asserts set equality across all five, in both directions, so
a binding with no Protocol entry fails loudly rather than quietly. The full walkthrough is in
[`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How do I add a new adapter?

The class under `adapters/<family>/` with one constructor shape, `Adapter(settings)`, and any
cloud import INSIDE the method; the same `module:Class` target in both `config.DEFAULT_BINDINGS`
and `config/settings.yaml` (`tests/unit/test_settings_file.py` fails if the two disagree); and any
new variable documented in `.env.example`. If it is a managed adapter that is still a placeholder,
add it to `INCOMPLETE_MANAGED_OPERATIONS` in `managed_readiness.py` so a `gcp` process refuses to
serve until it is real and integration-tested.

### How do I change the break taxonomy?

`BreakType` and `FeedSide` are `LenientStrEnum` vocabularies from the shared commons, so a member
IS its wire value and an unknown value from a future release does not crash the reader. Adding a
break type means the enum member, the classification branch in `domain/match_engine.py`, the
deterministic hypothesis line in `domain/resolution_service.py`, the offline narrator's phrase
table in `adapters/local/generation.py`, and a golden case that exercises it.

### Will the demo rot after I diverge?

It is guarded, and the guard is inside the gate. A step lives in `demo.STEPS` AND in
`walkthrough.CHECKS`, and `tests/unit/test_demo_surface.py` holds the two sets equal, so a claim
the demo makes but nobody verifies cannot exist. That same test drives the whole arc through the
REAL local adapters inside `make gate`, asserts the tamper step actually goes RED (a demo with no
failing panel is a sales deck), and asserts the demo surface imports no cloud SDK in a FRESH
interpreter. `make demo-selftest`, `make portability`, `make demo-static` and `make docs-check`
run in the demo-gate workflow on every push.

Keep the pattern when you extend it: put the numbers a check reads in the step's `facts` dict,
never only in the rendered rows, because a check that parses prose breaks on a wording change.

### Does the offline gate run for my fork out of the box?

Yes. `make gate` is `ruff check` plus `ruff format --check` plus `mypy src` plus
`pytest -m 'not integration'` plus the eval, and it needs no network, no cloud SDK, no project and
no credentials. The workflows reference no organisation secrets. `tests/unit/test_test_layout.py`
fails the build if a module in `tests/integration/` is not marked, if a test module sits outside
one of the four suites, or if the gate stops deselecting the integration marker, which is what
keeps the gate offline as the repo grows.

Two things a fork should expect. The eval measures the REFERENCE feeds and golden cases until you
rebuild them, which is an explicit adoption step rather than a silent pass. And GitHub Actions may
be disabled in your organisation, in which case `make gate` locally is your only gate: run it
before every commit rather than waiting for a CI tick that will not arrive.

### What is genuinely unfinished, so I can plan around it?

- The **managed profile does not serve**. `managed_readiness.py` names the BigQuery feed fetch,
  the managed generation draft and all three worklist-store methods as construction-only, and the
  API preflight refuses to start a `gcp` process while any of them is active.
- The **`ui/` console is not wired to this vertical**. Its security boundary is complete and
  tested, but the page still calls the template's `/v1/triage` route, which this service does not
  serve. Point it at `/v1/reconcile` and build the worklist views.
- **Hrz1, Hrz2, Hrz3 and the shared Hrz5 audit sink are not bound.** See the R1 to R5 rows in
  [`../../COMPLIANCE.md`](../../COMPLIANCE.md) and the boundary table in
  [features-faq.md](features-faq.md).
- **No `policy:` settings block** yet (item B4 above).
- **Nothing runs the Terraform tests.** `infra/terraform/production_edge.tftest.hcl` is a real,
  credential-free `terraform test` suite, but no `make` target and no workflow invokes it.
