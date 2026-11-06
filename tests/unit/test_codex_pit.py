import json
import sys

import pytest

from valuation_engine.ai.cli_provider import CodexCLIProvider
from valuation_engine.ai.codex_pit import (
    CONFIG,
    MODEL,
    POLICY_HASH,
    VERSION,
    call,
    discovery,
    monitor,
    overrides,
)
from valuation_engine.ai.provider import ProviderUnavailable


def fake(tmp_path, auth=True):
    p = tmp_path / "codex"
    p.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """import sys,json
if '--version' in sys.argv: print(VERSION_MARKER)
elif 'status' in sys.argv: print(AUTH)
elif '--help' in sys.argv: print('--json --output-schema --ignore-user-config --ignore-rules --ephemeral')
elif 'features' in sys.argv:
 for arg in sys.argv:
  if arg.startswith('features.'):
   key,value=arg.split('=',1);print(key[9:]+' stable '+value)
else:
 from pathlib import Path
 assert '--ignore-user-config' in sys.argv
 assert '--ephemeral' in sys.argv
 assert 'approval_policy="never"' in sys.argv
 assert 'permissions.qve_pit.network.enabled=false' in sys.argv
 import stat
 files=[p for p in Path.cwd().rglob('*') if p.is_file()]
 dirs=[p for p in Path.cwd().rglob('*') if p.is_dir()]
 assert {'output_schema.json','system_policy.md'} <= {p.name for p in files}
 assert all(stat.S_IMODE(p.stat().st_mode)==0o400 for p in files)
 assert all(stat.S_IMODE(p.stat().st_mode)==0o500 for p in dirs)
 assert stat.S_IMODE(Path.cwd().stat().st_mode)==0o500
 data=json.loads(sys.stdin.read())
 assert 'untrusted_data' in data
 print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{"answer":"unavailable"}'}}))
 print(json.dumps({'type':'turn.completed'}))
""".replace("AUTH", repr("Logged in using ChatGPT" if auth else "Not logged in")).replace("VERSION_MARKER", repr(VERSION))
    )
    p.chmod(0o700)
    return str(p)


def test_discovery_and_auth_absent(tmp_path):
    assert discovery(fake(tmp_path))["authenticated"]
    assert discovery(fake(tmp_path, auth=False))["reason"] == "AUTHENTICATION_REQUIRED"
    assert discovery(str(tmp_path / "absent"))["reason"] == "EXECUTABLE_MISSING"


def test_no_approval_without_gates(tmp_path):
    p = CodexCLIProvider(executable=fake(tmp_path))
    with pytest.raises(ProviderUnavailable):
        p.request("extract", {})


def test_historical_codex_request_requires_a_validated_quarter_package(tmp_path):
    provider = CodexCLIProvider(MODEL, fake(tmp_path), 10)
    provider._pit_approved = {"gate": "PASS", "policy_hash": POLICY_HASH}
    exact = {
        "system": "Synthetic",
        "task": "Test",
        "untrusted_data": {},
        "response_schema": {"type": "object"},
    }
    with pytest.raises(ProviderUnavailable, match="single-quarter package"):
        provider.request("extract", exact)


def test_controlled_transport_and_cohort(tmp_path):
    x = call(
        {
            "system": "Synthetic",
            "task": "Test",
            "untrusted_data": {},
            "response_schema": {"type": "object"},
        },
        fake(tmp_path),
    )
    assert x["structured_output"] == {"answer": "unavailable"}
    assert x["metadata"]["provider_type"] == "codex_cli"
    assert x["metadata"]["auth_mode"] == "chatgpt_subscription"
    assert x["metadata"]["working_directory_receipt"]["research_data"] is False
    assert x["metadata"]["working_directory_receipt"]["files_read_only"]
    assert x["metadata"]["working_directory_receipt"]["file_mode"] == "0400"
    assert x["metadata"]["working_directory_receipt"]["directories_read_only_during_inference"]
    assert x["metadata"]["ignored_user_config"]
    assert CONFIG["web_search"] == '"disabled"'
    assert CONFIG["mcp_servers"] == "{}"
    assert not any("danger-" in a for a in overrides())


def test_quarter_package_is_staged_read_only(tmp_path):
    from test_quarter_package import prepared

    from valuation_engine.ai.quarter_package import build_package

    package_context = prepared()
    package_context["quarter_package_manifest"] = build_package(package_context)["manifest"]
    exact = {
        "system": "Synthetic",
        "task": "Test",
        "untrusted_data": {"blocks": []},
        "response_schema": {"type": "object"},
    }
    result = call(exact, fake(tmp_path), package_context=package_context)
    receipt = result["metadata"]["working_directory_receipt"]
    assert receipt["research_data"]
    assert receipt["quarter"] == "FY2023-Q2"
    assert receipt["package_hash"] == package_context["quarter_package_manifest"]["package_hash"]
    assert "input/source_manifest.json" in receipt["files"]
    assert "output_schema.json" in receipt["files"]


@pytest.mark.parametrize(
    "kind", ["web_search", "mcp_tool_call", "command_execution", "file_change"]
)
def test_tool_attempt_rejected(tmp_path, kind):
    p = tmp_path / "fake.py"
    e = {"type": "item.started", "item": {"type": kind}}
    p.write_text("import time\nprint(" + repr(json.dumps(e)) + ",flush=True)\ntime.sleep(5)")
    r = monitor([sys.executable, str(p)], "", tmp_path, 2)
    assert r["failure_kind"] == "PIT_TOOL_OR_PERMISSION_ATTEMPT"
    assert r["structured_output"] is None
    assert r["external_file_success"] is None


def test_permission_request_rejected(tmp_path):
    p = tmp_path / "fake.py"
    p.write_text('print(\'{"type":"approval.requested"}\',flush=True)')
    r = monitor([sys.executable, str(p)], "", tmp_path, 2)
    assert r["permission_escalation_requested"] == 1
    assert r["structured_output"] is None


@pytest.mark.parametrize("text,kind", [("not json", "schema_failure"), ("", "timeout")])
def test_failure_and_timeout(tmp_path, text, kind):
    p = tmp_path / "fake.py"
    p.write_text("import time\nprint(" + repr(text) + ",flush=True)\ntime.sleep(3)")
    r = monitor([sys.executable, str(p)], "", tmp_path, 0.1)
    assert r["failure_kind"] == kind


def test_large_stage_timeout_has_a_finite_general_budget():
    from valuation_engine.ai.codex_pit import stage_timeout

    assert stage_timeout("extract", 180) == 180
    assert stage_timeout("synthesize", 180) == 600
    assert stage_timeout("challenge", 180) == 600
    assert stage_timeout("synthesize", 900) == 900
