"""Read a stored worklist, authorizing the tenant in the DOMAIN, not in the store.

``WorklistStorePort.get`` is a raw fetch by id that does not filter on tenant; the authorization
lives HERE, against the VERIFIED principal's tenant, so every driving adapter (API, CLI, agent)
inherits the same boundary and no store adapter becomes the only place it is enforced. A worklist
belonging to another tenant raises :class:`TenantAccessDeniedError` (HTTP 403), never a 404 that
would hide whether the id is in use across the boundary. A worklist that simply does not exist is
``None`` (the caller answers 404); the two are different facts and are kept apart on purpose.
"""

from __future__ import annotations

from .config import Container
from .domain.kernel import authorize_tenant
from .domain.models import StoredWorklist


def read_worklist(
    container: Container, worklist_id: str, *, principal_tenant: str
) -> StoredWorklist | None:
    """Fetch one stored worklist, or ``None`` if absent; deny a cross-tenant read with 403.

    ``principal_tenant`` is the tenant the IdentityPort verified for this request; it is never a
    value the client asserted. The store fetch is raw and the tenant comparison is the domain's,
    so the boundary holds no matter which store adapter is bound.
    """
    worklist = container.worklist_store.get(worklist_id)
    if worklist is None:
        return None
    authorize_tenant(worklist.tenant, principal_tenant)
    return worklist
