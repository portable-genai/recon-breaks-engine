# Ops worklist metrics contract

This document and [`schema/ops_worklist_export.schema.json`](../schema/ops_worklist_export.schema.json)
define the one cross-repo surface of the back-office STP wave: the ops-worklist metrics F1
(this engine) emits per reconciliation run, F2 (disputes and chargebacks) conforms to, and F5
(the control room and handover) consumes.

It is a DATA CONTRACT, not a shared package. The payload is warehouse schema rather than an
identical code layer, so the polyrepo packaging rule does not apply: F1 owns the schema, F2 and
F5 pin it, and each side carries a drift guard so a change on one side that the other has not
adopted fails a build rather than silently mis-reading a field.

## Ownership and versioning

- **F1 owns the schema.** The JSON Schema file is the source of truth; this document is its
  human-readable companion.
- **The version is a string, pinned exactly.** `schema_version` is `ops-worklist-export/v1`. A
  consumer pins that exact value. A breaking change (a removed or retyped field) bumps the
  version; an additive, optional field does not.
- **Every number is engine-computed.** A producer never lets a model author a field here, and a
  consumer never recomputes one. The export is a pure function of an already-computed run.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string const | `ops-worklist-export/v1`. The drift-guard pin. |
| `feed_id` | string | The feed pairing this worklist belongs to. |
| `as_of` | date | The explicit instant the run was computed against. A replay reproduces it. |
| `queue_depth` | integer | Count of unreconciled breaks in the worklist. |
| `throughput` | integer | Count of groups the matcher reconciled this run. |
| `aging_buckets` | object | Break counts by age band: `d0_1`, `d2_3`, `d4_7`, `d8_plus`. |
| `sla_clock_state` | object | `breached` versus `within` the aging SLA, plus `escalate_age_days`. |

Aging bands are inclusive of their upper bound in days; `d8_plus` is open-ended. The SLA split
uses the same `escalate_age_days` threshold the engine escalates on, so the control room and the
engine can never disagree about whether a break has breached.

## Producing and consuming

- **Produce (F1, F2):** call `domain.metrics_export.build_worklist_export(run, feed_id=...,
  as_of=..., aging=...)`. It returns a dict that validates against the schema. A producer test
  asserts schema validity at 1.0.
- **Consume (F5):** validate the payload against the pinned schema before reading it, and reject
  a `schema_version` that is not the pinned value. F5's coverage is deliberately bounded to the
  F1 and F2 feeds that exist; a later feed joins as configuration, not code.
