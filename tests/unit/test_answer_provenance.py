"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the model adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

Under ``local`` the generation port is the offline stub, which notes its own name; the managed
adapter refuses until a deployment wires a model endpoint, so it never answers and notes nothing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance

from recon_breaks_engine import config
from recon_breaks_engine.adapters.local.generation import LocalGenerationAdapter
from recon_breaks_engine.config import OFFLINE_STUB_MODEL

from tests import REPO_ROOT
from tests.conftest import local_settings

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"


def _reconcile(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    # CI targets run the suite with no profile exported; the served app must still be `local`.
    monkeypatch.setenv("RECONBREAKS_PROFILE", "local")
    from recon_breaks_engine.api.app import app

    client = TestClient(app, client=("127.0.0.1", 50000))
    response = client.post(
        "/v1/reconcile",
        json={"feed_a": "nostro", "feed_b": "scheme", "as_of": "2026-08-08"},
        headers={"X-Dev-Persona": "auditor"},
    )
    assert response.status_code == 200, response.text
    return dict(response.headers)


def test_the_local_narrator_answers_as_the_stub_the_pill_first_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under ``local`` the pill before and after the answer name the same stub."""
    headers = _reconcile(monkeypatch)
    assert headers[ANSWERED_BY] == OFFLINE_STUB_MODEL
    assert local_settings().generator_model == OFFLINE_STUB_MODEL
    assert SEARCH_USED not in headers


def test_a_call_that_searched_says_so_and_the_next_request_starts_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = LocalGenerationAdapter.draft

    def searching(self: LocalGenerationAdapter, prompt: str) -> str:
        provenance.note_search()
        return original(self, prompt)

    monkeypatch.setattr(LocalGenerationAdapter, "draft", searching)
    headers = _reconcile(monkeypatch)
    assert headers[ANSWERED_BY] == OFFLINE_STUB_MODEL
    assert headers[SEARCH_USED] == "true"
    monkeypatch.setattr(LocalGenerationAdapter, "draft", original)
    assert SEARCH_USED not in _reconcile(monkeypatch)


def test_the_stub_notes_its_name_once_per_answer() -> None:
    with provenance.scope() as record:
        LocalGenerationAdapter(local_settings()).draft("break_type: timing")
    assert record.models == [OFFLINE_STUB_MODEL]
    assert record.search_used is False


def test_generator_model_is_the_setting_the_adapter_reads_and_no_flag_swaps_it() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered."""
    models = SimpleNamespace(
        reasoning="the-model-the-adapter-calls",
        hard_reasoning="a-model-nobody-calls",
        use_hard_reasoning=True,
    )
    named = config._model_from_settings(SimpleNamespace(models=models), "models.reasoning")
    assert named == "the-model-the-adapter-calls"


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    settings_file = (REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "use_hard_reasoning" not in settings_file
    for source in sorted((REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
