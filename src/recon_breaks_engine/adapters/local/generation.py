"""Local GenerationPort: a deterministic, grounded narrator, SDK-free, for the offline profile.

It stands in for a managed LLM without one. The point of the port is that a model may only
NARRATE, so the offline adapter narrates deterministically: it reads the break type out of the
prompt facts and returns a fixed, number-free sentence for it. Carrying no digits at all, its
output always passes the caller's groundedness check, which is the correct behaviour for a
narrator that invents nothing. The caller (``ResolutionService``) is what enforces grounding on
ANY generation adapter, managed or local, so swapping in a real model changes only the prose, not
the guarantee.
"""

from __future__ import annotations

from hex_service_kit import provenance

from ...config import OFFLINE_STUB_MODEL, Settings

_BY_TYPE: dict[str, str] = {
    "timing": "The two feeds appear to record the same item on different value dates.",
    "missing": "One feed carries this item with no counterpart on the other feed.",
    "duplicate": "One feed appears to record this item more than once.",
    "fx": "A cross-currency counterpart exists but converts outside the accepted rate window.",
    "fee": "A same-currency counterpart exists but differs by more than the fee schedule allows.",
}
_FALLBACK = "The two feeds disagree on this item and it needs analyst confirmation."


class LocalGenerationAdapter:
    """Narrate a break in one deterministic, digit-free sentence keyed off its type."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, prompt: str) -> str:
        break_type = ""
        for line in prompt.splitlines():
            if line.startswith("break_type:"):
                break_type = line.split(":", 1)[1].strip()
                break
        # What answered this narration, for the console's model pill: the same name
        # `generator_model` reports under this binding, so the configured and answered pills agree.
        provenance.note_model(OFFLINE_STUB_MODEL)
        return _BY_TYPE.get(break_type, _FALLBACK)
