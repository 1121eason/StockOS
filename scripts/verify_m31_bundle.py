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
NAMES = ("quarterly-valuation-engine-m31-source.zip", "nvda-m31-review-data.zip")


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
    states = json.loads(Path("data/m31/report/history.json").read_text())["states"]
    selected = [s for s in states if s["quarter"] in ("FY2023-Q3", "FY2024-Q1", "FY2027-Q2")]
    assert len(selected) == 3
    contracts = json.loads(Path("data/m31/report/history.json").read_text())["contracts"]
    expected_contracts = {c["quarter"]: c for c in contracts}
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
        for state in selected:
            result = CliRunner().invoke(
                app, ["regime", "--ticker", "NVDA", "--as-of", state["as_of"], "--json-output"]
            )
            assert result.exit_code == 0, (result.output[-2000:], str(result.exception))
            if state == selected[0]:
                readable = CliRunner().invoke(
                    app, ["regime", "--ticker", "NVDA", "--as-of", state["as_of"]]
                )
                assert readable.exit_code == 0, readable.output
                assert "Primary reasons (deterministic rules)" in readable.output
                assert "Transition: STABLE" in readable.output
                assert "History sufficiency" in readable.output
                assert "Evidence" in readable.output
            actual = json.loads(result.output)
            assert actual == expected_contracts[state["quarter"]], state["quarter"]
            results.append(
                {
                    "quarter": state["quarter"],
                    "all_state_fields_equal": True,
                    "primary_regime": state["primary_regime"],
                    "candidate_regime": state["candidate_regime"],
                }
            )
    assert counts() == before
    return {
        "human_readable_reasons_verified": True,
        "relocated_import_verified": True,
        "network_blocked": True,
        "original_source_paths_blocked": True,
        "source_hashes_verified": len(sources),
        "database_integrity": "PASS",
        "all_counts_unchanged": True,
        "gates": results,
    }


def main():
    receipt = json.loads((ROOT / "artifacts/m31-checksums.json").read_text())
    verified = {}
    with tempfile.TemporaryDirectory(prefix="qve-m31-offline-") as directory:
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
            [sys.executable, "scripts/verify_m31_bundle.py", "--child", str(ROOT)],
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
    (ROOT / "artifacts/m31-extraction-validation.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        print(json.dumps(child(Path(sys.argv[2]))))
    else:
        main()
