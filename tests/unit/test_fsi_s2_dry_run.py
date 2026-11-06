import importlib.util
import os
from pathlib import Path

ROOT = Path(os.environ.get("PWD", "/Users/eason/Documents/Coding/StockOS"))
spec = importlib.util.spec_from_file_location(
    "run_fsi_s2_experiment", str(ROOT / "scripts/run_fsi_s2_experiment.py")
)
if spec is None or spec.loader is None:
    raise ImportError("Could not load scripts/run_fsi_s2_experiment.py")
s2_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s2_mod)

check_preflight = s2_mod.check_preflight
build_method_payloads = s2_mod.build_method_payloads
init_candidate_database = s2_mod.init_candidate_database
run_dry_run = s2_mod.run_dry_run
MAX_CALLS_PER_METHOD = s2_mod.MAX_CALLS_PER_METHOD


def test_preflight_checks():
    receipt = check_preflight("FY2023-Q2")
    assert receipt["quarter"] == "FY2023-Q2"
    assert receipt["max_calls_per_method"] == MAX_CALLS_PER_METHOD
    assert receipt["preflight_status"] == "PASS"

    raised = False
    try:
        check_preflight("FY2099-Q4")
    except ValueError as e:
        raised = True
        assert "not authorized" in str(e)
    assert raised, "Expected ValueError on unauthorized quarter"


def test_build_method_payloads():
    payloads = build_method_payloads("FY2023-Q2")
    assert "method_b" in payloads
    assert "method_c" in payloads

    b = payloads["method_b"]
    c = payloads["method_c"]

    assert b["method"] == "B"
    assert c["method"] == "C"
    assert b["prompt_version"] == "PromptSetV6"
    assert c["prompt_version"] == "PromptSetV6-FSI"
    assert b["config_hash"] != c["config_hash"]


def test_init_candidate_database(tmp_path=None):
    if tmp_path is None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_candidate.db"
            init_candidate_database(db_path)
            assert db_path.exists()
    else:
        db_path = tmp_path / "test_candidate.db"
        init_candidate_database(db_path)
        assert db_path.exists()


def test_s2_dry_run_execution():
    receipt = run_dry_run("FY2023-Q2")
    assert receipt["mode"] == "DRY_RUN"
    assert receipt["live_api_calls_made"] == 0
    assert receipt["formal_db_modified"] is False
    assert receipt["dry_run_verdict"] == "READY_FOR_AUTHORIZATION"


if __name__ == "__main__":
    test_preflight_checks()
    test_build_method_payloads()
    test_init_candidate_database()
    test_s2_dry_run_execution()
    print("All S2 dry-run unit tests PASSED successfully!")
