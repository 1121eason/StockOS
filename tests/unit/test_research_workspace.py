"""Offline import contract, temporal isolation, canonical DCF and durable-store boundaries."""

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path

import pytest

from valuation_engine.research.dcf import DCFModel
from valuation_engine.research.numbers import MarketEquityShares
from valuation_engine.research.workspace import (
    CLASSIFICATION,
    import_bundle,
    list_runs,
    load_run,
    parse_bundle_json,
)


def sample_bundle():
    def item(value):
        return {
            "value": value,
            "source_ids": ["issuer_2024"],
            "available_at": "2024-06-01T00:00:00Z",
        }

    return {
        "schema_version": 1,
        "ticker": "DEMO",
        "name": "Synthetic Company",
        "as_of": "2024-06-02T00:00:00Z",
        "data_kind": "synthetic",
        "sources": [
            {
                "id": "issuer_2024",
                "url": "https://example.com/filing",
                "published_at": "2024-06-01T00:00:00Z",
                "retrieved_at": "2025-01-01T00:00:00Z",
                "sha256": "a" * 64,
            }
        ],
        "inputs": {
            "cash": item("100"),
            "debt": item("200"),
            "shares": item("100"),
            "wacc": item("0.10"),
            "terminal_growth": item("0.02"),
            "forecast_cashflows": [item(str(v)) for v in (100, 110, 120, 130, 140)],
        },
        "assumptions": {
            "classification": CLASSIFICATION,
            "rationale": "Reconstructed annual FCFF assumptions in absolute USD.",
        },
    }


def test_canonical_dcf_full_result_and_round_trip(tmp_path):
    bundle = sample_bundle()
    db = tmp_path / "research.sqlite"
    result = import_bundle(db, bundle)
    assert result["bundle"] == bundle
    assert result["mode"] == "research"
    assert result["classification"] == CLASSIFICATION
    assert result["source_verification"] == "asserted_unverified"
    assert result["formal_decision"] == "withheld"
    assert result["units"]["monetary"] == "USD"
    assert result["ticker"] == "DEMO"
    assert result["run_id"] == "rw1_" + result["input_hash"]
    assert result["generated_at"] > bundle["as_of"]
    expected = DCFModel().value(
        [Decimal(v) for v in (100, 110, 120, 130, 140)],
        Decimal(100),
        Decimal(200),
        MarketEquityShares(Decimal(100)),
        Decimal("0.10"),
        Decimal("0.02"),
    )
    assert float(result["valuation"]["per_share"]) == pytest.approx(float(expected["per_share"]))
    assert result["valuation"]["parameters"]["wacc"] == "0.10"
    assert result["valuation"]["cashflows"] == ["100", "110", "120", "130", "140"]
    assert [row["name"] for row in result["valuation"]["scenarios"]] == [
        "higher_wacc",
        "base",
        "lower_wacc",
    ]
    assert list_runs(db) == [result]
    assert load_run(db, result["run_id"]) == result
    assert (
        "valuation_engine.db" not in Path("src/valuation_engine/research/workspace.py").read_text()
    )


def test_immutable_replay_and_distinct_inputs(tmp_path):
    db = tmp_path / "research.sqlite"
    bundle = sample_bundle()
    original = import_bundle(db, bundle)
    # Key order does not affect identity; replay retains the original generation time.
    assert import_bundle(db, dict(reversed(list(bundle.items())))) == original
    bundle["inputs"]["cash"]["value"] = "101"
    newer = import_bundle(db, bundle)
    assert newer["run_id"] != original["run_id"]
    assert len(list_runs(db)) == 2
    assert load_run(db, original["run_id"]) == original
    with sqlite3.connect(db) as connection:
        for statement in (
            "DELETE FROM research_runs",
            "UPDATE research_runs SET run_id='oops'",
            "DELETE FROM workspace_meta",
            "UPDATE workspace_meta SET identity='oops'",
            "INSERT OR REPLACE INTO research_runs SELECT * FROM research_runs",
            "INSERT OR REPLACE INTO workspace_meta SELECT * FROM workspace_meta",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(statement)
    # The returned object does not alias stored input or a later read.
    newer["bundle"]["inputs"]["cash"]["value"] = "9999"
    assert load_run(db, newer["run_id"])["bundle"]["inputs"]["cash"]["value"] == "101"


def test_concurrent_replay_is_idempotent(tmp_path):
    db = tmp_path / "research.sqlite"
    original = import_bundle(db, sample_bundle())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: import_bundle(db, sample_bundle()), range(8)))
    assert all(result == original for result in results)
    assert list_runs(db) == [original]


@pytest.mark.parametrize("field", ["cash", "debt", "shares", "wacc", "terminal_growth", "cashflow"])
def test_missing_values_unavailable_never_imputed(tmp_path, field):
    bundle = sample_bundle()
    item = (
        bundle["inputs"]["forecast_cashflows"][2]
        if field == "cashflow"
        else bundle["inputs"][field]
    )
    item.update(value=None, source_ids=[], available_at=None)
    result = import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["valuation"]["status"] == "unavailable"
    assert result["valuation"]["reason"] == "missing_required_inputs"
    assert "per_share" not in result["valuation"]
    assert all(row["status"] == "unavailable" for row in result["valuation"]["scenarios"])


def test_zero_is_preserved_and_zero_equity_is_available(tmp_path):
    bundle = sample_bundle()
    # Five annual 100 flows with zero terminal growth and 10% WACC have EV exactly 1000.
    bundle["inputs"]["cash"]["value"] = 0
    bundle["inputs"]["debt"]["value"] = 1000
    bundle["inputs"]["terminal_growth"]["value"] = 0
    for item in bundle["inputs"]["forecast_cashflows"]:
        item["value"] = 100
    result = import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["valuation"]["status"] == "available"
    assert abs(Decimal(result["valuation"]["per_share"])) < Decimal("1e-40")
    assert result["valuation"]["parameters"]["cash"] == "0"
    bundle["inputs"]["debt"]["value"] = 2000
    negative = import_bundle(tmp_path / "research.sqlite", bundle)
    assert Decimal(negative["valuation"]["per_share"]) < 0
    assert negative["valuation"]["negative_equity_warning"] is True
    bundle["inputs"]["cash"]["value"] = 0
    bundle["inputs"]["debt"]["value"] = 0
    assert import_bundle(tmp_path / "research.sqlite", bundle)["valuation"]["status"] == "available"


@pytest.mark.parametrize(
    "field,value",
    [
        ("cash", -1),
        ("debt", -1),
        ("shares", 0),
        ("shares", -1),
        ("wacc", 0),
        ("wacc", "0.02"),
        ("terminal_growth", -1),
        ("terminal_growth", "0.10"),
    ],
)
def test_invalid_economic_inputs_are_explicitly_unavailable(tmp_path, field, value):
    bundle = sample_bundle()
    bundle["inputs"][field]["value"] = value
    result = import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["valuation"]["status"] == "unavailable"
    assert "per_share" not in result["valuation"]


def test_negative_interim_cashflow_allowed_terminal_nonpositive_unavailable(tmp_path):
    bundle = sample_bundle()
    bundle["inputs"]["forecast_cashflows"][0]["value"] = -100
    assert import_bundle(tmp_path / "research.sqlite", bundle)["valuation"]["status"] == "available"
    for value in (0, -100):
        bundle["inputs"]["forecast_cashflows"][-1]["value"] = value
        result = import_bundle(tmp_path / "research.sqlite", bundle)
        assert result["valuation"]["status"] == "unavailable"


@pytest.mark.parametrize(
    "bad",
    [
        True,
        "NaN",
        "Infinity",
        float("nan"),
        float("inf"),
        "",
        "1_000",
        "+1",
        " 1 ",
        "1e10000",
        [],
        {},
    ],
)
def test_malformed_numbers_rejected_before_database_creation(tmp_path, bad):
    bundle = sample_bundle()
    bundle["inputs"]["cash"]["value"] = bad
    db = tmp_path / "research.sqlite"
    with pytest.raises(ValueError):
        import_bundle(db, bundle)
    assert not db.exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.update(extra="unknown"),
        lambda b: b.update(schema_version=True),
        lambda b: b.update(schema_version=2),
        lambda b: b.update(ticker="../../bad"),
        lambda b: b.update(name=""),
        lambda b: b.update(data_kind="historical_oos"),
        lambda b: b.update(as_of="2024-06-02T00:00:00"),
        lambda b: b.update(as_of="2999-01-01T00:00:00Z"),
        lambda b: b["assumptions"].update(classification="historical_oos"),
        lambda b: b["assumptions"].update(rationale=""),
        lambda b: b["sources"][0].update(id="bad/id"),
        lambda b: b["sources"].append(copy.deepcopy(b["sources"][0])),
        lambda b: b["sources"][0].update(sha256="bad"),
        lambda b: b["sources"][0].update(url="file:///etc/passwd"),
        lambda b: b["sources"][0].update(url="https://secret:password@example.com"),
        lambda b: b["sources"][0].update(extra=True),
        lambda b: b["sources"][0].update(published_at="2024-06-03T00:00:00Z"),
        lambda b: b["sources"][0].update(retrieved_at="2024-05-01T00:00:00Z"),
        lambda b: b["sources"][0].update(retrieved_at="2999-01-01T00:00:00Z"),
        lambda b: b["inputs"].update(extra=True),
        lambda b: b["inputs"]["cash"].update(source_ids=["unknown"]),
        lambda b: b["inputs"]["cash"].update(source_ids=["issuer_2024", "issuer_2024"]),
        lambda b: b["inputs"]["cash"].update(source_ids=[]),
        lambda b: b["inputs"]["cash"].update(available_at=None),
        lambda b: b["inputs"]["cash"].update(available_at="2024-06-03T00:00:00Z"),
        lambda b: b["inputs"]["cash"].update(available_at="2024-05-01T00:00:00Z"),
        lambda b: b["inputs"]["cash"].update(available_at="2024-06-01"),
        lambda b: b["inputs"]["cash"].update(original_vintage=True),
        lambda b: b["inputs"]["forecast_cashflows"].pop(),
    ],
)
def test_strict_schema_and_temporal_leakage_rejected(tmp_path, change):
    bundle = sample_bundle()
    change(bundle)
    db = tmp_path / "research.sqlite"
    with pytest.raises(ValueError):
        import_bundle(db, bundle)
    assert not db.exists()


def test_timezone_comparison_and_late_retrieval_are_not_original_vintage(tmp_path):
    bundle = sample_bundle()
    bundle["as_of"] = "2024-06-01T01:00:00+01:00"
    bundle["sources"][0]["published_at"] = "2024-05-31T20:00:00-04:00"
    result = import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["classification"] == CLASSIFICATION
    assert result["bundle"]["sources"][0]["retrieved_at"] > result["as_of"]
    bundle["inputs"]["cash"]["available_at"] = "2024-06-01T00:01:00Z"
    with pytest.raises(ValueError, match="temporal leakage"):
        import_bundle(tmp_path / "research.sqlite", bundle)


def test_json_duplicate_keys_and_nonfinite_constants_rejected():
    for value in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', "[]", "null"):
        with pytest.raises(ValueError):
            parse_bundle_json(value)


def test_read_apis_do_not_create_database_or_parent(tmp_path):
    db = tmp_path / "absent-parent" / "research.sqlite"
    assert list_runs(db) == []
    with pytest.raises(ValueError, match="not found"):
        load_run(db, "rw1_" + "a" * 64)
    assert not db.parent.exists()
    for value in ("", ":memory:", "file:/tmp/research.sqlite", tmp_path):
        with pytest.raises(ValueError):
            list_runs(value)
    with pytest.raises(ValueError, match="Invalid research run_id"):
        load_run(db, "' OR 1=1")


@pytest.mark.parametrize("kind", ["empty", "unrelated", "corrupt", "unexpected_table"])
def test_rejects_unrelated_preexisting_and_corrupt_databases_without_mutation(tmp_path, kind):
    db = tmp_path / "formal.sqlite"
    if kind == "empty":
        db.touch()
    elif kind == "unrelated":
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE formal_decisions (id INTEGER PRIMARY KEY)")
    elif kind == "corrupt":
        db.write_bytes(b"Not a SQLite database")
    else:
        import_bundle(db, sample_bundle())
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE formal_decisions (id INTEGER PRIMARY KEY)")
    before = db.read_bytes()
    with pytest.raises(ValueError):
        import_bundle(db, sample_bundle())
    with pytest.raises(ValueError):
        list_runs(db)
    assert db.read_bytes() == before


def test_sqlite_failure_is_valueerror(tmp_path):
    with pytest.raises(ValueError, match="import failed"):
        import_bundle(tmp_path / "missing-parent" / "research.sqlite", sample_bundle())


def test_schema_and_result_corruption_detected(tmp_path):
    db = tmp_path / "research.sqlite"
    result = import_bundle(db, sample_bundle())
    with sqlite3.connect(db) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='research_runs_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER research_runs_no_update")
        connection.execute("UPDATE research_runs SET result_hash=?", ("0" * 64,))
        connection.execute(trigger)
    with pytest.raises(ValueError, match="hash mismatch"):
        load_run(db, result["run_id"])
    with pytest.raises(ValueError, match="hash mismatch"):
        import_bundle(db, sample_bundle())


def test_forged_result_with_recomputed_hash_is_detected(tmp_path):
    db = tmp_path / "research.sqlite"
    result = import_bundle(db, sample_bundle())
    with sqlite3.connect(db) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='research_runs_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER research_runs_no_update")
        stored = json.loads(
            connection.execute("SELECT result_json FROM research_runs").fetchone()[0]
        )
        stored["formal_decision"] = "buy"
        encoded = json.dumps(stored, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        connection.execute(
            "UPDATE research_runs SET result_json=?,result_hash=?",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest()),
        )
        connection.execute(trigger)
    with pytest.raises(ValueError, match="content or identity mismatch"):
        load_run(db, result["run_id"])


def test_decimal_caller_context_does_not_change_results(tmp_path):
    first = import_bundle(tmp_path / "first.sqlite", sample_bundle())
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        second = import_bundle(tmp_path / "second.sqlite", sample_bundle())
        assert load_run(tmp_path / "first.sqlite", first["run_id"]) == first
    assert first["valuation"] == second["valuation"]


def test_cli_import_list_show_and_error(tmp_path):
    db = tmp_path / "research.sqlite"
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(sample_bundle()))
    command = [sys.executable, "scripts/import_research_workspace.py", "--db", str(db)]
    imported = subprocess.run([*command, "import", str(bundle)], capture_output=True, text=True)
    assert imported.returncode == 0, imported.stderr
    result = json.loads(imported.stdout)
    listed = subprocess.run([*command, "list"], capture_output=True, text=True)
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout) == [result]
    shown = subprocess.run([*command, "show", result["run_id"]], capture_output=True, text=True)
    assert json.loads(shown.stdout) == result
    bundle.write_text('{"schema_version":1,"schema_version":2}')
    invalid = subprocess.run([*command, "import", str(bundle)], capture_output=True, text=True)
    assert invalid.returncode == 2
    assert "Duplicate JSON key" in invalid.stderr
    assert list_runs(db) == [result]


def test_cli_runs_without_pythonpath_from_outside_repository(tmp_path):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    script = Path(__file__).resolve().parents[2] / "scripts/import_research_workspace.py"
    result = subprocess.run(
        [sys.executable, str(script), "--db", str(tmp_path / "absent.sqlite"), "list"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    assert not (tmp_path / "absent.sqlite").exists()


def test_non_text_database_payload_is_reported_as_corruption(tmp_path):
    db = tmp_path / "research.sqlite"
    import_bundle(db, sample_bundle())
    with sqlite3.connect(db) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='research_runs_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER research_runs_no_update")
        connection.execute("UPDATE research_runs SET result_json=?", (b"bad payload",))
        connection.execute(trigger)
    with pytest.raises(ValueError, match="invalid column types"):
        list_runs(db)


def test_symlink_database_is_rejected(tmp_path):
    db = tmp_path / "research.sqlite"
    import_bundle(db, sample_bundle())
    link = tmp_path / "link.sqlite"
    link.symlink_to(db)
    with pytest.raises(ValueError, match="symbolic link"):
        list_runs(link)
    with pytest.raises(ValueError, match="symbolic link"):
        import_bundle(link, sample_bundle())


@pytest.mark.parametrize(
    "value", ["0e-1000000", "-0e-1000000", "0e1000000", "0e-101", "0e101", "1e-101"]
)
def test_extreme_exponents_including_zero_rejected_before_storage(tmp_path, value):
    bundle = sample_bundle()
    bundle["inputs"]["cash"]["value"] = value
    database = tmp_path / "research.sqlite"
    with pytest.raises(ValueError):
        import_bundle(database, bundle)
    assert not database.exists()


@pytest.mark.parametrize("value", ["0e-100", "-0e-100", "0e100", "1e-100", "1e100"])
def test_bounded_exponent_boundary_round_trip(tmp_path, value):
    bundle = sample_bundle()
    bundle["inputs"]["cash"]["value"] = value
    database = tmp_path / "research.sqlite"
    result = import_bundle(database, bundle)
    assert len(result["valuation"]["parameters"]["cash"]) <= 103
    assert Decimal(result["valuation"]["parameters"]["cash"]) == Decimal(value)
    assert load_run(database, result["run_id"]) == result


@pytest.mark.parametrize("value", ["0e-1000000", "0e1000000", "1e-1000000", "1e1000000"])
def test_serializer_checks_output_bound_before_fixed_point_expansion(value):
    from valuation_engine.research.workspace import _serial

    with pytest.raises(ValueError, match="bounded serialization"):
        _serial(Decimal(value))
