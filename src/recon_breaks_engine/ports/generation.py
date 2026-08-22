"""GenerationPort: the ONLY seam a language model sits behind, and it narrates, never decides.

Every consequential value in this service (which entries reconcile, what kind of break the
residue is, how a break ranks, whether it escalates) is produced by the deterministic engine
BEFORE anything reaches this port. The model's whole job is to turn a set of engine-decided facts
into readable prose. It is handed a prompt built only from those facts, its output is redacted,
schema-validated and groundedness-checked, and it is DISCARDED on any failure in favour of a
deterministic engine-authored note. A model that invents a number here changes nothing a human
acts on, because the number a human acts on never came from the model.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class GenerationPort(Protocol):
    def draft(self, prompt: str) -> str:
        """Narrate prose from a prompt of engine facts. Returns text; never a number or verdict.

        The caller supplies a prompt assembled entirely from already-decided engine facts and is
        responsible for redaction before the call, and for validating and grounding the result
        after it. The port makes no promise about the truth of what it returns, which is exactly
        why the caller discards an ungrounded draft.
        """
        ...
