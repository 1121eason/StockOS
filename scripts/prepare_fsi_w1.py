#!/usr/bin/env python3
"""Prepare local SEC/IR inputs from explicit historical run IDs; never run a model."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from valuation_engine.ai.fsi_w1 import build_package, canonical, offline_plan, protocol, timestamp


def stored_utc(value):
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def availability_provenance(conn, doc, raw_dir):
    """Keep stored time assertions distinct from independently verified publication."""
    result = {
        "source_document_id": doc["source_document_id"],
        "status": "STORED_ASSERTION_NOT_INDEPENDENTLY_VERIFIED",
        "timestamp_precision": doc.get("timestamp_precision"),
        "availability_record": None,
        "evidence_document": None,
    }
    evidence_id = doc.get("availability_evidence_id")
    if evidence_id is None:
        return result
    if type(evidence_id) is not int or evidence_id <= 0:
        raise ValueError("Invalid availability evidence ID")
    row = conn.execute("SELECT * FROM availability_evidence WHERE id=?", (evidence_id,)).fetchone()
    if row is None or row["source_document_id"] != doc["source_document_id"]:
        raise ValueError("Availability evidence belongs to a different document")
    if stored_utc(row["information_available_at"]) != timestamp(
        doc["available_at"], "available_at"
    ):
        raise ValueError("Stored availability evidence disagrees with the context")
    publication = row["published_at"]
    if (publication is None) != (doc.get("published_at") is None) or (
        publication is not None
        and stored_utc(publication) != timestamp(doc["published_at"], "published_at")
    ):
        raise ValueError("Stored publication evidence disagrees with the context")
    result["availability_record"] = dict(row)
    evidence_document_id = row["evidence_document_id"]
    if evidence_document_id is not None:
        source = conn.execute(
            "SELECT * FROM source_documents WHERE id=?", (evidence_document_id,)
        ).fetchone()
        if source is None:
            raise ValueError("Referenced timestamp evidence document is absent")
        sha = source["content_hash"]
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Invalid timestamp evidence content hash")
        path = raw_dir / sha
        byte_status = "MISSING_CACHED_BYTES"
        if path.is_symlink():
            raise ValueError("Timestamp evidence cannot be a symlink")
        if path.is_file():
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError("Timestamp evidence bytes differ from their stored hash")
            byte_status = "HASH_MATCH_ONLY"
        result["evidence_document"] = {
            "id": evidence_document_id,
            "source_hash": sha,
            "source_url": source["source_url"],
            "bytes": byte_status,
        }
    return result


def load_cached_run(database, raw_dir, run_id):
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("An explicit positive run ID is required")
    database, raw_dir = Path(database).resolve(strict=True), Path(raw_dir).resolve(strict=True)
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Consistent read-only database without sidecars required")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        row = conn.execute("SELECT * FROM ai_analysis_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Selected analysis run is absent")
        context = json.loads(row["context_json"])
        if context["quant_context"]["quarter"] != row["quarter"]:
            raise ValueError("Stored context and selected run quarter disagree")
        # UTCDateTime's persisted SQLite representation is timezone-naive UTC.
        stored_cutoff = stored_utc(row["information_cutoff"])
        if timestamp(context["quant_context"]["information_cutoff"], "cutoff") != stored_cutoff:
            raise ValueError("Stored run and context cutoffs disagree")
        if (
            type(context["quant_context"].get("company_id")) is not int
            or context["quant_context"]["company_id"] != row["company_id"]
        ):
            raise ValueError("Stored run and context company disagree")
        documents = context["sources"]["documents"]
        ids = [d["source_document_id"] for d in documents]
        if len(ids) != len(set(ids)) or set(ids) != set(json.loads(row["source_document_ids"])):
            raise ValueError("Stored run source selection disagrees")
        contents, source_provenance = {}, []
        for doc in documents:
            source = conn.execute(
                "SELECT * FROM source_documents WHERE id=?", (doc["source_document_id"],)
            ).fetchone()
            if (
                source is None
                or any(
                    source[column] != doc[key]
                    for column, key in (
                        ("content_hash", "source_hash"),
                        ("source_url", "source_url"),
                        ("document_type", "document_type"),
                    )
                )
                or source["company_id"] != row["company_id"]
            ):
                raise ValueError("Source does not belong to the selected run identity")
            sha = doc["source_hash"]
            # No raw_path from the historical DB is followed.
            if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise ValueError("Invalid source content hash")
            path = raw_dir / sha
            if path.is_symlink() or not path.is_file():
                raise ValueError("Explicit content-addressed regular source file required")
            contents[sha] = path.read_bytes()
            source_provenance.append(availability_provenance(conn, doc, raw_dir))
        package = build_package(context["quant_context"], documents, contents)
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    if after != before:
        raise ValueError("Source database changed during preparation")
    return (
        package,
        contents,
        {
            "selected_run_id": run_id,
            "database_sha256": before,
            "database_unchanged": True,
            "historical_ai_output_reused": False,
            "source_time_provenance": source_provenance,
        },
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument(
        "--output-dir", type=Path, help="Explicit NEW directory; otherwise stdout only"
    )
    args = parser.parse_args(argv)
    try:
        package, contents, provenance = load_cached_run(args.database, args.raw_dir, args.run_id)
        result = {"plan": offline_plan(package, contents), "provenance": provenance}
        if args.output_dir:
            args.output_dir.mkdir(exist_ok=False)
            for name, data in (
                ("protocol.json", protocol()),
                ("package.json", package),
                ("preflight.json", result),
            ):
                (args.output_dir / name).write_text(canonical(data) + "\n", encoding="utf-8")
        print(canonical(result))
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        parser.exit(2, f"Offline preparation refused: {type(error).__name__}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
