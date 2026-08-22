"""On-prem GenerationPort: fail-fast portability placeholder (the sovereign-exit proof, P-12)."""

from __future__ import annotations

from ...config import Settings


class OnPremGenerationAdapter:
    """Satisfies GenerationPort but refuses at call time: the client wires its own model."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, prompt: str) -> str:
        raise NotImplementedError(
            "on-prem generation adapter is a portability placeholder: bind the client's own "
            "model host (see docs/onprem-migration.md)"
        )
