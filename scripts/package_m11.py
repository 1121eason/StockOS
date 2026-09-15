"""Package the M1.1 source and authoritative evidence using an explicit allowlist."""

import hashlib
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts"
PREFIX = "quarterly-valuation-engine/"


def sha(content):
    return hashlib.sha256(content).hexdigest()


def package(name, paths):
    result = {}
    destination = OUTPUT / name
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(paths)):
            assert path.is_file() and not path.is_symlink(), path
            relative = path.relative_to(ROOT).as_posix()
            assert ".env" not in path.parts and "__pycache__" not in path.parts
            if path.suffix == ".db":
                # SQLite backup includes committed WAL contents, if any.
                with tempfile.TemporaryDirectory(prefix="qve-package-") as temporary:
                    backup = Path(temporary) / path.name
                    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as source:
                        with sqlite3.connect(backup) as copy:
                            source.backup(copy)
                            assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                    content = backup.read_bytes()
            else:
                content = path.read_bytes()
            archive.writestr(PREFIX + relative, content)
            result[relative] = {"bytes": len(content), "sha256": sha(content)}
        archive.writestr(
            PREFIX + name.removesuffix(".zip") + "-files.json",
            json.dumps(result, indent=2, sort_keys=True) + "\n",
        )
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for relative, expected in result.items():
            assert sha(archive.read(PREFIX + relative)) == expected["sha256"]
    return {
        "bytes": destination.stat().st_size,
        "sha256": sha(destination.read_bytes()),
        "files": len(result),
        "integrity": "PASS",
    }


def main():
    OUTPUT.mkdir(exist_ok=True)
    verified_exports = json.loads(
        (ROOT / "data/m11/postgresql/dump-restore-validation.json").read_text()
    )
    for name, verification in verified_exports.items():
        assert verification["restored_all_tables_equal"]
        assert verification["restored_trigger_definitions_equal"]
        assert (
            sha((ROOT / f"data/m11/postgresql/{name}.dump").read_bytes())
            == verification["dump_sha256"]
        )
    source = [
        ROOT / name
        for name in (
            "README.md",
            "pyproject.toml",
            "uv.lock",
            ".env.example",
            ".gitignore",
            "alembic.ini",
        )
    ]
    for directory in ("src", "tests", "migrations", "docs", "scripts"):
        source.extend(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
    data = [
        ROOT / "data" / name
        for name in (
            "README.md",
            "qve.db",
            "labels.db",
            "ir-manifest.json",
            "m11/timestamps-manifest.json",
            "m11/splits-manifest.json",
            "m11/price-manifest.json",
            "m11/test-results.txt",
            "m11/lint.txt",
            "m11/format.txt",
            "m11/type-check.txt",
            "m11/backend-parity.json",
            "m11/decimal-migration-audit.json",
            "m11/cli-valuation-example.json",
            "m11/portable-source-validation.json",
        )
    ]
    with sqlite3.connect(f"file:{ROOT / 'data/qve.db'}?mode=ro", uri=True) as db:
        for (digest,) in db.execute("SELECT DISTINCT content_hash FROM source_documents"):
            assert re.fullmatch(r"[0-9a-f]{64}", digest)
            path = ROOT / "data/raw" / digest
            assert sha(path.read_bytes()) == digest
            data.append(path)
    for filename in ("timestamps-manifest.json", "splits-manifest.json", "price-manifest.json"):
        manifest = json.loads((ROOT / "data/m11" / filename).read_text())
        for entry in manifest if isinstance(manifest, list) else [manifest]:
            path = ROOT / entry["path"]
            assert path.is_relative_to(ROOT / "data/m11/external")
            assert sha(path.read_bytes()) == path.name
            data.append(path)
    for directory in ("report", "report-second", "postgresql", "postgresql-second"):
        data.extend((ROOT / "data/m11" / directory).glob("*.json"))
    data.extend(
        ROOT / "data/m11/postgresql" / name
        for name in (
            "test-results.txt",
            "qve_verified.dump",
            "qve_labels.dump",
            "schema.sql",
        )
    )
    assert (ROOT / "data/m11/report/counts.json").read_bytes() == (
        ROOT / "data/m11/report-second/counts.json"
    ).read_bytes()
    result = {
        "quarterly-valuation-engine-m11-source.zip": package(
            "quarterly-valuation-engine-m11-source.zip", source
        ),
        "nvda-m11-review-data.zip": package("nvda-m11-review-data.zip", data),
    }
    (OUTPUT / "m11-checksums.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
