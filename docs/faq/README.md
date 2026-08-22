# FAQ index

Answers to the questions different teams ask when evaluating, adopting, or reviewing this
repository as a common base for a reconciliation and breaks engine. Each file is written for a
specific audience; skim the one that matches your role.

| FAQ | For | Answers |
|---|---|---|
| [security-faq.md](security-faq.md) | AppSec / security review | what the service processes, server-side identity, the tenant boundary, the PII posture, secrets, supply chain, the audit chain and its honest limits |
| [portability-faq.md](portability-faq.md) | Architecture / cloud / exit planning | the no-lock-in claim, the three profiles, how a sovereign exit actually goes, residency, open-format export |
| [features-faq.md](features-faq.md) | Product / finance operations / delivery | what the engine produces, which passes run in what order, what is deterministic versus drafted, and the boundary with sibling systems |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | the rebrand, upstream fixes, extension points, retuning the policy numbers, whether the demo rots |
| [compliance-faq.md](compliance-faq.md) | Compliance / operational risk / model risk | maker-checker, auditability, residency enforcement, the model-risk story, what is still open |

These FAQs deliberately do **not** re-document capabilities owned by sibling systems in the
catalog. Where a concern belongs to another repo (the guardrail gateway, the human-review
console, the eval platform, the agent registry, the control-room worklist view), the FAQ points
at it by catalog id and explains the boundary rather than duplicating it. See
[features-faq.md](features-faq.md) for the full "what this repo owns versus what it integrates"
map, and [`../ADOPTING.md`](../ADOPTING.md) for the same map from a fork's point of view.
