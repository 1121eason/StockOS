import json
import runpy
import signal
import subprocess
from pathlib import Path

import httpx
import pytest

from valuation_engine.ai.native_preflight import (
    capture_official,
    classify_command_probe,
    compare_narrative,
    load_bound,
    official_url,
    parse_census,
    summarize,
)

SOURCE = "https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2023"


@pytest.mark.parametrize(
    "url",
    [
        "http://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2023",
        "https://www.sec.gov.evil.example/Archives/edgar/data/1045810/000104581022000079/a.htm",
        "https://www.sec.gov/Archives/edgar/data/9999999/000104581022000079/a.htm",
        "https://user:secret@www.sec.gov/Archives/edgar/data/1045810/000104581022000079/a.htm",
        SOURCE + "?token=sensitive",
        SOURCE + "#fragment",
    ],
)
def test_nonselected_or_credential_urls_refused(url):
    with pytest.raises(ValueError):
        official_url(url)


def test_rehashed_replacement_does_not_replace_pinned_protocol(tmp_path):
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps({"protocol_hash": "attacker-supplied", "live_authorized": True}))
    with pytest.raises(ValueError, match="pinned"):
        load_bound(path, "protocol_hash", "f" * 64)


def test_census_keeps_desktop_parents_and_interpreters_unresolved():
    census = parse_census(
        "1 0 /sbin/launchd\n10 1 /Applications/Codex.app/codex\n11 10 /bin/node\n12 1 /bin/python3.14\n13 1 /bin/custom-codex-worker\n",
        0,
    )
    assert [p["pid"] for p in census["candidates"]] == [10, 11, 12, 13]
    assert census["no_residual_provider_proven"] is False
    assert census["classification_status"].startswith("UNVERIFIED")


@pytest.mark.parametrize(
    "raw,code",
    [("", 0), ("1 0 /bin/a", 1), ("1 0 /bin/a\n1 0 /bin/a", 0), ("bad row", 0), ("0 0 /bin/a", 0)],
)
def test_failed_incomplete_or_duplicate_census_is_not_clean(raw, code):
    with pytest.raises(ValueError):
        parse_census(raw, code)


def test_redirect_revalidated_before_second_request(tmp_path):
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/secret"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError):
            capture_official(SOURCE, tmp_path / "capture.html", client=client)
    assert requests == [SOURCE]
    assert not (tmp_path / "capture.html").exists()


def test_current_capture_cannot_certify_historical_time(tmp_path):
    data = b'<html><meta property="article:published_time" content="2022-08-24T16:20:00-04:00">Disclosure</html>'
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=data))
    ) as client:
        capture = capture_official(SOURCE, tmp_path / "capture.html", client=client)
    assert (tmp_path / "capture.html").read_bytes() == data
    assert capture["historical_availability"].startswith("UNVERIFIED")
    assert len(capture["publication_metadata_observed"]) == 1


def test_http_error_does_not_write_official_capture(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            capture_official(SOURCE, tmp_path / "capture.html", client=client)
    assert not (tmp_path / "capture.html").exists()


def test_chrome_changes_can_match_all_research_text_without_claiming_historical_proof():
    result = compare_narrative(
        b"<nav>New menu</nav><p>Demand   weakened.</p><script>Missing quote</script>",
        [{"block_id": "1", "text": "Demand weakened."}, {"block_id": "2", "text": "Missing quote"}],
    )
    assert result["matching_blocks"] == 1
    assert result["missing_block_ids"] == ["2"]
    assert result["historical_availability"].startswith("UNVERIFIED")


def test_successful_discovery_and_empty_census_do_not_enable_models():
    from valuation_engine.ai.codex_pit import VERSION

    result = summarize(
        {"budget_status": "WITHIN_SINGLE_PAIR_CAP", "source_count": 1},
        {"cli_version": VERSION, "authenticated": True, "features_verified": True},
        {"observation_sha256": "x", "candidates": []},
        [{"exact_cached_bytes_match": True}],
    )
    assert result["ready_for_live"] is False
    assert "HISTORICAL_SOURCE_AVAILABILITY_NOT_AUTHENTICATED" in result["blockers"]
    assert result["live_model_attempts"] == 0
    assert result["quality_verdict"] == "UNSCORED"
    assert result["winner"] is None


@pytest.mark.parametrize(
    "error,exit_code,expected",
    [
        ("dd: outside-canary.txt: Operation not permitted", 1, "DENIED_WITH_SUCCESSFUL_CONTROL"),
        ("sandbox-exec: execvp() of dd failed: Operation not permitted", 71, "UNVERIFIED"),
        ("dd: outside-canary.txt: No such file or directory", 1, "UNVERIFIED"),
        ("dd: outside-canary.txt: Operation not permitted", 0, "UNVERIFIED"),
    ],
)
def test_startup_and_missing_file_errors_do_not_pass_isolation(error, exit_code, expected):
    control = {"exit_code": 0, "timeout": False, "group_absent": True}
    restricted = {"exit_code": exit_code, "stderr": error, "timeout": False, "group_absent": True}
    assert classify_command_probe("outside_read", control, restricted) == expected
    control["exit_code"] = 1
    assert classify_command_probe("outside_read", control, restricted) == "UNVERIFIED"


def test_owned_probe_sends_one_termination_signal_before_reaping(monkeypatch):
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/probe_nvda_ai_runtime.py")
    )
    calls, saved = [], []

    class Process:
        pid = 123
        returncode = None

        def wait(self, timeout):
            if timeout == 0.2:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            self.returncode = -9

        def poll(self):
            return self.returncode

    def killpg(pid, sig):
        calls.append((pid, sig))
        if sig == 0:
            raise ProcessLookupError()
        if len(calls) > 1:
            raise PermissionError("Repeated signal would interrupt cleanup")

    monkeypatch.setattr(module["os"], "killpg", killpg)
    state = {"group_absent": False, "cleanup_status": "PENDING"}
    module["reap_owned_probe"](Process(), state, lambda: saved.append(dict(state)))
    assert calls == [(123, signal.SIGKILL), (123, 0)]
    assert state["cleanup_status"] == "CLEAN"
    assert saved[-1]["reaped"] is True


def test_denied_termination_persists_unknown_and_never_retries(monkeypatch):
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/probe_nvda_ai_runtime.py")
    )
    calls, saved = [], []

    class Process:
        pid = 123

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("synthetic", timeout)

        def poll(self):
            return None

    def killpg(pid, sig):
        calls.append((pid, sig))
        raise PermissionError("Synthetic denial")

    monkeypatch.setattr(module["os"], "killpg", killpg)
    state = {"group_absent": False, "cleanup_status": "PENDING"}
    with pytest.raises(PermissionError):
        module["reap_owned_probe"](Process(), state, lambda: saved.append(dict(state)))
    assert calls == [(123, signal.SIGKILL)]
    assert saved[-1]["cleanup_status"] == "UNKNOWN"
    assert saved[-1]["error_type"] == "PermissionError"
