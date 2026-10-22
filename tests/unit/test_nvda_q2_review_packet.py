"""Read-only private review export; all outputs and providers are synthetic."""

import json
import sqlite3

import pytest
from test_fsi_s2_provenance import load, run
from test_fsi_s2_provenance import package as package

from valuation_engine.ai.native_preflight import canonical, sha


@pytest.fixture
def candidates(tmp_path, package, monkeypatch):
    first, database = run(tmp_path, package, method="B")
    second, _ = run(tmp_path, package, database=database, method="C")
    module = load("prepare_nvda_q2_review")
    rule = {
        "version": "SYNTHETIC",
        "anchors": {"0": "Missing", "1": "Partial", "2": "Supported", "3": "Counterevidence"},
        "hard_gates": ["exact_quotes", "zero_illegal_admissions"],
        "quality_dimensions": ["dispute_stability", "insight_depth", "challenge_quality"],
        "scale": [0, 1, 2, 3],
        "missing_repeat": "UNASSESSED_NO_COMPLETE_TOTAL",
        "missing_scores": "UNASSESSED",
        "independent_reviewers": 2,
        "disagreement": "third_person_adjudication_required",
        "result_scope": "synthetic_only",
    }
    body = {"review_rule": rule}
    binding = sha(canonical(body).encode())
    monkeypatch.setattr(module, "PROTOCOL_HASH", binding)
    protocol = tmp_path / "synthetic-protocol.json"
    protocol.write_text(json.dumps({**body, "protocol_hash": binding}))
    return module, database, {"B": first["run_id"], "C": second["run_id"]}, protocol


def test_packet_retains_sources_missingness_and_blank_scores_without_model_labels(
    candidates, tmp_path
):
    module, database, ids, protocol = candidates
    before = database.read_bytes()
    out = tmp_path / "review"
    result = module.prepare(database, ids, protocol, out)
    assert result["status"] == "PREPARED_UNSCORED"
    assert database.read_bytes() == before
    mapping = json.loads((out / "administrator/mapping.json").read_text())
    assert {v["method"] for v in mapping["mapping"].values()} == {"B", "C"}
    manifest = json.loads((out / "manifest.json").read_bytes())
    assert manifest["files"]["README.md"] == sha((out / "reviewers/README.md").read_bytes())
    assert "已接觸者不能算作未揭盲" in (out / "reviewers/README.md").read_text()
    for label in ("X", "Y"):
        sample = json.loads((out / f"reviewers/{label}.json").read_text())
        assert sample["features"] and sample["evidence"] and sample["challenges"]
        assert sample["missing_features"] and sample["repeat_stability"] == "UNASSESSED_NO_REPEATS"
        assert "method" not in sample and "run_id" not in sample and not sample["promotion_ready"]
    for index in (1, 2):
        form = json.loads((out / f"reviewers/reviewer-{index}.json").read_text())
        assert form["reviewer_identity"] is None and form["total_score"] is None
        assert all(
            v is None for sample in form["samples"].values() for v in sample["scores"].values()
        )
    assert "synthetic-fixture-only" not in "".join(
        p.read_text() for p in (out / "reviewers").glob("*.json")
    )
    with pytest.raises(ValueError, match="new directory"):
        module.prepare(database, ids, protocol, out)


@pytest.mark.parametrize("fault", ["quote", "pending", "selection", "protocol"])
def test_unverified_or_mismatched_candidates_never_publish_review_packet(
    candidates, tmp_path, fault
):
    module, database, ids, protocol = candidates
    if fault in ("quote", "pending"):
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE s2_evidence SET span='Invented quotation'"
                if fault == "quote"
                else "UPDATE s2_experiment_runs SET status='RUNNING'"
            )
    elif fault == "selection":
        ids = {"B": ids["C"], "C": ids["B"]}
    else:
        content = json.loads(protocol.read_text())
        content["review_rule"]["independent_reviewers"] = 0
        protocol.write_text(json.dumps(content))
    out = tmp_path / "must-not-publish"
    with pytest.raises(ValueError):
        module.prepare(database, ids, protocol, out)
    assert not out.exists()
