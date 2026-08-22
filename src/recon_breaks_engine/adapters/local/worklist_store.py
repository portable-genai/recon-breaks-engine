"""Local WorklistStorePort: an in-memory, tenant-scoped worklist store (SDK-free).

Honours the two-method authorization contract: :meth:`list_for_tenant` filters on tenant in the
store, and :meth:`get` is a raw fetch the DOMAIN authorizes. The store is per-process, which is
right for the offline gate and the demo; a durable managed store arrives with the gcp adapter.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import StoredWorklist


class LocalWorklistStoreAdapter:
    """A dict-backed tenant-scoped worklist store for the ``local`` profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._by_id: dict[str, StoredWorklist] = {}

    def list_for_tenant(self, tenant: str) -> tuple[StoredWorklist, ...]:
        # Store-side tenant filter: a query can never span tenants.
        return tuple(wl for wl in self._by_id.values() if wl.tenant == tenant)

    def get(self, worklist_id: str) -> StoredWorklist | None:
        # Raw fetch by id; the DOMAIN compares tenants and denies with 403 (see kernel).
        return self._by_id.get(worklist_id)

    def put(self, worklist: StoredWorklist) -> str:
        self._by_id[worklist.worklist_id] = worklist
        return worklist.worklist_id
