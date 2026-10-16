import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from scripts.generate_review_worksheet import OUTPUT_FILE
from scripts.import_review_submissions import (
    parse_markdown_table,
    parse_worksheet,
    validate_card_submission,
)


def test_parse_markdown_table():
    table_text = """
    | 欄位 | 填寫值 |
    |---|---|
    | card_id | `CARD-01` |
    | verdict | correct |
    | reviewer | Synthetic Reviewer |
    | notes | This is a valid note. |
    """
    parsed = parse_markdown_table(table_text)
    assert parsed["card_id"] == "`CARD-01`"
    assert parsed["verdict"] == "correct"
    assert parsed["reviewer"] == "Synthetic Reviewer"
    assert parsed["notes"] == "This is a valid note."


def test_validate_card_submission():
    # Valid submission
    table = {
        "analysis_run_id": "15",
        "quarter": "FY2023-Q2",
        "category": "demand",
        "verdict": "correct",
        "reviewer": "Synthetic Reviewer",
        "reviewed_at": "2026-10-07T11:00:00+10:00",
        "notes": "Valid note of sufficient length",
        "evidence_ids": "[3100, 3111]",
    }
    ok, msg, sub = validate_card_submission(table, "CARD-01")
    assert ok is True
    assert sub is not None
    assert sub["verdict"] == "correct"
    assert sub["evidence_ids"] == [3100, 3111]

    # Invalid verdict
    table_invalid_v = dict(table, verdict="invalid_choice")
    ok, msg, sub = validate_card_submission(table_invalid_v, "CARD-01")
    assert ok is False
    assert "非法 verdict" in msg

    # Notes too short
    table_short_notes = dict(table, notes="abc")
    ok, msg, sub = validate_card_submission(table_short_notes, "CARD-01")
    assert ok is False
    assert "notes 必須提供至少 5 個字元" in msg

    # Missing timezone in reviewed_at
    table_no_tz = dict(table, reviewed_at="2026-10-07T11:00:00")
    ok, msg, sub = validate_card_submission(table_no_tz, "CARD-01")
    assert ok is False
    assert "時區" in msg

    # Empty evidence_ids
    table_no_evidence = dict(table, evidence_ids="[]")
    ok, msg, sub = validate_card_submission(table_no_evidence, "CARD-01")
    assert ok is False
    assert "非空的整數列表" in msg


def test_worksheet_generation_and_parsing(tmp_path):
    # Ensure generated worksheet is valid and parsable
    assert OUTPUT_FILE.exists()
    parsed = parse_worksheet(OUTPUT_FILE)
    assert len(parsed["p1"]) == 14
    assert len(parsed["p2"]) == 16
    assert len(parsed["p3"]) == 35
