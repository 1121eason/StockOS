#!/usr/bin/env python3
"""Run bounded offline tests under transport/process/SQLite audit restrictions."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve(strict=True)
    temporary = evidence / "pytest-tmp"
    if temporary.exists():
        parser.error("Use fresh evidence directory; prior test outputs are preserved")
    os.environ.pop("QVE_TEST_POSTGRES_URL", None)
    attempts = {"network": 0, "process": 0, "outside_sqlite": 0, "sqlite_allowed": 0}

    def audit(event, values):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
            attempts["network"] += 1
            raise AssertionError("Network is forbidden in W1 offline verification")
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork"}:
            attempts["process"] += 1
            raise AssertionError("Child processes are forbidden in W1 offline verification")
        if event == "sqlite3.connect":
            value = str(values[0])
            if value != ":memory:":
                path = Path(unquote(urlsplit(value).path) if value.startswith("file:") else value)
                if not path.resolve().is_relative_to(temporary):
                    attempts["outside_sqlite"] += 1
                    raise AssertionError("Only test-temporary SQLite is allowed")
            attempts["sqlite_allowed"] += 1

    # Existing connections would evade connect auditing; none are created before this hook.
    assert sqlite3.sqlite_version
    sys.addaudithook(audit)
    tests = [
        "tests/unit/test_fsi_w1.py",
        "tests/unit/test_fsi_s2_provenance.py",
        "tests/unit/test_fsi_lineage_review.py",
        "tests/unit/test_fsi_cohort_safety.py",
        "tests/unit/test_fsi_s2_offline_verifier.py",
        "tests/unit/test_human_review_tools.py",
        "tests/unit/test_ai_guards.py",
        "tests/integration/test_ai_analyst.py",
    ]
    code = pytest.main(
        [
            *tests,
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(temporary),
            "--junitxml",
            str(evidence / "pytest.xml"),
        ]
    )
    receipt = {
        "pytest_exit_code": int(code),
        "python_version": sys.version,
        "pytest_version": pytest.__version__,
        "sqlite_version": sqlite3.sqlite_version,
        "test_paths": tests,
        "audit": attempts,
        "model_calls": 0,
        "formal_database_opens": 0,
        "scope": "synthetic affected-path tests only; no native provider certification",
        "evidence_basis": "Audit restrictions and deterministic in-memory adapters; no model transport",
    }
    (evidence / "offline-audit.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
