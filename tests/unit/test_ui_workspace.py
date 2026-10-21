"""Boundary and contract tests for the local-only, non-persistent UI adapter."""

import importlib.util
import json
import threading
from decimal import Decimal
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "stockos_ui", Path(__file__).resolve().parents[2] / "scripts/serve_ui.py"
)
assert SPEC and SPEC.loader
ui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ui)


def inputs():
    return {"wacc": 10, "terminal_growth": 2.5, "growth": 0, "cash": 120, "debt": 80, "shares": 100}


@pytest.mark.parametrize(
    "value",
    [
        "http://stockos.example",
        "https://user:password@stockos.example",
        "https://stockos.example/path",
        "https://stockos.example?query=1",
        "https://stockos.example#fragment",
        "https://stockos.example:8080",
        "https://stockos.example evil.example",
        "https://stockos.example,evil.example",
    ],
)
def test_proxy_origin_rejects_ambiguous_or_insecure_values(value):
    with pytest.raises(ValueError):
        ui.validate_proxy_origin(value)


def test_proxy_origin_is_exact_https_only():
    assert ui.validate_proxy_origin("https://stockos.example") == "https://stockos.example"


def test_private_proxy_keeps_host_and_cross_origin_guards():
    from types import SimpleNamespace

    instance = ui.ResearchHTTPServer(("127.0.0.1", 0), ui.Handler)
    instance.public_origin = "https://stockos.example"
    calls = []

    def update():
        calls.append(True)
        return {"refresh_queued": True}

    instance.workbench = SimpleNamespace(update=update)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    port = instance.server_address[1]
    headers = {"Content-Type": "application/json", "Origin": instance.public_origin}
    try:
        assert request(port, "POST", "/api/nvda/update", "{}", headers)[0] == 200
        for overrides in (
            {"Origin": "https://stockos.example.evil.test"},
            {"Host": "stockos.example"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            assert (
                request(port, "POST", "/api/nvda/update", "{}", {**headers, **overrides})[0] == 403
            )
        assert len(calls) == 1
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def test_demo_retains_negative_values_and_unavailable_price():
    result = ui.workspace("atlas")
    assert result["mode"] == "demo"
    assert Decimal(result["valuation"]["per_share"]) < 0
    assert result["valuation"]["negative_equity_warning"] is True
    assert result["snapshot"]["price"] is None
    assert result["snapshot"]["run_id"] is None
    assert result["valuation"]["scenarios"][0]["wacc_pct"] == "11.00000000"


def test_empty_company_does_not_become_a_zero_valuation():
    result = ui.workspace("empty")
    assert result["valuation"]["status"] == "unavailable"
    assert "per_share" not in result["valuation"]


def test_exact_zero_dcf_is_available_and_not_treated_as_missing():
    company = {"cashflows": [100]}
    result = ui.calculate(company, {**inputs(), "cash": 0, "debt": 1000, "terminal_growth": 0})
    assert result["status"] == "available"
    assert Decimal(result["per_share"]) == 0


@pytest.mark.parametrize("field", list(ui.FIELDS))
@pytest.mark.parametrize("bad", [None, "", " ", True, "NaN", "Infinity"])
def test_missing_and_invalid_inputs_rejected(field, bad):
    with pytest.raises(ValueError):
        ui.numbers({**inputs(), field: bad})


def test_zero_cash_and_debt_are_valid_and_wacc_guard_is_explicit():
    assert ui.numbers({**inputs(), "cash": 0, "debt": 0})["cash"] == 0
    with pytest.raises(ValueError, match="WACC"):
        ui.numbers({**inputs(), "wacc": 2, "terminal_growth": 2})


@pytest.fixture
def server():
    instance = ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance.server_address[1]
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=2)


def request(port, method, path, body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    result = response.status, dict(response.getheaders()), data
    connection.close()
    return result


def test_nvda_without_configuration_never_uses_demo_data(server):
    status, _, body = request(server, "GET", "/api/nvda")
    assert status == 200
    assert json.loads(body)["configured"] is False
    assert json.loads(body)["research"] is None
    assert (
        request(server, "POST", "/api/nvda/update", "{}", {"Content-Type": "application/json"})[0]
        == 409
    )


@pytest.fixture
def nvda_server():
    from types import SimpleNamespace

    calls = []

    def update():
        calls.append(True)
        return {"snapshot_id": "synthetic", "research": {"synthetic_only": True}}

    instance = ui.ResearchHTTPServer(("127.0.0.1", 0), ui.Handler)
    instance.workbench = SimpleNamespace(update=update, load=update, last_attempt=None)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance.server_address[1], calls
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=2)


def test_nvda_manual_update_has_no_path_ticker_or_model_input(nvda_server):
    port, calls = nvda_server
    headers = {"Content-Type": "application/json"}
    assert request(port, "POST", "/api/nvda/update", "{}", headers)[0] == 200
    assert len(calls) == 1
    for body in ('{"ticker":"OTHER"}', '{"source_db":"/private/file"}', "[]", "null", "bad JSON"):
        assert request(port, "POST", "/api/nvda/update", body, headers)[0] == 422
    assert len(calls) == 1


def test_nvda_manual_update_rejects_cross_origin_and_non_json(nvda_server):
    port, calls = nvda_server
    assert (
        request(
            port,
            "POST",
            "/api/nvda/update",
            "{}",
            {"Origin": "https://external.example", "Content-Type": "application/json"},
        )[0]
        == 403
    )
    assert request(port, "POST", "/api/nvda/update", "{}", {"Content-Type": "text/plain"})[0] == 422
    assert len(calls) == 0


def test_http_allowlist_no_database_credentials_or_directory_exposure(server):
    for path in ["/.env", "/data/qve.db", "/ui/fixtures/demo.json", "/src/", "/../README.md"]:
        assert request(server, "GET", path)[0] == 404
    status, headers, body = request(server, "GET", "/")
    assert status == 200 and "zh-Hant" in body.decode()
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert request(server, "GET", "/", headers={"Host": "evil.example"})[0] == 403


def test_http_calculation_and_cross_origin_guard(server):
    body = json.dumps({"company": "aurora", **inputs()})
    headers = {"Content-Type": "application/json"}
    status, _, content = request(server, "POST", "/api/sandbox", body, headers)
    assert status == 200 and json.loads(content)["status"] == "available"
    assert (
        request(
            server, "POST", "/api/sandbox", body, {**headers, "Origin": "https://evil.example"}
        )[0]
        == 403
    )
    assert request(server, "POST", "/api/sandbox", "{}", headers)[0] == 422
    assert request(server, "GET", "/api/workspace?company=unknown")[0] == 404
    assert request(server, "POST", "/api/sandbox", "[]", headers)[0] == 422


def test_research_routes_are_read_only_and_empty_without_explicit_store(server):
    status, _, body = request(server, "GET", "/api/research/runs")
    assert status == 200
    assert json.loads(body) == {"configured": False, "runs": []}
    assert request(server, "GET", "/api/research/run?id=anything")[0] == 404
    assert request(server, "POST", "/api/research/runs", "{}")[0] == 404
    assert request(server, "GET", "/research")[0] == 200
    assert request(server, "GET", "/research.js")[0] == 200


def test_research_http_loads_canonical_saved_result_without_demo_substitution(tmp_path):
    from valuation_engine.research.workspace import import_bundle

    def evidence(value):
        return {"value": value, "source_ids": ["filing"], "available_at": "2020-01-01T00:00:00Z"}

    bundle = {
        "schema_version": 1,
        "ticker": "TEST",
        "name": "Synthetic contract test",
        "as_of": "2020-01-01T00:00:00Z",
        "data_kind": "synthetic",
        "sources": [
            {
                "id": "filing",
                "url": "https://example.com/synthetic",
                "published_at": "2019-12-31T00:00:00Z",
                "retrieved_at": "2026-01-01T00:00:00Z",
                "sha256": "a" * 64,
            }
        ],
        "inputs": {
            "cash": evidence("0"),
            "debt": evidence("1000"),
            "shares": evidence("100"),
            "wacc": evidence("0.1"),
            "terminal_growth": evidence("0"),
            "forecast_cashflows": [evidence("100") for _ in range(5)],
        },
        "assumptions": {
            "classification": "research_reconstructed_not_historical_oos",
            "rationale": "Synthetic test values; no historical model vintage.",
        },
    }
    store = tmp_path / "private.sqlite"
    stored = import_bundle(store, bundle)
    instance = ui.ResearchHTTPServer(("127.0.0.1", 0), ui.Handler)
    instance.research_store = store
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    port = instance.server_address[1]
    try:
        status, _, body = request(port, "GET", "/api/research/runs")
        assert status == 200
        assert json.loads(body)["runs"][0]["run_id"] == stored["run_id"]
        status, _, body = request(port, "GET", "/api/research/run?id=" + stored["run_id"])
        assert status == 200
        loaded = json.loads(body)
        assert loaded == stored
        assert loaded["formal_decision"] == "withheld"
        assert Decimal(loaded["valuation"]["per_share"]) == 0
        assert request(port, "GET", "/api/research/run?id=../../private.sqlite")[0] == 422
        assert request(port, "GET", "/private.sqlite")[0] == 404
        assert json.loads(request(port, "GET", "/api/workspace")[2])["mode"] == "demo"
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)
