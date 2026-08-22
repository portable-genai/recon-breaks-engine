"""Managed GenerationPort: narrate over a managed model (SDK imported LAZILY).

The model import lives inside :meth:`draft`, so this module imports with no cloud SDK present.
Offline the lazy import fails first, which is the honest refusal: the caller then has no draft to
ground and falls back to the deterministic engine-authored note, exactly as it would on any
model failure.
"""

from __future__ import annotations

from ...config import Settings


class CloudGenerationAdapter:
    """Draft a narration from a managed model. Narrates only; never a number or a verdict."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, prompt: str) -> str:
        import google.generativeai as genai  # noqa: F401  (lazy: managed edge is real)

        raise RuntimeError(
            "the managed generation adapter needs a configured model endpoint; wire it in the "
            "deployment (see docs/runbook.md)"
        )
