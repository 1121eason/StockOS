#!/usr/bin/env python3
"""Parse, validate, and import human review submissions from the consolidated worksheet.

Usage:
    uv run python scripts/import_review_submissions.py --dry-run
    uv run python scripts/import_review_submissions.py --apply
    uv run python scripts/import_review_submissions.py --apply --import-db
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUMAN_REVIEW_DIR = (
    ROOT / "data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review"
)
DEFAULT_WORKSHEET = HUMAN_REVIEW_DIR / "CONSOLIDATED_REVIEW_WORKSHEET.md"
SUBMISSIONS_DIR = HUMAN_REVIEW_DIR / "submissions"
CARDS_DIR = HUMAN_REVIEW_DIR / "cards"

VALID_VERDICTS = {"correct", "partially_correct", "unsupported", "missed"}


def parse_markdown_table(block: str) -> dict[str, str]:
    """Parse a simple key-value Markdown table into a dict."""
    data = {}
    for line in block.strip().splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "| 欄位 |" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p]
        if len(parts) >= 2:
            key = parts[0].strip()
            val = parts[1].strip()
            data[key] = val
    return data


def parse_worksheet(worksheet_path: Path) -> dict[str, list[dict]]:
    if not worksheet_path.exists():
        raise FileNotFoundError(f"Worksheet not found: {worksheet_path}")

    content = worksheet_path.read_text(encoding="utf-8")

    # Split into sections
    p1_section = ""
    p2_section = ""
    p3_section = ""

    parts = re.split(r"\n## Part ", content)
    for part in parts:
        if part.startswith("1："):
            p1_section = part
        elif part.startswith("2："):
            p2_section = part
        elif part.startswith("3："):
            p3_section = part

    p1_items = []
    for match in re.finditer(
        r"### \[(P1-\d+)\] ([^\n]+)\n(.*?)(?=\n### \[P1-|\n---\n|\Z)", p1_section, re.DOTALL
    ):
        code = match.group(1)
        header = match.group(2)
        body = match.group(3)
        table_match = re.search(r"\*\*【填答區】\*\*\n(.*?)(?=\n\n|\Z)", body, re.DOTALL)
        table_data = parse_markdown_table(table_match.group(1)) if table_match else {}
        p1_items.append({"code": code, "header": header, "table": table_data})

    p2_items = []
    for match in re.finditer(
        r"### \[(P2-\d+)\] ([^\n]+)\n(.*?)(?=\n### \[P2-|\n---\n|\Z)", p2_section, re.DOTALL
    ):
        code = match.group(1)
        header = match.group(2)
        body = match.group(3)
        table_match = re.search(r"\*\*【填答區】\*\*\n(.*?)(?=\n\n|\Z)", body, re.DOTALL)
        table_data = parse_markdown_table(table_match.group(1)) if table_match else {}
        p2_items.append({"code": code, "header": header, "table": table_data})

    p3_cards = []
    for match in re.finditer(
        r"#### \[(CARD-\d+)\] ([^\n]+)\n(.*?)(?=\n#### \[CARD-|\n### 【季度|\n---\n|\Z)",
        p3_section,
        re.DOTALL,
    ):
        code = match.group(1)
        header = match.group(2)
        body = match.group(3)
        table_match = re.search(r"\*\*【審查填答表】\*\*\n(.*?)(?=\n\n|\Z)", body, re.DOTALL)
        table_data = parse_markdown_table(table_match.group(1)) if table_match else {}
        p3_cards.append({"code": code, "header": header, "table": table_data})

    return {"p1": p1_items, "p2": p2_items, "p3": p3_cards}


def validate_card_submission(
    table: dict[str, str], card_code: str
) -> tuple[bool, str, dict | None]:
    verdict = table.get("verdict", "").strip("` ")
    if not verdict or "待填" in verdict:
        return False, "verdict 待填", None

    if verdict not in VALID_VERDICTS:
        return False, f"非法 verdict: '{verdict}' (必須是 {VALID_VERDICTS})", None

    reviewer = table.get("reviewer", "").strip("` ")
    if len(reviewer) < 2:
        return False, "reviewer 名稱長度必須 >= 2", None

    notes = table.get("notes", "").strip("` ")
    if len(notes) < 5 or "待填" in notes:
        return False, "notes 必須提供至少 5 個字元的實質理由", None

    run_id_raw = table.get("analysis_run_id", "").strip("` ")
    try:
        run_id = int(run_id_raw)
    except ValueError:
        return False, f"無效的 analysis_run_id: {run_id_raw}", None

    cat = table.get("category", "").strip("` ")
    quarter = table.get("quarter", "").strip("` ")

    reviewed_at_raw = table.get("reviewed_at", "").strip("` ")
    try:
        dt = datetime.fromisoformat(reviewed_at_raw)
        if dt.tzinfo is None:
            return False, "reviewed_at 必須包含時區資訊", None
        reviewed_at = dt.isoformat()
    except Exception as e:
        return False, f"無效的時間格式 reviewed_at: {e}", None

    evidence_ids_raw = table.get("evidence_ids", "").strip()
    try:
        e_ids = ast.literal_eval(evidence_ids_raw)
        if not isinstance(e_ids, list) or not e_ids or not all(isinstance(x, int) for x in e_ids):
            return False, "evidence_ids 必須為非空的整數列表", None
    except Exception as e:
        return False, f"解析 evidence_ids 失敗: {e}", None

    submission = {
        "analysis_run_id": run_id,
        "quarter": quarter,
        "category": cat,
        "verdict": verdict,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "notes": notes,
        "evidence_ids": e_ids,
        "card_code": card_code,
    }
    return True, "驗證通過", submission


def update_card_markdown(submission: dict) -> None:
    quarter = submission["quarter"]
    category = submission["category"]
    card_path = CARDS_DIR / f"{quarter}-{category}.md"
    if not card_path.exists():
        print(f"Warning: Card file not found: {card_path}")
        return

    content = card_path.read_text(encoding="utf-8")
    content = content.replace(
        "狀態：待真人審查。", f"狀態：已由 {submission['reviewer']} 審查完成。"
    )

    # Replace table fields
    replacements = [
        (r"\| verdict \| 待填 \|", f"| verdict | {submission['verdict']} |"),
        (r"\| reviewer \| 待填 \|", f"| reviewer | {submission['reviewer']} |"),
        (
            r"\| reviewed_at（含時區） \| 待填 \|",
            f"| reviewed_at（含時區） | {submission['reviewed_at']} |",
        ),
        (r"\| notes／判斷理由 \| 待填 \|", f"| notes／判斷理由 | {submission['notes']} |"),
        (r"\| evidence_ids \| 待選 \|", f"| evidence_ids | {submission['evidence_ids']} |"),
    ]
    for pattern, repl in replacements:
        content = re.sub(pattern, repl, content)

    card_path.write_text(content, encoding="utf-8")
    print(f"  Updated card file: {card_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import human reviews from consolidated worksheet."
    )
    parser.add_argument(
        "--worksheet", type=Path, default=DEFAULT_WORKSHEET, help="Path to worksheet"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without writing files or modifying database",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write submissions JSON and update card files"
    )
    parser.add_argument(
        "--import-db", action="store_true", help="Execute qve ai-review-import to update database"
    )

    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Please specify either --dry-run or --apply.")
        sys.exit(1)

    print(f"Reading worksheet from: {args.worksheet}")
    parsed = parse_worksheet(args.worksheet)

    print("\n--- [Part 1: 14 Priority Changes Status] ---")
    p1_filled = 0
    for it in parsed["p1"]:
        v = it["table"].get("verdict", "").strip("` ")
        if v and "待填" not in v:
            p1_filled += 1
            print(
                f"  [{it['code']}] {it['header']}: verdict='{v}', notes='{it['table'].get('notes', '')}'"
            )
    print(f"Total Part 1 filled: {p1_filled} / {len(parsed['p1'])}")

    print("\n--- [Part 2: 16 Empty Support Cases Status] ---")
    p2_filled = 0
    for it in parsed["p2"]:
        agr = it["table"].get("guard_g_agree", "").strip("` ")
        if agr and "待填" not in agr:
            p2_filled += 1
            print(f"  [{it['code']}] {it['header']}: guard_g_agree='{agr}'")
    print(f"Total Part 2 filled: {p2_filled} / {len(parsed['p2'])}")

    print("\n--- [Part 3: 35 Review Cards Status] ---")
    valid_submissions = []
    card_errors = []

    for card in parsed["p3"]:
        code = card["code"]
        table = card["table"]
        ok, msg, sub = validate_card_submission(table, code)
        if ok and sub is not None:
            valid_submissions.append(sub)
            print(
                f"  ✓ [{code}] {sub['quarter']} {sub['category']}: verdict='{sub['verdict']}', reviewer='{sub['reviewer']}'"
            )
        else:
            if "待填" not in msg:
                card_errors.append((code, msg))

    print(f"\nTotal Part 3 cards ready: {len(valid_submissions)} / {len(parsed['p3'])}")
    if card_errors:
        print("\nErrors detected in Part 3 cards:")
        for code, err in card_errors:
            print(f"  ✗ [{code}]: {err}")

    if args.dry_run:
        print("\n[DRY RUN COMPLETED] No files modified. Review readiness reported above.")
        return

    if args.apply:
        if not valid_submissions:
            print(
                "\nNo valid card submissions found to apply. Please fill out the worksheet first."
            )
            return

        SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        sub_file = SUBMISSIONS_DIR / f"submission_{timestamp_str}.json"

        # Format according to HumanReviewSubmission schema (exclude internal fields)
        clean_submissions = [
            {
                "analysis_run_id": s["analysis_run_id"],
                "category": s["category"],
                "verdict": s["verdict"],
                "reviewer": s["reviewer"],
                "reviewed_at": s["reviewed_at"],
                "notes": s["notes"],
                "evidence_ids": s["evidence_ids"],
            }
            for s in valid_submissions
        ]

        sub_file.write_text(
            json.dumps(clean_submissions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\nWrote {len(clean_submissions)} submissions to: {sub_file}")

        print("\nUpdating individual review cards in human-review/cards/:")
        for s in valid_submissions:
            update_card_markdown(s)

        if args.import_db:
            print("\nImporting into database via qve ai-review-import...")
            qve_bin = ROOT / ".venv/bin/qve"
            cmd = (
                [str(qve_bin), "ai-review-import", str(sub_file)]
                if qve_bin.exists()
                else ["qve", "ai-review-import", str(sub_file)]
            )
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            print("Import output:", res.stdout)
            if res.returncode != 0:
                print("Import error:", res.stderr)
                sys.exit(res.returncode)
            print("Successfully imported reviews into local database!")


if __name__ == "__main__":
    main()
