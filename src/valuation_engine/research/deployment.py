"""Prepare and validate a private, versioned, read-only deployment seed.

No uploads, credentials, AI calls or writes to the source database. The seed
contains the existing research database and NVDA source bytes required for
subsequent financial rebuilds. It is private data, never an image build input.
"""

import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import Company, SourceDocument
from valuation_engine.research.workbench import (
    build_research,
    file_hash,
    readonly_engine,
    source_preflight,
)

VERSION = "StockOSSeedV1"


def refresh_source_hashes(source_db: Path, raw_dir: Path) -> set[str]:
    """Future forecasts reparse prior IR guidance; package those bytes too."""
    engine = readonly_engine(source_db)
    try:
        with Session(engine, autoflush=False) as db:
            hashes = set(
                db.scalars(
                    select(SourceDocument.content_hash)
                    .join(Company, Company.id == SourceDocument.company_id)
                    .where(
                        Company.ticker == "NVDA",
                        SourceDocument.source_provider.in_(("NVIDIA IR", "SEC")),
                    )
                )
            )
        for identity in hashes:
            path = raw_dir / identity
            if path.is_symlink() or file_hash(path) != identity:
                raise ValueError("seed_source_hash_mismatch")
        return hashes
    finally:
        engine.dispose()


def verify_seed(root: Path) -> dict:
    manifest = json.loads((root / "seed-manifest.json").read_text())
    if manifest.get("version") != VERSION or manifest.get("ticker") != "NVDA":
        raise ValueError("unsupported_seed")
    if source_preflight(root / "qve.db") != manifest["database_sha256"]:
        raise ValueError("seed_database_hash_mismatch")
    hashes = manifest.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or len(set(hashes)) != len(hashes):
        raise ValueError("invalid_source_manifest")
    for value in hashes:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("invalid_source_hash")
        path = root / "raw" / value
        if path.is_symlink() or file_hash(path) != value:
            raise ValueError("seed_source_hash_mismatch")
    return manifest


def prepare_seed(source_db: Path, raw_dir: Path, destination: Path) -> dict:
    source_db, raw_dir, destination = source_db.resolve(), raw_dir.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("seed_destination_already_exists")
    if (
        destination.is_relative_to(raw_dir)
        or raw_dir.is_relative_to(destination)
        or source_db.is_relative_to(destination)
    ):
        raise ValueError("seed_must_be_separate_from_source")
    research = build_research(source_db, raw_dir)
    hashes = sorted(
        {item["sha256"] for item in research["sources"]} | refresh_source_hashes(source_db, raw_dir)
    )
    manifest = {
        "version": VERSION,
        "ticker": "NVDA",
        "database_sha256": research["source_database_sha256"],
        "source_hashes": hashes,
        "current_quarter": research["current"]["quarter"],
        "previous_quarter": research["previous"]["quarter"],
        "prepared_at": datetime.now(UTC).isoformat(),
        "classification": "private_readonly_research_seed",
        "local_login_files_included": False,
        "database_scope": "complete_existing_research_database_copy",
        "source_scope": "NVDA_SEC_AND_IR_INCLUDING_PRIOR_GUIDANCE_FOR_FINANCIAL_REBUILD",
        "historical_records": "preserved_not_revalidated_or_approved_by_this_export",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A failed copy never becomes a usable deployment seed.
    with tempfile.TemporaryDirectory(prefix=".stockos-seed-", dir=destination.parent) as folder:
        staging = Path(folder) / "seed"
        (staging / "raw").mkdir(parents=True)
        shutil.copyfile(source_db, staging / "qve.db")
        for identity in hashes:
            shutil.copyfile(raw_dir / identity, staging / "raw" / identity)
        (staging / "seed-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        verify_seed(staging)
        if source_preflight(source_db) != manifest["database_sha256"]:
            raise ValueError("source_changed_during_seed_copy")
        copied = build_research(staging / "qve.db", staging / "raw")
        for key in ("current", "previous", "revisions", "sources", "source_database_sha256"):
            if copied[key] != research[key]:
                raise ValueError("seed_research_mismatch")
        staging.rename(destination)
    return manifest
