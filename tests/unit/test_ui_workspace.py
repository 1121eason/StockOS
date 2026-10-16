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
    return {"wacc": 10, "terminal_growth": 2.5, "growth": 0,
            "cash": 120, "debt": 80, "shares": 100}


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
    result = ui.calculate(company, {**inputs(), "cash": 0, "debt": 1000,
                                    "terminal_growth": 0})
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
    assert request(server, "POST", "/api/sandbox", body,
                   {**headers, "Origin": "https://evil.example"})[0] == 403
    assert request(server, "POST", "/api/sandbox", "{}", headers)[0] == 422
    assert request(server, "GET", "/api/workspace?company=unknown")[0] == 404
    assert request(server, "POST", "/api/sandbox", "[]", headers)[0] == 422
