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
NAMES = ("quarterly-valuation-engine-m4-source.zip", "nvda-m4-review-data.zip")


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
    original_is_file = Path.is_file

    def relocated_only(path):
        return (
            False
            if path.is_absolute() and path.is_relative_to(original_root)
            else original_is_file(path)
        )

    def no_network(*args, **kwargs):
        raise AssertionError("Offline verification attempted network access")

    gates = []
    with (
        patch.object(Path, "is_file", relocated_only),
        patch.object(socket.socket, "connect", no_network),
    ):
        with Session(engine("sqlite:///data/qve.db")) as db:
            sources = list(db.scalars(select(SourceDocument)))
            for source in sources:
                assert hashlib.sha256(read_document(source)).hexdigest() == source.content_hash
        for quarter in ("FY2023-Q2", "FY2024-Q2", "FY2027-Q2"):
            result = CliRunner().invoke(
                app, ["ai-analyze", "--ticker", "NVDA", "--quarter", quarter, "--prepare-only"]
            )
            assert result.exit_code == 0, (result.output[-1000:], str(result.exception))
            expected = json.loads(Path(f"data/m4/report/{quarter}-context.json").read_text())
            assert json.loads(result.output) == expected
            gates.append(
                {"quarter": quarter, "prepared_context_equal": True, "live_ai_result": False}
            )
        result = CliRunner().invoke(app, ["research-view", "--ticker", "NVDA"])
        assert result.exit_code == 0, (result.output[-1000:], str(result.exception))
        combined = json.loads(result.output)
        assert combined["ai"] == {"status": "unavailable"}
        assert all(
            k in combined["regime"]
            for k in (
                "confirmed_regime",
                "candidate_regime",
                "transition_status",
                "probabilities",
                "cycle_score",
            )
        )
    assert counts() == before
    return {
        "network_blocked": True,
        "original_source_paths_blocked": True,
        "relocated_import_verified": True,
        "source_hashes_verified": len(sources),
        "database_integrity": "PASS",
        "all_counts_unchanged": True,
        "combined_quant_view_without_ai": "PASS",
        "gates": gates,
        "note": "Offline context preparation only; no live AI results or semantic validation claimed",
    }


def main():
    receipt = json.loads((ROOT / "artifacts/m4-checksums.json").read_text())
    verified = {}
    with tempfile.TemporaryDirectory(prefix="qve-m4-offline-") as directory:
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
            [sys.executable, "scripts/verify_m4_bundle.py", "--child", str(ROOT)],
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
    (ROOT / "artifacts/m4-extraction-validation.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        print(json.dumps(child(Path(sys.argv[2]))))
    else:
        main()
