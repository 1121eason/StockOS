import json
import sys

import pytest

from valuation_engine.ai.cli_provider import CodexCLIProvider
from valuation_engine.ai.codex_pit import CONFIG, call, discovery, monitor, overrides
from valuation_engine.ai.provider import ProviderUnavailable


def fake(tmp_path, auth=True):
    p = tmp_path / "codex"
    p.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """import sys,json
if '--version' in sys.argv: print('codex-cli 0.153.4')
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
 assert sorted(p.name for p in Path.cwd().iterdir())==['schema.json','system.md']
 data=json.loads(sys.stdin.read())
 assert 'untrusted_data' in data
 print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{"answer":"unavailable"}'}}))
 print(json.dumps({'type':'turn.completed'}))
""".replace("AUTH", repr("Logged in using ChatGPT" if auth else "Not logged in"))
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
    assert x["metadata"]["ignored_user_config"]
    assert CONFIG["web_search"] == '"disabled"'
    assert CONFIG["mcp_servers"] == "{}"
    assert not any("danger-" in a for a in overrides())


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
