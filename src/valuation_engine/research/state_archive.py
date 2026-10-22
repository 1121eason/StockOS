"""Consistent private backups and non-destructive restores of product state."""

import json
import re
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from valuation_engine.research.product_store import ProductStore
from valuation_engine.research.workbench import file_hash

VERSION = "StockOSStateBackupV1"


def references(connection):
    raw, research = set(), set()
    for row in connection.execute("SELECT * FROM artifacts"):
        record = ProductStore._artifact(row)
        payload = record["payload"]
        if record["kind"] in ("source_document", "source_index"):
            raw.add(payload["source_hash"])
        if record["kind"] == "research" and payload.get("database_ref"):
            research.add(payload["database_ref"])
            raw.update(payload["database_source_hashes"])
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in raw | research):
        raise ValueError("archive_source_hash")
    return sorted(raw), sorted(research)


def inspect_state(root: Path) -> list[str]:
    """Validate the copied database and the raw bytes referenced by its snapshot."""
    path = root / "operations.sqlite"
    if path.is_symlink() or (root / "raw").is_symlink():
        raise ValueError("archive_symlink")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    hashes = []
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("archive_integrity")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("archive_schema_version")
        hashes, databases = references(connection)
        for identity in databases:
            path = root / "research" / (identity + ".sqlite")
            if (root / "research").is_symlink() or path.is_symlink() or file_hash(path) != identity:
                raise ValueError("archive_research_database_hash")
        missing = connection.execute(
            "SELECT COUNT(*) FROM pointers p LEFT JOIN artifacts a ON p.artifact_id=a.id "
            "WHERE a.id IS NULL"
        ).fetchone()[0]
        if missing:
            raise ValueError("archive_broken_pointer")
    finally:
        connection.close()
    for identity in hashes:
        source = root / "raw" / identity
        if source.is_symlink() or file_hash(source) != identity:
            raise ValueError("archive_raw_mismatch")
    return sorted(hashes)


def _destination(source: Path, destination: Path):
    if destination.exists() or destination.is_symlink():
        raise ValueError("archive_destination_exists")
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("archive_must_be_separate")
    destination.parent.mkdir(parents=True, exist_ok=True)


def backup_state(root: Path, destination: Path) -> dict:
    root, destination = root.resolve(), destination.resolve()
    _destination(root, destination)
    with tempfile.TemporaryDirectory(prefix=".stockos-backup-", dir=destination.parent) as temp:
        staging = Path(temp) / "backup"
        (staging / "raw").mkdir(parents=True)
        source = sqlite3.connect((root / "operations.sqlite").as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(staging / "operations.sqlite")
        try:
            source.backup(target)
            target.row_factory = sqlite3.Row
            hashes, databases = references(target)
            for identity in hashes:
                raw = root / "raw" / identity
                if raw.is_symlink():
                    raise ValueError("archive_symlink")
                shutil.copyfile(raw, staging / "raw" / identity)
            for identity in databases:
                raw = root / "research" / (identity + ".sqlite")
                if (root / "research").is_symlink() or raw.is_symlink():
                    raise ValueError("archive_symlink")
                (staging / "research").mkdir(exist_ok=True)
                shutil.copyfile(raw, staging / "research" / raw.name)
        finally:
            source.close()
            target.close()
        hashes = inspect_state(staging)
        manifest = {
            "version": VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "database_sha256": file_hash(staging / "operations.sqlite"),
            "source_hashes": hashes,
            "research_databases": databases,
            "classification": "private_product_state",
        }
        (staging / "backup-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        staging.rename(destination)
    return manifest


def restore_state(backup: Path, destination: Path) -> dict:
    backup, destination = backup.resolve(), destination.resolve()
    _destination(backup, destination)
    manifest = json.loads((backup / "backup-manifest.json").read_text())
    if manifest.get("version") != VERSION:
        raise ValueError("unsupported_archive")
    if file_hash(backup / "operations.sqlite") != manifest["database_sha256"]:
        raise ValueError("archive_database_hash")
    if inspect_state(backup) != manifest["source_hashes"]:
        raise ValueError("archive_source_list")
    with tempfile.TemporaryDirectory(prefix=".stockos-restore-", dir=destination.parent) as temp:
        staging = Path(temp) / "state"
        (staging / "raw").mkdir(parents=True)
        shutil.copyfile(backup / "operations.sqlite", staging / "operations.sqlite")
        for identity in manifest["source_hashes"]:
            shutil.copyfile(backup / "raw" / identity, staging / "raw" / identity)
        for identity in manifest.get("research_databases", []):
            if not re.fullmatch(r"[0-9a-f]{64}", identity):
                raise ValueError("archive_source_hash")
            (staging / "research").mkdir(exist_ok=True)
            shutil.copyfile(
                backup / "research" / (identity + ".sqlite"),
                staging / "research" / (identity + ".sqlite"),
            )
        if file_hash(staging / "operations.sqlite") != manifest["database_sha256"]:
            raise ValueError("restore_database_hash")
        inspect_state(staging)
        staging.rename(destination)
    return manifest
