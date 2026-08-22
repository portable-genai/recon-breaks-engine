"""WorklistStorePort: the tenant-scoped store of ranked break worklists (plan slice 5).

Authorization contract (fail-closed, server-verified), the two-method shape the fleet's
tenant-scoped stores share: :meth:`list_for_tenant` takes the tenant and MUST filter on it in the
store, so a query can never span tenants; :meth:`get` is a raw fetch by id that does NOT filter,
and the caller (the domain, :func:`recon_breaks_engine.worklist_access.read_worklist`) compares
the stored worklist's tenant to the VERIFIED principal's tenant and denies with 403, not 404.
Keeping the check in the domain means every driving adapter inherits it and no store adapter can
become the only place the boundary is enforced. Never pass a client-supplied tenant into either
method: the tenant comes from the principal the IdentityPort verified.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import StoredWorklist


@runtime_checkable
class WorklistStorePort(Protocol):
    def list_for_tenant(self, tenant: str) -> tuple[StoredWorklist, ...]:
        """Return the worklists ``tenant`` holds (store-side tenant filter)."""
        ...

    def get(self, worklist_id: str) -> StoredWorklist | None:
        """Return one worklist by id, or ``None``; the DOMAIN authorizes the tenant, not this."""
        ...

    def put(self, worklist: StoredWorklist) -> str:
        """Upsert one worklist and return its id."""
        ...
