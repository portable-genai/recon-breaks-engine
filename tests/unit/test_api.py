"""API surface: verified-principal identity, fail-closed S2S, security headers.

The client comes from the shared ``api_client`` fixture, which pins a loopback peer: the
app-object exposure guard refuses the unauthenticated local posture to any other peer, and
TestClient's default peer is the literal host "testclient".
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import sample_cases

_TOKEN_ENV = "RECONBREAKS_S2S_TOKEN"


def _reconcile_body() -> dict[str, str]:
    return {
        "feed_a": sample_cases.NOSTRO_FEED,
        "feed_b": sample_cases.SCHEME_FEED,
        "as_of": "2026-08-08",
    }


def test_reconcile_uses_the_verified_principal_as_actor(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/reconcile",
        json=_reconcile_body(),
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["match_count"] == 5
    # Five typed breaks, plus the fixture's PII-carrying nostro row, which reconciles to nothing.
    assert len(body["breaks"]) == 6
    assert body["requires_human_review"] is True
    # Rule R8: every drafted resolution is routed, not merely flagged (see test_review_routing.py).
    assert all(r["requires_human_review"] for r in body["resolutions"])
    # The ops-worklist export (the F5 data contract) is computed and returned.
    assert body["export"]["schema_version"] == "ops-worklist-export/v1"


def test_a_reconcile_persists_a_retrievable_tenant_scoped_worklist(api_client: TestClient) -> None:
    """The worklist a reconcile ranks is stored and can be read back by its own tenant."""
    posted = api_client.post(
        "/v1/reconcile", json=_reconcile_body(), headers={"X-Dev-Persona": "auditor"}
    ).json()
    worklist_id = posted["worklist_id"]
    assert worklist_id, "the reconcile must return the handle its worklist was persisted under"
    got = api_client.get("/v1/worklist/" + worklist_id, headers={"X-Dev-Persona": "auditor"})
    assert got.status_code == 200
    body = got.json()
    assert len(body["breaks"]) == len(posted["breaks"])
    assert all(b["citations"] for b in body["breaks"]), "every stored break keeps its citations"


def test_a_cross_tenant_worklist_read_is_403_not_404(api_client: TestClient) -> None:
    """A worklist belonging to another tenant is refused with 403: the record exists, the caller
    may not see it. 404 would leak whether the id is in use across the boundary."""
    from datetime import date

    from recon_breaks_engine.api.app import _container
    from recon_breaks_engine.domain.models import StoredWorklist

    _container().worklist_store.put(
        StoredWorklist(
            worklist_id="wl:other-bank:nostro:scheme",
            tenant="other-bank",
            feed_id="nostro:scheme",
            as_of=date(2026, 8, 8),
            ranked_breaks=(),
        )
    )
    denied = api_client.get(
        "/v1/worklist/wl:other-bank:nostro:scheme", headers={"X-Dev-Persona": "auditor"}
    )
    assert denied.status_code == 403


def test_a_missing_worklist_is_404(api_client: TestClient) -> None:
    resp = api_client.get("/v1/worklist/wl:demo-bank:no:such", headers={"X-Dev-Persona": "auditor"})
    assert resp.status_code == 404


def test_unknown_persona_is_401(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/reconcile",
        json=_reconcile_body(),
        headers={"X-Dev-Persona": "ghost"},
    )
    assert resp.status_code == 401


def test_healthz_reports_profile_and_region(api_client: TestClient) -> None:
    body = api_client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["profile"] == "local"
    assert body["region"] == "asia-southeast1"


def test_security_headers_present(api_client: TestClient) -> None:
    headers = api_client.get("/healthz").headers
    assert headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.fixture()
def token_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv(_TOKEN_ENV, "s3cret-service-token")
    yield "s3cret-service-token"


def test_s2s_endpoint_open_when_secret_unset(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_TOKEN_ENV, raising=False)
    assert api_client.post("/v1/audit/ping").status_code == 200


def test_s2s_endpoint_rejects_missing_token_when_enforced(
    api_client: TestClient, token_env: str
) -> None:
    assert api_client.post("/v1/audit/ping").status_code == 401


def test_s2s_endpoint_accepts_correct_token(api_client: TestClient, token_env: str) -> None:
    resp = api_client.post("/v1/audit/ping", headers={"Authorization": f"Bearer {token_env}"})
    assert resp.status_code == 200
