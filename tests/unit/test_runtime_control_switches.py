"""Review routing has a switch, default on, and every caller says what happened to a hand-off.

The fleet's runtime-control contract (2026-09-24). Review routing is the one cheap runtime
control this service has: ``RECONBREAKS_REVIEW_ROUTING`` is read in three states; off binds a
disabled router and says so at startup; on under the managed profile refuses to boot without a
console; and the API, the agent tool and the CLI report ``review_routing`` rather than failing
an already-reconciled, already-audited run when the console is unreachable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from recon_breaks_engine.adapters.controls import (
    DisabledReviewRouter,
    RecordingReviewRouter,
    ReviewRouting,
)
from recon_breaks_engine.agent.tools import reconcile_feeds
from recon_breaks_engine.api import app as api_module
from recon_breaks_engine.api.app import app
from recon_breaks_engine.cli.main import main as cli_main
from recon_breaks_engine.config import (
    REVIEW_ROUTING_ENV,
    Container,
    ControlSwitches,
    ProfileChoice,
    Settings,
    build_container,
    warn_switched_off,
)
from recon_breaks_engine.domain.kernel import Citation, Decision, Severity
from recon_breaks_engine.domain.models import BreakResolution, BreakType
from recon_breaks_engine.envread import ConfiguredEmptyError

from tests.fixtures import sample_cases

_LOOPBACK = ("127.0.0.1", 50000)
_LOCAL_ROUTE = "recon_breaks_engine.adapters.local.review_router.LocalReviewRouter.route"
_BODY = {
    "feed_a": sample_cases.NOSTRO_FEED,
    "feed_b": sample_cases.SCHEME_FEED,
    "as_of": sample_cases.AS_OF.isoformat(),
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(REVIEW_ROUTING_ENV, raising=False)
    monkeypatch.delenv("HUMAN_REVIEW_URL", raising=False)
    # The API caches its container for the process; each test here states its own posture.
    api_module._container.cache_clear()
    yield
    api_module._container.cache_clear()


def _settings(**overrides: object) -> Settings:
    return Settings(profile="local", audit_path=":memory:", tenant="demo-bank", **overrides)  # type: ignore[arg-type]


def _resolution(*, requires_review: bool = True) -> BreakResolution:
    return BreakResolution(
        subject="break BRK-missing-A6 (ZETA INC FICTIONAL)",
        severity=Severity.HIGH,
        decision=Decision.ESCALATED,
        summary="One feed carries this item with no counterpart on the other feed.",
        requires_human_review=requires_review,
        break_id="BRK-missing-A6",
        break_type=BreakType.MISSING,
        hypothesis="One feed carries this item with no counterpart on the other feed.",
        journal_note="Investigate missing break; do NOT post until a checker confirms.",
        citations=(Citation(source_id="nostro:7", title="Feed nostro line 7", snippet="A6"),),
    )


def _gcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "recon_breaks_engine.config.resolve_profile",
        lambda environ=None: ProfileChoice("gcp", True),
    )


# --------------------------------------------------------------------------- #
# Three states
# --------------------------------------------------------------------------- #
def test_routing_is_on_when_nothing_is_said() -> None:
    assert Settings.load().controls == ControlSwitches(review_routing=True)


def test_routing_switched_off_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert Settings.load().controls.switched_off() == (REVIEW_ROUTING_ENV,)


def test_an_emptied_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "")
    with pytest.raises(ConfiguredEmptyError, match=REVIEW_ROUTING_ENV):
        Settings.load()


def test_an_unrecognised_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "sometimes")
    with pytest.raises(ValueError, match=REVIEW_ROUTING_ENV):
        Settings.load()


# --------------------------------------------------------------------------- #
# Off binds the disabled router, and says so once
# --------------------------------------------------------------------------- #
def test_off_binds_the_disabled_router() -> None:
    settings = _settings(controls=ControlSwitches(review_routing=False))
    assert isinstance(Container(settings).review_router, DisabledReviewRouter)


def test_on_binds_the_profile_router() -> None:
    assert not isinstance(Container(_settings()).review_router, DisabledReviewRouter)


def test_the_off_posture_is_logged_once_however_many_containers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    warn_switched_off.cache_clear()
    settings = _settings(controls=ControlSwitches(review_routing=False))
    with caplog.at_level(logging.WARNING, logger="recon_breaks_engine.config"):
        for _ in range(3):
            build_container(settings)
    assert caplog.text.count(REVIEW_ROUTING_ENV) == 1


# --------------------------------------------------------------------------- #
# On has to work: checked at boot under the managed profile
# --------------------------------------------------------------------------- #
def test_routing_on_under_gcp_without_a_console_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _gcp(monkeypatch)
    with pytest.raises(ConfiguredEmptyError, match="HUMAN_REVIEW_URL"):
        Settings.load()


def test_routing_stated_off_under_gcp_still_needs_the_console_for_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case engine opens escalation cases on the same console and has no switch."""
    _gcp(monkeypatch)
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "false")
    with pytest.raises(ConfiguredEmptyError, match="case engine"):
        Settings.load()


def test_routing_stated_off_under_gcp_with_a_console_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _gcp(monkeypatch)
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "false")
    monkeypatch.setenv("HUMAN_REVIEW_URL", "https://review.example.test")
    assert Settings.load().controls.review_routing is False


def test_routing_on_under_gcp_with_a_console_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    _gcp(monkeypatch)
    monkeypatch.setenv("HUMAN_REVIEW_URL", "https://review.example.test")
    assert Settings.load().review_url == "https://review.example.test"


# --------------------------------------------------------------------------- #
# The four routing outcomes
# --------------------------------------------------------------------------- #
class _Accepting:
    def route(self, result: BreakResolution, *, maker: str, tenant: str = "") -> str:
        return "review-1"


class _Refusing:
    def route(self, result: BreakResolution, *, maker: str, tenant: str = "") -> str:
        raise ConnectionError("console unreachable")


def test_routing_outcomes_take_each_of_their_four_values() -> None:
    not_required = RecordingReviewRouter(_Accepting())
    assert not_required.route(_resolution(requires_review=False), maker="m") == ""
    assert not_required.outcome is ReviewRouting.NOT_REQUIRED

    routed = RecordingReviewRouter(_Accepting())
    assert routed.route(_resolution(), maker="m") == "review-1"
    assert routed.outcome is ReviewRouting.ROUTED

    off = RecordingReviewRouter(DisabledReviewRouter(_settings()))
    assert off.route(_resolution(), maker="m") == ""
    assert off.outcome is ReviewRouting.OFF


def test_one_failure_among_many_hand_offs_is_what_the_caller_reports(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = iter(("review-1", ConnectionError("console unreachable"), "review-3"))

    class _Flaky:
        def route(self, result: BreakResolution, *, maker: str, tenant: str = "") -> str:
            answer = next(calls)
            if isinstance(answer, Exception):
                raise answer
            return answer

    recorder = RecordingReviewRouter(_Flaky())
    with caplog.at_level(logging.WARNING, logger="recon_breaks_engine.adapters.controls"):
        refs = [recorder.route(_resolution(), maker="m") for _ in range(3)]
    assert refs == ["review-1", "", "review-3"]
    assert recorder.outcome is ReviewRouting.FAILED
    assert "ConnectionError" in caplog.text


# --------------------------------------------------------------------------- #
# Every caller reports it: the API, the agent tool, the CLI
# --------------------------------------------------------------------------- #
def _reconcile() -> dict[str, object]:
    response = TestClient(app, client=_LOOPBACK).post(
        "/v1/reconcile", json=_BODY, headers={"X-Dev-Persona": "auditor"}
    )
    assert response.status_code == 200
    return response.json()


def test_the_api_reports_a_routed_hand_off() -> None:
    assert _reconcile()["review_routing"] == "routed"


def test_the_api_reports_routing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert _reconcile()["review_routing"] == "off"


def test_the_api_reports_a_failed_hand_off_instead_of_failing_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_LOCAL_ROUTE, _Refusing.route)
    body = _reconcile()
    assert body["review_routing"] == "failed"
    assert body["requires_human_review"] is True


def test_the_agent_tool_reports_the_hand_off() -> None:
    payload = reconcile_feeds(
        sample_cases.NOSTRO_FEED,
        sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF.isoformat(),
        tenant=sample_cases.TENANT,
        settings=_settings(),
    )
    assert payload["review_routing"] == "routed"


def test_the_agent_tool_reports_routing_off() -> None:
    payload = reconcile_feeds(
        sample_cases.NOSTRO_FEED,
        sample_cases.SCHEME_FEED,
        as_of=sample_cases.AS_OF.isoformat(),
        tenant=sample_cases.TENANT,
        settings=_settings(controls=ControlSwitches(review_routing=False)),
    )
    assert payload["review_routing"] == "off"


def test_the_cli_reports_the_hand_off(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["reconcile", sample_cases.NOSTRO_FEED, sample_cases.SCHEME_FEED]
    assert cli_main([*argv, "--as-of", sample_cases.AS_OF.isoformat()]) == 0
    assert "human review hand-off : routed" in capsys.readouterr().out
