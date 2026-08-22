"""Managed WorklistStorePort: the tenant-scoped worklist store on BigQuery (SDK imported LAZILY).

The ``google.cloud.bigquery`` import lives inside each method, so this module imports with no
cloud SDK present (the offline profiles and the SDK-free gate depend on that). Offline, or with no
project reachable, the lazy import is the first thing to fail, which is the honest managed refusal:
never a silent empty result standing in for a stored worklist. The tenant filter on
:meth:`list_for_tenant` is applied in the warehouse query, never after the fact.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import StoredWorklist


class CloudWorklistStoreAdapter:
    """Tenant-scoped worklist store on BigQuery (lazy SDK import; store-side tenant filter)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def list_for_tenant(self, tenant: str) -> tuple[StoredWorklist, ...]:
        from google.cloud import bigquery  # noqa: F401  (lazy: proves the managed edge is real)

        raise RuntimeError(
            "the managed worklist store needs a configured BigQuery dataset; wire the tenant "
            f"query for {tenant!r} in the deployment (see docs/runbook.md)"
        )

    def get(self, worklist_id: str) -> StoredWorklist | None:
        from google.cloud import bigquery  # noqa: F401

        raise RuntimeError(
            "the managed worklist store needs a configured BigQuery dataset; wire the fetch for "
            f"{worklist_id!r} in the deployment (see docs/runbook.md)"
        )

    def put(self, worklist: StoredWorklist) -> str:
        from google.cloud import bigquery  # noqa: F401

        raise RuntimeError(
            "the managed worklist store needs a configured BigQuery dataset; wire the upsert in "
            "the deployment (see docs/runbook.md)"
        )
