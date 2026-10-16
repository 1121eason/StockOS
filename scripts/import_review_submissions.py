#!/usr/bin/env python3
"""Validate actual human submissions against explicit, hash-bound review dossiers.

Both modes require --worksheet and --dossiers-dir. The worksheet's adjacent
.bindings.json is used unless --bindings is supplied. --apply additionally needs
an explicit, new --output JSON path. Database import requires --import-db and an
explicit --database-url; no ambient/default database or historical cards are used.
All cards and all submitted evidence are validated before any output or DB write.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import datetime
from pathlib import Path
from typing import get_args

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from valuation_engine.ai.contracts import ReviewDraft
from valuation_engine.ai.validation import HumanReviewSubmission
from valuation_engine.db.schema import (
    AIAnalysisRun,
    AIAnalystFeature,
    AIAnalystSnapshot,
    AIChallenge,
    AIEvidence,
    AIHumanReview,
)
from valuation_engine.db.session import engine
from valuation_engine.research.numbers import canonical

try:  # Support both direct script execution and module imports in tests.
    from .generate_review_worksheet import (
        BINDING_VERSION,
        build_bindings,
        load_dossiers,
        read_object,
    )
except ImportError:
    from generate_review_worksheet import (
        BINDING_VERSION,
        build_bindings,
        load_dossiers,
        read_object,
    )

VALID_VERDICTS = set(get_args(ReviewDraft.model_fields["verdict"].annotation))
PENDING = {"", "pending", "todo", "tbd", "none", "null"}
SUBMISSION_FIELDS = tuple(HumanReviewSubmission.model_fields)


def clean(value: str) -> str:
    return value.strip("` ")


def pending(value: str) -> bool:
    return "待填" in value or clean(value).casefold() in PENDING


def parse_markdown_table(block: str) -> dict[str, str]:
    """Read key/value rows without silently accepting duplicate or extra cells."""
    data = {}
    for line in block.strip().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip().replace(r"\|", "|") for p in re.split(r"(?<!\\)\|", line[1:-1])]
        if parts == ["欄位", "填寫值"] or all(re.fullmatch(r":?-+:?", p) for p in parts):
            continue
        if not line.endswith("|") or len(parts) != 2 or not parts[0]:
            raise ValueError("Malformed review table row (escape literal pipes as \\|)")
        key, value = parts
        if key in data:
            raise ValueError(f"Duplicate review field: {key}")
        data[key] = value
    return data


def parse_worksheet(worksheet_path: Path) -> dict[str, list[dict]]:
    content = worksheet_path.read_text(encoding="utf-8")
    sections = {}
    for part in re.split(r"\n## Part ", content)[1:]:
        match = re.match(r"([123])：", part)
        if match:
            name = f"p{match[1]}"
            if name in sections:
                raise ValueError(f"Duplicate worksheet section: {name}")
            sections[name] = part
    result: dict[str, list[dict]] = {"p1": [], "p2": [], "p3": []}
    patterns = {
        "p1": r"### \[(P1-\d+)\] ([^\n]+)\n(.*?)(?=\n### \[P1-|\n---\n|\Z)",
        "p2": r"### \[(P2-\d+)\] ([^\n]+)\n(.*?)(?=\n### \[P2-|\n---\n|\Z)",
        "p3": r"#### \[(CARD-\d+)\] ([^\n]+)\n(.*?)(?=\n#### \[CARD-|\n### 【季度|\n---\n|\Z)",
    }
    for name, pattern in patterns.items():
        seen = set()
        for match in re.finditer(pattern, sections.get(name, ""), re.DOTALL):
            code, header, body = match.groups()
            if code in seen:
                raise ValueError(f"Duplicate review card: {code}")
            seen.add(code)
            marker = "審查填答表" if name == "p3" else "填答區"
            tables = re.findall(rf"\*\*【{marker}】\*\*\n(.*?)(?=\n\n|\Z)", body, re.DOTALL)
            if len(tables) != 1:
                raise ValueError(f"Exactly one review table required: {code}")
            result[name].append(
                {"code": code, "header": header, "table": parse_markdown_table(tables[0])}
            )
    return result


def load_bound_dossiers(manifest_path: Path, dossiers_dir: Path) -> tuple[dict, dict]:
    manifest = read_object(manifest_path)
    if manifest.get("schema_version") != BINDING_VERSION:
        raise ValueError("Missing or unsupported worksheet binding manifest")
    selections = {
        quarter: {key: row[key] for key in ("analysis_run_id", "snapshot_id")}
        for quarter, row in manifest["dossiers"].items()
    }
    dossiers = load_dossiers(dossiers_dir, selections)
    if manifest != build_bindings(dossiers_dir, selections, dossiers):
        raise ValueError("Dossier hash or worksheet binding manifest mismatch")
    return manifest, dossiers


def validate_card_submission(
    table: dict[str, str], card_code: str, binding: dict | None = None
) -> tuple[bool, str, dict | None]:
    if binding is None:
        return False, "Validated dossier binding required", None
    for field in ("quarter", "category", "analysis_run_id", "snapshot_id"):
        if clean(table.get(field, "")) != str(binding[field]):
            return False, f"{field} does not match the bound dossier", None
    if clean(table.get("card_id", "")) != card_code:
        return False, "card_id does not match its worksheet heading", None

    verdict = clean(table.get("verdict", ""))
    if pending(verdict):
        # An entirely blank card is allowed. Partially completed cards must be
        # completed or cleared, rather than silently disappearing from a batch.
        if any(
            not pending(table.get(field, ""))
            for field in ("reviewer", "notes", "reviewed_at", "evidence_ids")
        ):
            return False, "Incomplete card: verdict is missing", None
        return False, "pending", None
    if verdict not in VALID_VERDICTS:
        return False, f"非法 verdict: '{verdict}'", None
    reviewer = clean(table.get("reviewer", ""))
    if pending(reviewer) or len(reviewer) < 2:
        return False, "reviewer 必須填寫真人審查者名稱（至少 2 個字元）", None
    notes = clean(table.get("notes", ""))
    if pending(notes) or len(notes) < 5:
        return False, "notes 必須提供至少 5 個字元的實質理由", None
    reviewed_at_raw = clean(table.get("reviewed_at", ""))
    try:
        reviewed_at = datetime.fromisoformat(reviewed_at_raw)
        if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
            return False, "reviewed_at 必須包含時區資訊", None
    except ValueError:
        return False, "reviewed_at 必須填寫實際審查時間（含時區）", None
    try:
        evidence_ids = ast.literal_eval(clean(table.get("evidence_ids", "")))
    except (ValueError, SyntaxError):
        return False, "evidence_ids 必須為非空的整數列表", None
    if (
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or any(type(eid) is not int or eid <= 0 for eid in evidence_ids)
        or len(evidence_ids) != len(set(evidence_ids))
    ):
        return False, "evidence_ids 必須為非空的整數列表（正整數且不重複）", None
    if not set(evidence_ids) <= set(binding["evidence_ids"]):
        return False, "Evidence does not belong to the selected run/dossier", None
    review = HumanReviewSubmission.model_validate(
        {
            "analysis_run_id": binding["analysis_run_id"],
            "category": binding["category"],
            "verdict": verdict,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "notes": notes,
            "evidence_ids": evidence_ids,
        }
    )
    return (
        True,
        "驗證通過",
        {
            **review.model_dump(mode="json"),
            "quarter": binding["quarter"],
            "snapshot_id": binding["snapshot_id"],
            "card_code": card_code,
        },
    )


def validate_worksheet(parsed: dict, manifest: dict) -> list[dict]:
    cards = parsed["p3"]
    if {card["code"] for card in cards} != set(manifest["cards"]):
        raise ValueError("Worksheet card set does not match the binding manifest")
    submissions, errors = [], []
    seen = set()
    for card in cards:
        code = card["code"]
        if code in seen:
            raise ValueError(f"Duplicate review card: {code}")
        seen.add(code)
        binding = manifest["cards"][code]
        expected_header = f"{binding['quarter']} — {binding['category'].upper()}（"
        if not card["header"].startswith(expected_header):
            errors.append(f"{code}: heading does not match bound quarter/category")
        ok, message, submission = validate_card_submission(card["table"], code, binding)
        if ok and submission is not None:
            submissions.append(submission)
        elif message != "pending":
            errors.append(f"{code}: {message}")
    if errors:
        raise ValueError("No submissions applied: " + "; ".join(errors))
    return submissions


def _check_database_row(row, exported: dict, label: str) -> None:
    if row is None:
        raise ValueError(f"Selected {label} unavailable in target database")
    columns = {column.name for column in row.__table__.columns}
    for key, value in exported.items():
        if key in columns and canonical(getattr(row, key)) != canonical(value):
            raise ValueError(f"Selected {label}.{key} differs from the bound dossier")


def validate_database_bindings(db: Session, dossiers: dict) -> None:
    """Read-only preflight against the exact database selected for import."""
    for dossier in dossiers.values():
        _check_database_row(db.get(AIAnalysisRun, dossier["run"]["id"]), dossier["run"], "run")
        _check_database_row(
            db.get(AIAnalystSnapshot, dossier["snapshot"]["id"]), dossier["snapshot"], "snapshot"
        )
        for collection, model in (
            ("evidence", AIEvidence),
            ("features", AIAnalystFeature),
            ("challenges", AIChallenge),
        ):
            for row in dossier[collection]:
                _check_database_row(db.get(model, row["id"]), row, collection)


def import_database(db: Session, submissions: list[dict], dossiers: dict) -> None:
    # A single transaction: a later invalid card never leaves earlier reviews.
    validate_database_bindings(db, dossiers)
    validated = []
    for submission in submissions:
        dossier = dossiers.get(submission["quarter"])
        if (
            dossier is None
            or submission["analysis_run_id"] != dossier["run"]["id"]
            or submission["snapshot_id"] != dossier["snapshot"]["id"]
        ):
            raise ValueError("Submission does not match the selected run/snapshot")
        ids = submission["evidence_ids"]
        if (
            not ids
            or any(type(eid) is not int or eid <= 0 for eid in ids)
            or not set(ids) <= {e["id"] for e in dossier["evidence"]}
        ):
            raise ValueError("Submission evidence does not belong to selected run")
        review = HumanReviewSubmission.model_validate(
            {key: submission[key] for key in SUBMISSION_FIELDS}
        )
        validated.append(review)
    for review in validated:
        db.add(
            AIHumanReview(
                **review.model_dump(exclude={"reviewed_at"}), created_at=review.reviewed_at
            )
        )
    db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worksheet", type=Path, required=True)
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--dossiers-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--output", type=Path, help="New submission JSON path (required with --apply)"
    )
    parser.add_argument("--import-db", action="store_true")
    parser.add_argument(
        "--database-url", help="Explicit target; also permits read-only dry-run validation"
    )
    args = parser.parse_args(argv)
    if args.apply and args.output is None:
        parser.error("--apply requires --output")
    if args.import_db and (not args.apply or not args.database_url):
        parser.error("--import-db requires --apply and an explicit --database-url")
    try:
        manifest, dossiers = load_bound_dossiers(
            args.bindings or args.worksheet.with_suffix(".bindings.json"), args.dossiers_dir
        )
        submissions = validate_worksheet(parse_worksheet(args.worksheet), manifest)
        if args.apply and args.output.exists():
            raise FileExistsError("Refusing to overwrite existing submissions")
        clean_submissions = [{key: row[key] for key in SUBMISSION_FIELDS} for row in submissions]
        target = None
        if args.database_url:
            url = make_url(args.database_url)
            if url.get_backend_name() == "sqlite" and (
                not url.database or url.database == ":memory:" or not Path(url.database).is_file()
            ):
                raise ValueError("Explicit SQLite database must already exist")
            target = engine(args.database_url)
        try:
            if target is not None:
                with Session(target) as db:
                    validate_database_bindings(db, dossiers)
            if args.apply and submissions:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(clean_submissions, indent=2, ensure_ascii=False) + "\n")
                if args.import_db:
                    try:
                        with Session(target) as db:
                            import_database(db, submissions, dossiers)
                    except Exception:
                        args.output.unlink()  # Only our newly created, unimported export.
                        raise
                print(f"Wrote {len(submissions)} actual human submissions: {args.output}")
                if args.import_db:
                    print(
                        f"Appended {len(submissions)} reviews to the explicitly selected database"
                    )
            else:
                print(
                    f"Validated {len(submissions)} completed / {len(manifest['cards'])} selected cards; no files or database rows changed"
                )
        finally:
            if target is not None:
                target.dispose()
    except (ValueError, OSError, KeyError, TypeError, SQLAlchemyError) as exc:
        parser.exit(1, f"Review import refused: {exc}\n")


if __name__ == "__main__":
    main()
