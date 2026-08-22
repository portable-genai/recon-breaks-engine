"""Tenant isolation on the worklist store: the two-method authorization contract, proven red.

``WorklistStorePort.list_for_tenant`` filters on tenant IN the store, so a listing can never span
tenants. ``get`` is a raw fetch the DOMAIN authorizes: ``worklist_access.read_worklist`` compares
the stored worklist's tenant to the verified principal's tenant and denies with 403, never a 404
that would hide whether an id is in use across the boundary. The "red without the check" proof is
explicit here: the raw ``get`` returns another tenant's worklist, and only the domain check turns
that into a refusal.
"""

from __future__ import annotations

from datetime import date

import pytest

from recon_breaks_engine.config import Container, Settings, build_container
from recon_breaks_engine.domain.kernel import TenantAccessDeniedError
from recon_breaks_engine.domain.models import StoredWorklist
from recon_breaks_engine.worklist_access import read_worklist


def _worklist(worklist_id: str, tenant: str) -> StoredWorklist:
    return StoredWorklist(
        worklist_id=worklist_id,
        tenant=tenant,
        feed_id="nostro:scheme",
        as_of=date(2026, 8, 8),
        ranked_breaks=(),
    )


def _container() -> Container:
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    container.worklist_store.put(_worklist("wl:alpha", "tenant-a"))
    container.worklist_store.put(_worklist("wl:beta", "tenant-b"))
    return container


def test_a_principal_reads_its_own_tenants_worklist() -> None:
    container = _container()
    worklist = read_worklist(container, "wl:alpha", principal_tenant="tenant-a")
    assert worklist is not None and worklist.worklist_id == "wl:alpha"


def test_a_cross_tenant_read_is_denied_403_not_404() -> None:
    container = _container()
    with pytest.raises(TenantAccessDeniedError) as excinfo:
        read_worklist(container, "wl:beta", principal_tenant="tenant-a")
    assert excinfo.value.http_status == 403


def test_a_missing_worklist_is_none_not_a_denial() -> None:
    """Absent and forbidden are different facts: a missing id is ``None`` (a later 404), and only
    an EXISTING id owned by another tenant is the 403."""
    container = _container()
    assert read_worklist(container, "wl:absent", principal_tenant="tenant-a") is None


def test_the_raw_store_get_leaks_without_the_domain_check() -> None:
    """The mutant: bypassing ``read_worklist`` and calling the raw ``get`` returns the other
    tenant's worklist. That leak is exactly what the domain authorization prevents, so the guard
    can go red."""
    container = _container()
    leaked = container.worklist_store.get("wl:beta")
    assert leaked is not None and leaked.tenant == "tenant-b"


def test_list_for_tenant_filters_on_tenant_in_the_store() -> None:
    container = _container()
    a_ids = {wl.worklist_id for wl in container.worklist_store.list_for_tenant("tenant-a")}
    b_ids = {wl.worklist_id for wl in container.worklist_store.list_for_tenant("tenant-b")}
    assert a_ids == {"wl:alpha"}
    assert b_ids == {"wl:beta"}
