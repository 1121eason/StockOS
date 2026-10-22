"""Synthetic receipt fixtures only: no model calls, authorization or quality evidence."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from test_fsi_s2_provenance import SyntheticProvider, load
from test_nvda_q2_candidate_runner import kernel

from valuation_engine.ai.native_preflight import canonical, sha
from valuation_engine.ai.quarter_runtime import CLI_VERSION, CONTRACT_HASH, MODEL


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def bound_pair(tmp_path):
    runner, verifier = load("run_fsi_s2_experiment"), load("verify_fsi_lineage")
    root, state = tmp_path, tmp_path / "shared-state"
    research, diagnostic = root / "research", root / "diagnostic"
    database = research / "candidate.db"
    research.mkdir()
    state.mkdir()
    write(
        research / "approval.json",
        {
            "contract_hash": CONTRACT_HASH,
            "decision": "APPROVED_BY_USER",
            "user_instruction": "SYNTHETIC TEST ONLY - NO HUMAN APPROVAL OR MODEL CALL",
            "shared_state_root": str(state),
        },
    )
    write(root / "kernel-probe/receipt.json", kernel())
    kernel_hash = sha((root / "kernel-probe/receipt.json").read_bytes())
    for folder in (diagnostic, research):
        write(folder / "kernel-binding.json", {"kernel_receipt_sha256": kernel_hash})
    count = 0

    def recorded_response(stage, method, exact, output):
        nonlocal count
        count += 1
        folder = (diagnostic if method is None else research) / f"call-{count:04d}"
        folder.mkdir()
        stdout = (json.dumps({"synthetic_only": True, "output": output}) + "\n").encode()
        (folder / "stdout.jsonl").write_bytes(stdout)
        (folder / "stderr.txt").write_bytes(b"")
        result = {
            "group_absent": True,
            "runner_signals": [],
            "exit_code": 0,
            "turn_completed": True,
            "failure": None,
            "remaining_observed_descendants": [],
            "workspace_files_after": ["schema.json", "system.md"],
            "requested_model": MODEL,
            "actual_model": None,
            "structured_output": output,
            "stdout.jsonl_sha256": sha(stdout),
            "stderr.txt_sha256": sha(b""),
        }
        write(folder / "request.json", exact)
        write(folder / "result.json", result)
        write(
            state / f"attempt-{count:04d}.json",
            {
                "index": count,
                "contract_hash": CONTRACT_HASH,
                "phase": "diagnostic" if method is None else "research",
                "stage": stage,
                "method": method,
                "status": "COMPLETED",
                "cleanup": "CLEAN",
                "request_hash": sha(canonical(exact).encode()),
                "result_sha256": sha(canonical(result).encode()),
            },
        )
        return {
            "structured_output": output,
            "response_model": None,
            "raw_response": result,
            "execution_metadata": {
                "provider_execution_status": "completed",
                "model_identity_status": "REQUESTED_ONLY",
                "requested_model": MODEL,
                "cli_version": CLI_VERSION,
                "execution_contract_hash": CONTRACT_HASH,
            },
        }

    for index in range(1, 8):
        recorded_response(
            f"isolation_{index}", None, {"synthetic_test": index}, {"answer": "unavailable"}
        )
    write(
        diagnostic / "isolation.json",
        {
            "contract_hash": CONTRACT_HASH,
            "status": "PASS",
            "diagnostic_attempts": 7,
            "gates": {f"C{i}": "PASS" for i in range(1, 13)},
            "configuration_hash_before": "synthetic",
            "configuration_hash_after": "synthetic",
            "cases": [{"case": i, "passed": True} for i in range(1, 8)],
            "kernel_receipt_sha256": kernel_hash,
            "attempt_ledger_sha256": {
                p.name: sha(p.read_bytes()) for p in state.glob("attempt-*.json")
            },
        },
    )
    # Twenty independently parsed, long paragraphs create twenty extraction batches.
    content = (
        "<html><body>"
        + "".join(
            f"<p>Customer demand remained resilient for synthetic segment {i}. "
            + "Deployment timing depends on available capacity. " * 200
            + "</p>"
            for i in range(20)
        )
        + "</body></html>"
    ).encode()
    source_hash = sha(content)
    doc = {
        "source_document_id": 101,
        "source_hash": source_hash,
        "document_type": "SEC primary filing",
        "source_url": "https://example.test/synthetic-only",
        "tier": 1,
        "published_at": "2022-08-01T10:00:00+00:00",
        "available_at": "2022-08-01T10:00:00+00:00",
    }
    blocks, _ = runner.source_blocks(
        SimpleNamespace(id=101, content_hash=source_hash, document_type=doc["document_type"]),
        content,
    )
    blocks = [
        {**b, **{k: doc[k] for k in ("tier", "published_at", "available_at")}} for b in blocks
    ]
    assert len(list(runner.chunks(blocks))) == 20
    prepared = {
        "quant_context": {
            "quarter": "FY2023-Q2",
            "information_cutoff": "2022-08-02T10:00:00+00:00",
            "anomaly_codes": [],
        },
        "sources": {"documents": [doc], "blocks": blocks},
    }
    runner.init_candidate_database(database)
    ids = []
    for method in ("B", "C"):

        class Provider:
            def request(self, stage, exact, selected_method=method):
                output = SyntheticProvider().request(stage, exact)["structured_output"]
                if stage == "extract":
                    output["evidence"][0]["span"] = output["evidence"][0]["span"][:150]
                return recorded_response(stage, selected_method, exact, output)

        result = runner._method_engine(
            "method_" + method.lower(),
            runner.build_method_payloads("FY2023-Q2")["method_" + method.lower()],
            Provider(),
            prepared,
            database,
            source_contents={source_hash: content},
            execution_mode="BOUNDED_LIVE_CANDIDATE_V2",
        )
        assert result["status"] == "COMPLETED"
        ids.append(result["run_id"])
    return verifier, database, ids, root


def test_live_mode_requires_all_bound_receipts_and_full_admission_replay(bound_pair):
    verifier, database, ids, root = bound_pair
    before = database.read_bytes()
    assert verifier.verify(database, ids)["lineage_status"] == "INCONSISTENT"
    result = verifier.verify(database, ids, execution_root=root)
    assert result["lineage_status"] == "CONSISTENT", result
    assert result["quality_verdict"] == "UNSCORED" and not result["promotion_ready"]
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    "fault", ["stream", "cleanup", "approval", "extra_attempt", "lock", "kernel", "db_response"]
)
def test_live_lineage_refuses_missing_or_changed_execution_evidence(bound_pair, fault):
    verifier, database, ids, root = bound_pair
    if fault == "stream":
        (root / "research/call-0008/stdout.jsonl").write_text("changed")
    elif fault == "cleanup":
        path = root / "research/call-0008/result.json"
        result = json.loads(path.read_bytes())
        result["group_absent"] = False
        write(path, result)
        ledger = root / "shared-state/attempt-0008.json"
        record = json.loads(ledger.read_bytes())
        record["result_sha256"] = sha(canonical(result).encode())
        write(ledger, record)
    elif fault == "approval":
        (root / "research/approval.json").unlink()
    elif fault == "extra_attempt":
        write(root / "shared-state/attempt-0052.json", {"synthetic_extra": True})
    elif fault == "lock":
        (root / "shared-state/global-active.lock").write_text("unresolved")
    elif fault == "kernel":
        path = root / "kernel-probe/receipt.json"
        receipt = json.loads(path.read_bytes())
        receipt["cases"]["outside_read"]["control"]["exit_code"] = 1
        write(path, receipt)
    else:
        with sqlite3.connect(database) as connection:
            raw = json.loads(
                connection.execute(
                    "SELECT raw_response FROM s2_provider_calls WHERE id=1"
                ).fetchone()[0]
            )
            raw["execution_metadata"]["execution_contract_hash"] = "unbound"
            runner = load("run_fsi_s2_experiment")
            connection.execute(
                "UPDATE s2_provider_calls SET raw_response=?, response_hash=? WHERE id=1",
                (json.dumps(raw), runner.digest(raw)),
            )
    assert verifier.verify(database, ids, execution_root=root)["lineage_status"] == "INCONSISTENT"
