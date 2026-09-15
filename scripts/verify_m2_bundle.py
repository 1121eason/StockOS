"""Verify packaged hashes and replay three CLI gates offline after relocation."""

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("quarterly-valuation-engine-m2-source.zip", "nvda-m2-review-data.zip")


def counts():
    result = {}
    for name in ("qve", "labels"):
        with sqlite3.connect(f"data/{name}.db") as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                result[f"{name}:{table}"] = db.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
    return result


def child(original_root):
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from typer.testing import CliRunner

    import valuation_engine
    from valuation_engine.cli.main import app
    from valuation_engine.db.schema import SourceDocument
    from valuation_engine.db.session import engine
    from valuation_engine.db.store import read_document

    assert Path(valuation_engine.__file__).resolve().is_relative_to(ROOT)
    before = counts()
    gates = json.loads(Path("data/m2/report/gates.json").read_text())
    selected = [g for g in gates if g["quarter"] in ("FY2022-Q1", "FY2024-Q1", "FY2027-Q2")]
    assert len(selected) == 3
    original_is_file = Path.is_file

    def relocated_only(path):
        return (
            False
            if path.is_absolute() and path.is_relative_to(original_root)
            else original_is_file(path)
        )

    def no_network(*args, **kwargs):
        raise AssertionError("Offline bundle verification attempted network access")

    results = []
    with (
        patch.object(Path, "is_file", relocated_only),
        patch.object(socket.socket, "connect", no_network),
    ):
        with Session(engine("sqlite:///data/qve.db")) as db:
            sources = list(db.scalars(select(SourceDocument)))
            for source in sources:
                assert hashlib.sha256(read_document(source)).hexdigest() == source.content_hash
        for gate in selected:
            at = gate["valuation"]["as_of_timestamp"]
            forecast = CliRunner().invoke(
                app, ["forecast", "--ticker", "NVDA", "--as-of", at, "--json-output"]
            )
            assert forecast.exit_code == 0, (forecast.output[-2000:], str(forecast.exception))
            forecast_data = json.loads(forecast.output)
            valuation = CliRunner().invoke(
                app, ["valuation", "--ticker", "NVDA", "--as-of", at, "--json-output"]
            )
            assert valuation.exit_code == 0, (valuation.output[-2000:], str(valuation.exception))
            value = json.loads(valuation.output)
            assert value == gate["valuation"], gate["quarter"]
            assert forecast_data["run"] == gate["first_tradable_forecast"], gate["quarter"]
            assert forecast_data["periods"] == gate["forecast_periods"], gate["quarter"]
            assert forecast_data["revision"] == gate["revision"], gate["quarter"]
            results.append(
                {
                    "quarter": gate["quarter"],
                    "forecast_run_id": value["forecast_run_id"],
                    "valuation_id": value["id"],
                    "valuation_all_fields_equal": True,
                    "forecast_and_revision_all_fields_equal": True,
                    "forecast_period_count": len(forecast_data["periods"]),
                }
            )
    assert counts() == before
    return {
        "relocated_import_verified": True,
        "network_blocked": True,
        "original_source_paths_blocked": True,
        "source_hashes_verified": len(sources),
        "database_integrity": "PASS",
        "all_counts_unchanged": True,
        "gates": results,
    }


def main():
    receipt = json.loads((ROOT / "artifacts/m2-checksums.json").read_text())
    verified = {}
    with tempfile.TemporaryDirectory(prefix="qve-m2-offline-") as directory:
        for name in NAMES:
            path = ROOT / "artifacts" / name
            assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt[name]["sha256"]
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None
                manifest = json.loads(
                    archive.read(
                        "quarterly-valuation-engine/" + name.removesuffix(".zip") + "-files.json"
                    )
                )
                for item, expected in manifest.items():
                    content = archive.read("quarterly-valuation-engine/" + item)
                    assert hashlib.sha256(content).hexdigest() == expected["sha256"]
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    assert not member_path.is_absolute() and ".." not in member_path.parts
                    assert ".env" not in member_path.parts and "sources" not in member_path.parts
                archive.extractall(directory)
                verified[name] = {
                    "files_verified": len(manifest),
                    "sha256": receipt[name]["sha256"],
                }
        checkout = Path(directory) / "quarterly-valuation-engine"
        result = subprocess.run(
            [sys.executable, "scripts/verify_m2_bundle.py", "--child", str(ROOT)],
            cwd=checkout,
            env={
                **os.environ,
                "PYTHONPATH": str(checkout / "src"),
                "QVE_DATABASE_URL": "sqlite:///data/qve.db",
                "QVE_LABEL_DATABASE_URL": "sqlite:///data/labels.db",
                "QVE_RAW_DIR": "data/raw",
                "SEC_USER_AGENT": "",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        child_result = json.loads(result.stdout)
    output = {"archives": verified, "offline_replay": child_result}
    (ROOT / "artifacts/m2-extraction-validation.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        print(json.dumps(child(Path(sys.argv[2]))))
    else:
        main()
