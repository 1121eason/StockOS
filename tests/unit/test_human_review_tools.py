"""Synthetic, isolated tests; these fixtures are never actual human reviews."""

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from scripts.generate_review_worksheet import (
    CATEGORIES,
    generate_worksheet,
    load_cases_data,
    load_dossiers,
    load_focus_data,
)
from scripts.import_review_submissions import (
    import_database,
    load_bound_dossiers,
    main,
    parse_markdown_table,
    parse_worksheet,
    validate_card_submission,
    validate_database_bindings,
    validate_worksheet,
)
from valuation_engine.ai.validation import HumanReviewSubmission
from valuation_engine.db.schema import AIAnalysisRun, AIAnalystSnapshot, AIEvidence, AIHumanReview
from valuation_engine.db.session import create_test_schema
from valuation_engine.db.store import company, document

QUARTER = "FY2026-Q1"


@pytest.fixture
def dossier():
    span = "Synthetic evidence only; no historical claims."
    return {
        "run": {
            "id": 101,
            "company_id": 1,
            "quarter": QUARTER,
            "request_hash": "synthetic-request",
            "model_provider": "synthetic",
            "model_name": "synthetic-model",
            "model_version": "synthetic-model-v1",
            "prompt_version": "SyntheticPromptV1",
            "schema_version": "SyntheticSchemaV1",
        },
        "snapshot": {
            "id": 501,
            "analysis_run_id": 101,
            "company_id": 1,
            "prompt_version": "SyntheticPromptV1",
            "model_version": "synthetic-model-v1",
        },
        "evidence": [
            {
                "id": 9001,
                "analysis_run_id": 101,
                "evidence_key": "synthetic-evidence",
                "span": span,
                "span_hash": hashlib.sha256(span.encode()).hexdigest(),
                "source_document_id": 1,
                "source_hash": hashlib.sha256(span.encode()).hexdigest(),
                "block_id": "synthetic-block",
            }
        ],
        "features": [],
        "challenges": [],
    }


@pytest.fixture
def inputs(tmp_path, dossier):
    directory = tmp_path / "dossiers"
    directory.mkdir()
    path = directory / f"{QUARTER}.json"
    path.write_text(json.dumps(dossier), encoding="utf-8")
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({QUARTER: {"analysis_run_id": 101, "snapshot_id": 501}}))
    return {
        "dossiers_dir": directory,
        "selection_path": selection,
        "output_file": tmp_path / "worksheet.md",
    }


@pytest.fixture
def generated(inputs):
    manifest_path = generate_worksheet(**inputs)
    manifest, dossiers = load_bound_dossiers(manifest_path, inputs["dossiers_dir"])
    return inputs, manifest_path, manifest, dossiers


@pytest.fixture
def card(generated):
    inputs, _, manifest, _ = generated
    table = parse_worksheet(inputs["output_file"])["p3"][0]["table"]
    table.update(
        verdict="correct",
        reviewer="Synthetic Reviewer",
        reviewed_at="2026-10-07T11:00:00+10:00",
        notes="Synthetic test note of sufficient length",
        evidence_ids="[9001]",
    )
    return table, manifest["cards"]["CARD-01"]


def complete_first_card(path):
    text = path.read_text(encoding="utf-8")
    for field, value in {
        "verdict": "correct",
        "reviewer": "Synthetic Reviewer",
        "reviewed_at": "2026-10-07T11:00:00+10:00",
        "notes": "Synthetic test note of sufficient length",
        "evidence_ids": "[9001]",
    }.items():
        import re

        text = re.sub(rf"\| {field} \| [^\n]+ \|", f"| {field} | {value} |", text, count=1)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def isolated_db(tmp_path, dossier):
    # Intentionally independent of tests/conftest.py's optional PostgreSQL db.
    db_path = tmp_path / "synthetic-review.db"
    target = create_test_schema(f"sqlite:///{db_path}")
    at = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(target) as db:
        co = company(db)
        doc = document(
            db,
            tmp_path / "synthetic-raw",
            dossier["evidence"][0]["span"].encode(),
            url="https://example.test/synthetic-review",
            company_id=co.id,
            provider="synthetic",
            kind="synthetic",
            published_at=at,
        )
        assert doc.id == 1
        db.add(
            AIAnalysisRun(
                **dossier["run"],
                as_of_timestamp=at,
                information_cutoff=at,
                source_document_ids=[doc.id],
                policy_version="synthetic-policy",
                context_json={},
                settings_json={},
            )
        )
        db.flush()
        db.add(
            AIAnalystSnapshot(
                **dossier["snapshot"],
                as_of_timestamp=at,
                overall_qualitative_confidence="0.5",
                metadata_json={},
            )
        )
        db.add(
            AIEvidence(
                **dossier["evidence"][0],
                section="synthetic",
                topic="demand",
                implication="synthetic",
                available_at=at,
                metadata_json={},
            )
        )
        db.commit()
        yield db, f"sqlite:///{db_path}"
    target.dispose()


def test_parse_markdown_table_preserves_escaped_pipe():
    parsed = parse_markdown_table("""
    | 欄位 | 填寫值 |
    |---|---|
    | card_id | `CARD-01` |
    | notes | Evidence A \\| evidence B |
    """)
    assert parsed == {"card_id": "`CARD-01`", "notes": "Evidence A | evidence B"}


@pytest.mark.parametrize(
    "table",
    ["| verdict | correct |\n| verdict | missed |", "| notes | a | b |", "| notes | broken"],
)
def test_parse_table_rejects_ambiguous_rows(table):
    with pytest.raises(ValueError):
        parse_markdown_table(table)


def test_generation_uses_explicit_ids_and_preserves_blank_human_fields(generated):
    inputs, _, manifest, _ = generated
    parsed = parse_worksheet(inputs["output_file"])
    assert len(parsed["p3"]) == len(CATEGORIES) == 7
    assert not parsed["p1"] and not parsed["p2"]
    for item in parsed["p3"]:
        assert item["table"]["analysis_run_id"] == "`101`"
        assert item["table"]["snapshot_id"] == "`501`"
        for field in ("reviewer", "verdict", "reviewed_at", "notes", "evidence_ids"):
            assert "待填" in item["table"][field]
    assert validate_worksheet(parsed, manifest) == []
    assert "completed human reviews" not in inputs["output_file"].read_text()
    assert "**候選 Evidence IDs**：`[]`" in inputs["output_file"].read_text()
    assert "**候選 Evidence IDs**：`[9001]`" not in inputs["output_file"].read_text()


def test_generation_never_overwrites_human_work(generated):
    inputs, manifest_path, _, _ = generated
    inputs["output_file"].write_text("Existing human work")
    before = manifest_path.read_bytes()
    with pytest.raises(FileExistsError):
        generate_worksheet(**inputs)
    assert inputs["output_file"].read_text() == "Existing human work"
    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize(
    "bad_selection",
    [
        {},
        {QUARTER: {}},
        {QUARTER: {"analysis_run_id": 15, "snapshot_id": 501}},
        {QUARTER: {"analysis_run_id": 101, "snapshot_id": 4}},
        {"../bad": {"analysis_run_id": 101, "snapshot_id": 501}},
        {QUARTER: {"analysis_run_id": True, "snapshot_id": 501}},
    ],
)
def test_generation_rejects_unavailable_or_legacy_selection(inputs, bad_selection):
    inputs["selection_path"].write_text(json.dumps(bad_selection))
    with pytest.raises(ValueError):
        generate_worksheet(**inputs)
    assert not inputs["output_file"].exists()


def test_generation_requires_available_dossier(inputs):
    (inputs["dossiers_dir"] / f"{QUARTER}.json").unlink()
    with pytest.raises(FileNotFoundError):
        generate_worksheet(**inputs)
    assert not inputs["output_file"].exists()


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("run", "quarter", "FY2023-Q2"),
        ("run", "id", 15),
        ("run", "request_hash", ""),
        ("snapshot", "analysis_run_id", 15),
        ("snapshot", "id", 4),
        ("snapshot", "company_id", 2),
        ("snapshot", "prompt_version", "other-prompt"),
        ("evidence", "analysis_run_id", 15),
        ("evidence", "id", True),
        ("evidence", "span", ""),
        ("evidence", "source_hash", ""),
    ],
)
def test_generation_rejects_mixed_dossier(inputs, dossier, section, field, value):
    row = dossier[section][0] if section == "evidence" else dossier[section]
    row[field] = value
    (inputs["dossiers_dir"] / f"{QUARTER}.json").write_text(json.dumps(dossier))
    with pytest.raises(ValueError):
        generate_worksheet(**inputs)
    assert not inputs["output_file"].exists()


def test_generation_rejects_absent_evidence(inputs, dossier):
    dossier["evidence"] = []
    (inputs["dossiers_dir"] / f"{QUARTER}.json").write_text(json.dumps(dossier))
    with pytest.raises(ValueError, match="Evidence unavailable"):
        generate_worksheet(**inputs)


@pytest.mark.parametrize("kind", ["feature", "challenge"])
def test_generation_rejects_cross_run_references(inputs, dossier, kind):
    if kind == "feature":
        dossier["features"] = [
            {
                "id": 401,
                "analysis_run_id": 101,
                "feature_name": "demand_momentum",
                "feature_value": "0.3",
                "metadata_json": {"evidence_keys": ["missing-key"]},
            }
        ]
    else:
        dossier["challenges"] = [{"id": 601, "analysis_run_id": 101, "evidence_ids": [9999]}]
    (inputs["dossiers_dir"] / f"{QUARTER}.json").write_text(json.dumps(dossier))
    with pytest.raises(ValueError, match="unavailable evidence"):
        generate_worksheet(**inputs)


def test_feature_candidates_are_linked_without_prefilling_reviews(inputs, dossier):
    dossier["features"] = [
        {
            "id": 401,
            "analysis_run_id": 101,
            "feature_name": "demand_momentum",
            "feature_value": "0.3",
            "rationale": "Synthetic interpretation",
            "metadata_json": {"evidence_keys": ["synthetic-evidence"]},
        }
    ]
    (inputs["dossiers_dir"] / f"{QUARTER}.json").write_text(json.dumps(dossier))
    generate_worksheet(**inputs)
    text = inputs["output_file"].read_text()
    assert "**候選 Evidence IDs**：`[9001]`" in text
    assert "| evidence_ids | [9001] |" not in text


def test_valid_card_uses_formal_human_schema(card):
    table, binding = card
    ok, _, submission = validate_card_submission(table, "CARD-01", binding)
    assert ok
    review = HumanReviewSubmission.model_validate(
        {key: submission[key] for key in HumanReviewSubmission.model_fields}
    )
    assert review.evidence_ids == [9001]
    assert review.analysis_run_id == 101
    assert review.reviewed_at.isoformat() == table["reviewed_at"]


def test_unbound_legacy_card_is_rejected(card):
    table, _ = card
    ok, message, _ = validate_card_submission(table, "CARD-01")
    assert not ok and "binding" in message


@pytest.mark.parametrize(
    "field,value",
    [
        ("analysis_run_id", "15"),
        ("snapshot_id", "4"),
        ("quarter", "FY2023-Q2"),
        ("category", "../../outside"),
        ("card_id", "CARD-02"),
        ("verdict", "invalid_choice"),
        ("reviewer", "待填"),
        ("reviewer", "TBD"),
        ("notes", "abc"),
        ("notes", "待填待填待填"),
        ("reviewed_at", "2026-10-07T11:00:00"),
        ("reviewed_at", "待填"),
        ("evidence_ids", "[]"),
        ("evidence_ids", "[True]"),
        ("evidence_ids", "[9001, 9001]"),
        ("evidence_ids", "[9001.0]"),
        ("evidence_ids", "[9999]"),
        ("evidence_ids", "[0]"),
    ],
)
def test_invalid_submission_fails_closed(card, field, value):
    table, binding = card
    ok, _, submission = validate_card_submission({**table, field: value}, "CARD-01", binding)
    assert not ok and submission is None


def test_one_bad_card_rejects_whole_batch(generated, card):
    inputs, _, manifest, _ = generated
    parsed = parse_worksheet(inputs["output_file"])
    parsed["p3"][0]["table"] = card[0]
    parsed["p3"][1]["table"]["analysis_run_id"] = "15"
    with pytest.raises(ValueError, match="No submissions applied"):
        validate_worksheet(parsed, manifest)


def test_partially_completed_card_is_error(generated):
    inputs, _, manifest, _ = generated
    parsed = parse_worksheet(inputs["output_file"])
    parsed["p3"][0]["table"]["notes"] = "Synthetic partial note"
    with pytest.raises(ValueError, match="Incomplete card"):
        validate_worksheet(parsed, manifest)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "heading"])
def test_worksheet_structure_is_bound(generated, mutation):
    inputs, _, manifest, _ = generated
    parsed = parse_worksheet(inputs["output_file"])
    if mutation == "missing":
        parsed["p3"].pop()
    elif mutation == "duplicate":
        parsed["p3"].append(copy.deepcopy(parsed["p3"][0]))
    else:
        parsed["p3"][0]["header"] = "FY2023-Q2 — DEMAND（"
    with pytest.raises(ValueError):
        validate_worksheet(parsed, manifest)


def test_dossier_changes_invalidate_manifest(generated):
    inputs, manifest_path, _, _ = generated
    path = inputs["dossiers_dir"] / f"{QUARTER}.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="hash"):
        load_bound_dossiers(manifest_path, inputs["dossiers_dir"])


def test_manifest_card_tampering_is_rejected(generated):
    inputs, manifest_path, manifest, _ = generated
    manifest["cards"]["CARD-01"]["analysis_run_id"] = 15
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest mismatch"):
        load_bound_dossiers(manifest_path, inputs["dossiers_dir"])


def test_apply_export_matches_formal_schema(generated, tmp_path):
    inputs, _, _, _ = generated
    complete_first_card(inputs["output_file"])
    output = tmp_path / "submissions.json"
    main(
        [
            "--worksheet",
            str(inputs["output_file"]),
            "--dossiers-dir",
            str(inputs["dossiers_dir"]),
            "--apply",
            "--output",
            str(output),
        ]
    )
    reviews = json.loads(output.read_text())
    assert len(reviews) == 1
    assert HumanReviewSubmission.model_validate(reviews[0]).reviewer == "Synthetic Reviewer"
    assert not (inputs["output_file"].parent / "cards").exists()


def test_dry_run_never_writes(generated, tmp_path):
    inputs, _, _, _ = generated
    complete_first_card(inputs["output_file"])
    output = tmp_path / "submissions.json"
    main(
        [
            "--worksheet",
            str(inputs["output_file"]),
            "--dossiers-dir",
            str(inputs["dossiers_dir"]),
            "--dry-run",
            "--output",
            str(output),
        ]
    )
    assert not output.exists()


def test_import_requires_explicit_database(generated, tmp_path):
    inputs, _, _, _ = generated
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--worksheet",
                str(inputs["output_file"]),
                "--dossiers-dir",
                str(inputs["dossiers_dir"]),
                "--apply",
                "--output",
                str(tmp_path / "out.json"),
                "--import-db",
            ]
        )
    assert exc.value.code == 2


def test_missing_database_is_not_created(generated, tmp_path):
    inputs, _, _, _ = generated
    missing = tmp_path / "missing.db"
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--worksheet",
                str(inputs["output_file"]),
                "--dossiers-dir",
                str(inputs["dossiers_dir"]),
                "--dry-run",
                "--database-url",
                f"sqlite:///{missing}",
            ]
        )
    assert exc.value.code == 1
    assert not missing.exists()


def test_database_validation_and_atomic_import(isolated_db, dossier, card):
    db, _ = isolated_db
    _, _, submission = validate_card_submission(card[0], "CARD-01", card[1])
    validate_database_bindings(db, {QUARTER: dossier})
    invalid = dict(submission, snapshot_id=4)
    with pytest.raises(ValueError, match="run/snapshot"):
        import_database(db, [submission, invalid], {QUARTER: dossier})
    assert db.scalar(select(func.count()).select_from(AIHumanReview)) == 0
    import_database(db, [submission], {QUARTER: dossier})
    review = db.scalar(select(AIHumanReview))
    assert review.analysis_run_id == 101
    assert review.evidence_ids == [9001]
    assert review.created_at == datetime(2026, 10, 7, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("run", "request_hash", "another-database"),
        ("run", "id", 999),
        ("snapshot", "id", 4),
        ("evidence", "span", "Changed synthetic text"),
        ("evidence", "analysis_run_id", 15),
    ],
)
def test_database_preflight_rejects_id_collisions(isolated_db, dossier, section, field, value):
    db, _ = isolated_db
    changed = copy.deepcopy(dossier)
    row = changed[section][0] if section == "evidence" else changed[section]
    row[field] = value
    with pytest.raises(ValueError):
        validate_database_bindings(db, {QUARTER: changed})
    assert db.scalar(select(func.count()).select_from(AIHumanReview)) == 0


def test_import_cli_uses_only_explicit_synthetic_database(
    generated, isolated_db, tmp_path, monkeypatch
):
    inputs, _, _, _ = generated
    db, url = isolated_db
    complete_first_card(inputs["output_file"])
    forbidden = tmp_path / "ambient-must-not-be-created.db"
    monkeypatch.setenv("QVE_DATABASE_URL", f"sqlite:///{forbidden}")
    output = tmp_path / "submitted.json"
    main(
        [
            "--worksheet",
            str(inputs["output_file"]),
            "--dossiers-dir",
            str(inputs["dossiers_dir"]),
            "--apply",
            "--output",
            str(output),
            "--import-db",
            "--database-url",
            url,
        ]
    )
    assert output.is_file()
    assert db.scalar(select(func.count()).select_from(AIHumanReview)) == 1
    assert not forbidden.exists()


def test_missing_optional_inputs_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="unavailable"):
        load_cases_data(tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        load_focus_data(tmp_path / "missing.json")


def test_cases_have_blank_verdict_and_review_time(inputs, tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "feature-1.md").write_text(
        "# feature-1 — demand_momentum\nRun / snapshot：101 / 501\n原狀態：admitted；原分數：0.5；原保存 confidence：0.5\n新 G：synthetic reason\n"
    )
    generate_worksheet(**inputs, cases_dir=cases)
    card = parse_worksheet(inputs["output_file"])["p2"][0]
    assert "待填" in card["table"]["verdict"]
    assert "待填" in card["table"]["reviewed_at"]


def test_no_implicit_selection_api(inputs):
    with pytest.raises(ValueError, match="explicit"):
        load_dossiers(inputs["dossiers_dir"], {})


def test_apply_with_invalid_card_writes_nothing(generated, tmp_path):
    inputs, _, _, _ = generated
    complete_first_card(inputs["output_file"])
    text = inputs["output_file"].read_text()
    text = text.replace("| snapshot_id | `501` |", "| snapshot_id | `4` |", 1)
    inputs["output_file"].write_text(text)
    output = tmp_path / "refused.json"
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--worksheet",
                str(inputs["output_file"]),
                "--dossiers-dir",
                str(inputs["dossiers_dir"]),
                "--apply",
                "--output",
                str(output),
            ]
        )
    assert exc.value.code == 1
    assert not output.exists()


def test_output_failure_precedes_database_mutation(generated, isolated_db, tmp_path):
    inputs, _, _, _ = generated
    db, url = isolated_db
    complete_first_card(inputs["output_file"])
    blocker = tmp_path / "file-not-directory"
    blocker.write_text("Keep this original content")
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--worksheet",
                str(inputs["output_file"]),
                "--dossiers-dir",
                str(inputs["dossiers_dir"]),
                "--apply",
                "--output",
                str(blocker / "out.json"),
                "--import-db",
                "--database-url",
                url,
            ]
        )
    assert exc.value.code == 1
    assert db.scalar(select(func.count()).select_from(AIHumanReview)) == 0
    assert blocker.read_text() == "Keep this original content"


def test_database_failure_rolls_back_and_removes_new_export(
    generated, isolated_db, tmp_path, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError

    inputs, _, _, _ = generated
    db, url = isolated_db
    complete_first_card(inputs["output_file"])
    output = tmp_path / "failed.json"

    def fail_commit(_session):
        raise SQLAlchemyError("Synthetic test commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--worksheet",
                str(inputs["output_file"]),
                "--dossiers-dir",
                str(inputs["dossiers_dir"]),
                "--apply",
                "--output",
                str(output),
                "--import-db",
                "--database-url",
                url,
            ]
        )
    assert exc.value.code == 1
    assert not output.exists()
    assert db.scalar(select(func.count()).select_from(AIHumanReview)) == 0


def test_database_dry_run_cannot_append_reviews(generated, isolated_db):
    inputs, _, _, _ = generated
    db, url = isolated_db
    complete_first_card(inputs["output_file"])
    main(
        [
            "--worksheet",
            str(inputs["output_file"]),
            "--dossiers-dir",
            str(inputs["dossiers_dir"]),
            "--dry-run",
            "--database-url",
            url,
        ]
    )
    assert db.scalar(select(func.count()).select_from(AIHumanReview)) == 0


def test_explicit_multi_quarter_selection_retains_seven_category_rubric(inputs, dossier):
    second = copy.deepcopy(dossier)
    second_quarter = "FY2026-Q2"
    second["run"].update(id=202, quarter=second_quarter, request_hash="synthetic-second-request")
    second["snapshot"].update(id=502, analysis_run_id=202)
    second["evidence"][0].update(id=9002, analysis_run_id=202)
    (inputs["dossiers_dir"] / f"{second_quarter}.json").write_text(json.dumps(second))
    inputs["selection_path"].write_text(
        json.dumps(
            {
                second_quarter: {"analysis_run_id": 202, "snapshot_id": 502},
                QUARTER: {"analysis_run_id": 101, "snapshot_id": 501},
            }
        )
    )
    manifest_path = generate_worksheet(**inputs)
    manifest, _ = load_bound_dossiers(manifest_path, inputs["dossiers_dir"])
    cards = parse_worksheet(inputs["output_file"])["p3"]
    assert len(cards) == 14
    assert manifest["cards"]["CARD-01"]["analysis_run_id"] == 101
    assert manifest["cards"]["CARD-08"]["analysis_run_id"] == 202
    for start in (0, 7):
        assert {card["table"]["category"].strip("`") for card in cards[start : start + 7]} == set(
            CATEGORIES
        )


def test_focus_requires_available_evidence(tmp_path):
    focus = tmp_path / "focus.json"
    focus.write_text(
        json.dumps(
            {
                "quarters": [{"quarter": QUARTER, "priority_changes": [{"evidence_ids": [1]}]}],
                "evidence": [],
            }
        )
    )
    with pytest.raises(ValueError, match="unavailable evidence"):
        load_focus_data(focus)


def test_malformed_case_cannot_default_to_run_zero(tmp_path):
    (tmp_path / "feature-1.md").write_text("# feature-1 — demand_momentum\nNo run identity")
    with pytest.raises(ValueError, match="identity unavailable"):
        load_cases_data(tmp_path)
