"""On-prem WorklistStorePort: fail-fast portability placeholder (the sovereign-exit proof, P-12)."""

from __future__ import annotations

from ...config import Settings
from ...domain.models import StoredWorklist


class OnPremWorklistStoreAdapter:
    """Satisfies WorklistStorePort but refuses: the client binds its own worklist store."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def list_for_tenant(self, tenant: str) -> tuple[StoredWorklist, ...]:
        raise NotImplementedError(
            "on-prem worklist store is a portability placeholder: bind the client's own store "
            "(see docs/onprem-migration.md)"
        )

    def get(self, worklist_id: str) -> StoredWorklist | None:
        raise NotImplementedError(
            "on-prem worklist store is a portability placeholder (see docs/onprem-migration.md)"
        )

    def put(self, worklist: StoredWorklist) -> str:
        raise NotImplementedError(
            "on-prem worklist store is a portability placeholder (see docs/onprem-migration.md)"
        )
