"""Synthetic transport tests; these are not real Gemini analyses."""

import json
import sys

import pytest

from valuation_engine.ai.cli_provider import GeminiCLIProvider
from valuation_engine.ai.contracts import Extraction
from valuation_engine.ai.prompts import prompt
from valuation_engine.ai.provider import ProviderUnavailable
from valuation_engine.ai.recovery import RecoveryProvider
from valuation_engine.db.store import digest


def fake(tmp_path, response='{"ok":true}', code=0, tools=0):
    path = tmp_path / "gemini"
    path.write_text(f"""#!{sys.executable}
import json,os,sys
from pathlib import Path
if '--version' in sys.argv: print('0.59.0')
elif '--help' in sys.argv: print('--prompt --output-format --model --skip-trust')
else:
    marker = Path.cwd() / 'GEMINI.md'
    marker.write_text('future document must not enter context')
    try:
        marker.read_text()
        raise AssertionError('OS memory boundary was not enforced')
    except PermissionError:
        pass
    assert 'GEMINI_API_KEY' not in os.environ
    settings=json.loads(Path(os.environ['GEMINI_CLI_SYSTEM_SETTINGS_PATH']).read_text())
    assert settings['tools']['core'] == []
    assert settings['context']['fileName'] == []
    assert not settings['admin']['mcp']['enabled']
    assert not settings['admin']['extensions']['enabled']
    assert not settings['hooksConfig']['enabled']
    assert settings['security']['auth']['selectedType'] == 'oauth-personal'
    assert 'Return' in Path(os.environ['GEMINI_SYSTEM_MD']).read_text()
    json.loads(sys.stdin.read())
    print({json.dumps({"response": response, "stats": {"models": {"test-actual": {}}, "tools": {"totalCalls": tools}}})!r})
    sys.exit({code})
""")
    path.chmod(0o700)
    return GeminiCLIProvider(executable=str(path))


def test_google_probe_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-forward")
    provider = fake(tmp_path)
    assert not provider.check()["ready"]
    assert provider._legacy_probe()["ready"]
    assert provider.settings["activation"] == "authorized_quota_fallback"


@pytest.mark.parametrize(
    "response,code,tools",
    [
        ("not JSON", 0, 0),
        ('```json\n{"ok":true}\n```', 0, 0),
        ('{"ok":true}', 1, 0),
        ('{"ok":true}', 0, 1),
    ],
)
def test_probe_fails_closed(tmp_path, response, code, tools):
    assert not fake(tmp_path, response, code, tools)._legacy_probe()["ready"]


def test_no_analysis_before_probe(tmp_path):
    with pytest.raises(ProviderUnavailable):
        fake(tmp_path).request("extract", prompt("extract", {}, Extraction))


def test_recovery_only_exact_extraction(tmp_path):
    delegate = fake(tmp_path)
    exact = prompt("extract", {}, Extraction)
    raw = {"structured_output": {"evidence": []}, "execution_metadata": {}}
    cached = RecoveryProvider(delegate, {digest(["extract", exact]): {"id": 42, "raw": raw}})
    assert cached.request("extract", exact)["execution_metadata"]["reused_from_call_id"] == 42
    assert raw["execution_metadata"] == {}
    with pytest.raises(ProviderUnavailable):
        cached.request("synthesize", exact)
    with pytest.raises(ProviderUnavailable):
        cached.request("extract", {**exact, "task": "changed"})


def test_service_ineligibility_is_not_login_failure(tmp_path):
    model = fake(tmp_path, code=1)
    path = tmp_path / "gemini"
    path.write_text(
        path.read_text().replace(
            "    sys.exit(1)",
            "    print('IneligibleTierError UNSUPPORTED_CLIENT', file=sys.stderr)\n    sys.exit(1)",
        )
    )
    result = model._legacy_probe()
    assert result["ready"] is False
    assert result["reason"] == "UNSUPPORTED_CLIENT"
    assert result["authentication"] == "service_ineligible"


def test_deprecated_consumer_route_never_executes(tmp_path):
    model = fake(tmp_path)
    assert model.probe()["reason"] == "LEGACY_CONSUMER_ROUTE_DEPRECATED"
    with pytest.raises(ProviderUnavailable, match="deprecated"):
        model.request("extract", {})
