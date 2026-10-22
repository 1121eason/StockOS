"""Read-only V2 receipt binding for the completed, bounded NVDA Q2 pair.

These are recorded execution observations, not model-quality or human approval.
The admission verifier independently replays every response against the database.
"""

import importlib.util
import json
from pathlib import Path

from valuation_engine.ai.native_preflight import canonical, sha
from valuation_engine.ai.quarter_runtime import CLI_VERSION, CONTRACT_HASH, MODEL, approved_failure


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    require(not path.is_symlink() and not path.parent.is_symlink(), "Symlink receipt refused")
    return json.loads(path.read_bytes())


def verify(root, database):
    root = root.resolve(strict=True)
    state, research = root / "shared-state", root / "research"
    require(database.resolve() == research / "candidate.db", "Candidate and receipts differ")
    require(not (state / "global-active.lock").exists(), "Execution is still active or unresolved")
    approval = read(research / "approval.json")
    require(
        approval.get("contract_hash") == CONTRACT_HASH
        and approval.get("decision") == "APPROVED_BY_USER"
        and approval.get("user_instruction")
        and approval.get("shared_state_root") == str(state),
        "Execution approval binding changed",
    )
    recovered = approved_failure(state, approval)
    extra = int(recovered is not None)
    paths = sorted(state.glob("attempt-*.json"))
    require(len(paths) == 51 + extra, "Completed pair must retain every bounded launch")
    diagnostic = root / ("diagnostic-recovery" if recovered else "diagnostic")
    isolation = read(diagnostic / "isolation.json")
    spec = importlib.util.spec_from_file_location(
        "kernel_receipt_validator", Path(__file__).with_name("run_nvda_q2_candidate.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    kernel_hash = module.validate_kernel(root / "kernel-probe/receipt.json")
    require(
        isolation.get("contract_hash") == CONTRACT_HASH
        and isolation.get("status") == "PASS"
        and isolation.get("diagnostic_attempts") == 7
        and isolation.get("gates") == {f"C{i}": "PASS" for i in range(1, 13)}
        and isolation.get("configuration_hash_before") == isolation.get("configuration_hash_after")
        and isolation.get("cases") == [{"case": i, "passed": True} for i in range(1, 8)],
        "Complete isolation evidence required",
    )
    require(
        isolation.get("kernel_receipt_sha256") == kernel_hash
        and all(
            read(folder / "kernel-binding.json").get("kernel_receipt_sha256") == kernel_hash
            for folder in (diagnostic, research)
        ),
        "Kernel isolation binding changed",
    )
    calls = {}
    for index, path in enumerate(paths, 1):
        record = read(path)
        require(
            path.name == f"attempt-{index:04d}.json" and record.get("index") == index,
            "Attempt sequence changed",
        )
        if index <= 7 + extra:
            require(
                isolation.get("attempt_ledger_sha256", {}).get(path.name) == sha(path.read_bytes()),
                "Isolation ledger binding changed",
            )
        if path == recovered:
            continue
        is_diagnostic = index <= 7 + extra
        call_index = index - 7 - extra
        method = None if is_diagnostic else "B" if call_index <= 22 else "C"
        offset = (call_index - 1) % 22
        stage = (
            f"isolation_{index - extra}"
            if is_diagnostic
            else "extract"
            if offset < 20
            else "synthesize"
            if offset == 20
            else "challenge"
        )
        require(
            record.get("contract_hash") == CONTRACT_HASH
            and record.get("status") == "COMPLETED"
            and record.get("cleanup") == "CLEAN"
            and record.get("phase") == ("diagnostic" if is_diagnostic else "research")
            and record.get("method") == method
            and record.get("stage") == stage,
            "Execution status, identity or stage changed",
        )
        directory = (diagnostic if is_diagnostic else research) / f"call-{index:04d}"
        request, result = read(directory / "request.json"), read(directory / "result.json")
        require(
            sha(canonical(request).encode()) == record.get("request_hash")
            and sha(canonical(result).encode()) == record.get("result_sha256"),
            "Request or response binding changed",
        )
        for name in ("stdout.jsonl", "stderr.txt"):
            stream = directory / name
            require(
                not stream.is_symlink()
                and sha(stream.read_bytes()) == result.get(name + "_sha256"),
                "Original execution stream changed",
            )
        require(
            result.get("group_absent") is True
            and result.get("runner_signals") == []
            and result.get("exit_code") == 0
            and result.get("turn_completed") is True
            and result.get("failure") is None
            and result.get("remaining_observed_descendants") == []
            and result.get("workspace_files_after") == ["schema.json", "system.md"]
            and result.get("requested_model") == MODEL
            and result.get("actual_model") is None,
            "Execution or cleanup is not complete",
        )
        if is_diagnostic:
            require(
                result.get("structured_output") == {"answer": "unavailable"}, "Isolation failed"
            )
        else:
            calls[call_index] = {
                "method": method,
                "stage": stage,
                "request": request,
                "response": {
                    "structured_output": result["structured_output"],
                    "response_model": None,
                    "raw_response": result,
                    "execution_metadata": {
                        "provider_execution_status": "completed",
                        "model_identity_status": "REQUESTED_ONLY",
                        "requested_model": MODEL,
                        "cli_version": CLI_VERSION,
                        "execution_contract_hash": CONTRACT_HASH,
                    },
                },
            }
    require(len(calls) == 44, "Incomplete research pair")
    return calls
