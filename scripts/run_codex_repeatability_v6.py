"""Two explicit V6 reruns and pending human cards bound to the accepted seven-quarter set."""

import argparse
import html
import json
import os
import sqlite3
from pathlib import Path
from typing import get_args

import resume_codex_validation_v6 as resume
import run_codex_validation_v6 as base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from valuation_engine.ai.attempt_journal import AttemptJournal, workspace_fingerprint
from valuation_engine.ai.contracts import FeatureName
from valuation_engine.ai.validation import CATEGORIES, compare
from valuation_engine.config import Settings
from valuation_engine.db.session import engine
from valuation_engine.research.numbers import canonical

PLAN_VERSION = "CodexRepeatabilityPlanV1"
BUDGET_VERSION = "CodexStageBudgetV1"


def serialized(row):
    return {column.name: getattr(row, column.key) for column in row.__table__.columns}


def rows_hash(rows):
    return base.digest(
        {
            key: [serialized(r) for r in sorted(value, key=lambda r: r.id)]
            if isinstance(value, list)
            else serialized(value)
            if value is not None
            else None
            for key, value in rows.items()
        }
    )


def effective_budget(rows):
    """Legacy receipts lack a profile label; verify the actual recorded limits."""
    budget = base.execution_budget(BUDGET_VERSION)
    if rows.get("run") is None or not rows.get("calls"):
        raise ValueError("Baseline execution metadata missing")
    settings = rows["run"].settings_json
    records = [settings] + [c.raw_output.get("execution_metadata", {}) for c in rows["calls"]]
    for record in records:
        if (
            record.get("timeout_seconds") != 180
            or record.get("max_attempts") != 2
            or ("execution_budget" in record and record["execution_budget"] != budget)
        ):
            raise ValueError("Execution budget is not the baseline V1 profile")
    for call in rows["calls"]:
        meta = call.raw_output.get("execution_metadata", {})
        if (
            call.stage not in budget["stage_seconds"]
            or meta.get("stage_timeout_seconds") != budget["stage_seconds"].get(call.stage)
            or type(meta.get("retry_count")) is not int
            or not 0 <= meta["retry_count"] < 2
            or meta.get("reused_from_call_id") is not None
        ):
            raise ValueError("Actual execution limits or freshness differ")
    return budget


def validate_completed_receipt(final, plan, origin):
    terminal = json.loads((origin / "progress.jsonl").read_text().splitlines()[-1])
    expected_refs = {**plan["references"], "plan": final["references"]["plan"]}
    if (
        final.get("gate") != "PASS"
        or final.get("required_quarters") != 7
        or final.get("completed_quarters") != 7
        or final.get("process_state_unknown") is not False
        or final.get("inherited_results") != plan["inherited_results"]
        or final.get("execution_budget") != plan["execution_budget"]
        or final.get("references") != expected_refs
        or [r.get("quarter") for r in final.get("results", [])] != plan["quarters"]
        or any(r.get("gate") != "PASS" for r in final["results"])
        or terminal.get("event") != "finished"
        or terminal.get("status") != "completed"
        or terminal.get("attempt_id") != final.get("attempt_id")
        or origin.name != final.get("attempt_id")
    ):
        raise ValueError("A confirmed complete seven-quarter cohort is required")


def verify_new_cohort_row(db, row, expected, refs, directory, budget):
    result_ref, saved = base.reference(directory / "result.json")
    context_ref, context = base.reference(directory / "context.json")
    preflight_ref, preflight = base.reference(directory / "preflight.json")
    if (
        saved != row
        or row.get("references") != refs
        or row.get("model_started") is not True
        or row.get("preservation_unchanged") is not True
        or row.get("execution_budget") != budget
        or preflight.get("status") != "PASS"
        or preflight.get("references") != refs
        or preflight.get("execution_budget") != budget
        or row.get("preflight_sha256") != preflight_ref["sha256"]
        or preflight.get("approved_context_sha256") != row.get("context_hash")
        or row.get("context_hash") != expected["context_hash"]
        or base.context_identity(context) != expected
    ):
        raise ValueError("Accepted quarter receipt or input differs")
    rows = base.run_rows(db, row["analysis_run_id"])
    assessment = base.assess_run(
        rows, row["quarter"], row["context_hash"], refs["isolation"], refs["kernel"]
    )
    if (
        assessment["gate"] != "PASS"
        or any(row.get(k) != v for k, v in assessment.items())
        or base.verify_execution_budget(rows, budget)
        or rows["snapshot"] is None
        or rows["snapshot"].id != row["snapshot_id"]
        or len(rows["calls"]) != row["calls"]
        or sum(c.status == "valid" for c in rows["calls"]) != row["valid_calls"]
        or rows["snapshot"].metadata_json.get("missing_features", []) != row["missing_features"]
    ):
        raise ValueError("Accepted quarter no longer matches formal database")
    return rows, {"result": result_ref, "context": context_ref, "preflight": preflight_ref}


def prepare_plan(db, settings, cohort_ref):
    final = resume.read_bound(cohort_ref)
    old_plan_ref = final["references"]["plan"]
    old_plan = resume.read_bound(old_plan_ref)
    core_refs = {k: old_plan["references"][k] for k in ("pilot", "isolation", "kernel")}
    fresh = resume.prepare_resume_plan(
        db, settings, old_plan["references"]["previous_validation"], core_refs
    )
    resume.require_exact_plan(old_plan, fresh)
    origin = Path(cohort_ref["path"]).parent
    validate_completed_receipt(final, old_plan, origin)
    refs = {
        **final["references"],
        "completed_cohort": cohort_ref,
        "completed_progress": resume.byte_reference(origin / "progress.jsonl"),
    }
    pilot = resume.read_bound(core_refs["pilot"])
    accepted = [
        {
            "quarter": base.QUARTERS[0],
            "analysis_run_id": pilot["analysis_run_id"],
            "snapshot_id": pilot["snapshot_id"],
            "receipt": core_refs["pilot"],
            "execution_budget": base.execution_budget(BUDGET_VERSION),
        }
    ]
    accepted += old_plan["inherited_results"]
    for i, row in enumerate(final["results"]):
        _, bound = verify_new_cohort_row(
            db,
            row,
            old_plan["inputs"][row["quarter"]],
            final["references"],
            origin / "quarters" / row["quarter"],
            old_plan["execution_budget"],
        )
        refs.update({f"accepted_{i}_{name}": ref for name, ref in bound.items()})
        accepted.append(
            {
                "quarter": row["quarter"],
                "analysis_run_id": row["analysis_run_id"],
                "snapshot_id": row["snapshot_id"],
                "receipt": bound["result"],
                "execution_budget": old_plan["execution_budget"],
            }
        )
    if [a["quarter"] for a in accepted] != list(base.QUARTERS):
        raise ValueError("Incomplete or reordered accepted set")
    inputs, data_hashes = {}, {}
    for row in accepted:
        rows = base.run_rows(db, row["analysis_run_id"])
        data_hashes[row["quarter"]] = rows_hash(rows)
        if row["quarter"] in base.QUARTERS[:2]:
            effective_budget(rows)
            current = base.prepare(
                db, base.resolve_run(db, 1, row["quarter"]), settings.qve_raw_dir
            )
            if base.digest(current) != base.digest(rows["run"].context_json):
                raise ValueError("Repeat input changed from the accepted baseline")
            inputs[row["quarter"]] = base.context_identity(current)
    return {
        "version": PLAN_VERSION,
        "contract": base.contract(),
        "references": refs,
        "accepted_results": accepted,
        "accepted_data_hashes": data_hashes,
        "quarters": list(base.QUARTERS[:2]),
        "inputs": inputs,
        "execution_budget": base.execution_budget(BUDGET_VERSION),
        "required_human_reviews": 35,
        "semantic_stability": "human_interpretation_required",
    }


def compare_pair(db, first, second):
    a, b = base.run_rows(db, first), base.run_rows(db, second)
    if first == second or a["snapshot"] is None or b["snapshot"] is None:
        raise ValueError("Comparison requires two fresh completed snapshots")
    metrics = compare(db, first, second)

    def extract_hashes(rows):
        return [
            c.request_hash
            for c in sorted(rows["calls"], key=lambda c: c.id)
            if c.stage == "extract"
        ]

    required = {
        k: metrics[k]
        for k in (
            "same_provider",
            "same_context",
            "same_prompt_version",
            "same_schema_version",
            "same_package_hash",
            "same_requested_model",
            "same_cli_version",
        )
    }
    required.update(
        same_policy_version=a["run"].policy_version == b["run"].policy_version,
        same_execution_budget=effective_budget(a) == effective_budget(b),
        same_extract_prompt_hashes=extract_hashes(a) == extract_hashes(b),
        new_budget_attested=not base.verify_execution_budget(
            b, base.execution_budget(BUDGET_VERSION)
        ),
    )
    af, bf = ({f.feature_name: f.feature_value for f in rows["features"]} for rows in (a, b))
    feature_differences = [
        {
            "feature": name,
            "first_value": af.get(name),
            "second_value": bf.get(name),
            "delta": bf[name] - af[name] if name in af and name in bf else None,
            "opposite_sign": name in af and name in bf and af[name] * bf[name] < 0,
        }
        for name in get_args(FeatureName)
    ]
    return canonical(
        {
            **metrics,
            "gate": "PASS" if all(required.values()) else "FAIL",
            "comparison_complete": all(required.values()),
            "conditions": required,
            "first_missing_features": a["snapshot"].metadata_json.get("missing_features", []),
            "second_missing_features": b["snapshot"].metadata_json.get("missing_features", []),
            "feature_differences": feature_differences,
            "execution_budget": base.execution_budget(BUDGET_VERSION),
            "exact_prompt_note": "Extraction requests must match. Later prompts depend on newly generated evidence/features; their full hashes may differ.",
            "actual_model_identity_verified": False,
            "m4_1_final_pass": False,
        }
    )


def review_cards(plan, dossiers):
    accepted = plan["accepted_results"]
    if (
        [r["quarter"] for r in accepted] != list(base.QUARTERS)
        or any(not r.get("analysis_run_id") or not r.get("snapshot_id") for r in accepted)
        or len({r["analysis_run_id"] for r in accepted}) != 7
    ):
        raise ValueError("Cards require the explicit accepted seven-quarter set")
    return [
        {
            "quarter": row["quarter"],
            "category": category,
            "analysis_run_id": row["analysis_run_id"],
            "snapshot_id": row["snapshot_id"],
            "provider": "codex_cli",
            "requested_model": base.gates.MODEL,
            "prompt_version": base.PROMPT,
            "baseline_receipt": row["receipt"],
            "dossier": dossiers[row["quarter"]],
            "status": "pending_human_review",
            "verdict": None,
            "reviewer": None,
            "reviewed_at": None,
            "notes": None,
            "evidence_ids": [],
            "semantic_support": None,
        }
        for row in accepted[:5]
        for category in CATEGORIES
    ]


def text_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(value)


def export_review(db, plan, out):
    """Read-only DB export into a new immutable package, never a review submission."""
    if out.exists():
        raise FileExistsError("Review output must be a new directory")
    prepared = []
    for selected in plan["accepted_results"][:5]:
        rows = base.run_rows(db, selected["analysis_run_id"])
        if (
            rows_hash(rows) != plan["accepted_data_hashes"][selected["quarter"]]
            or rows["snapshot"].id != selected["snapshot_id"]
        ):
            raise ValueError("Review baseline changed")
        prepared.append((selected, rows))
    dossiers = {}
    for selected, rows in prepared:
        quarter = selected["quarter"]
        dossier = {
            "quarter": quarter,
            "analysis_run_id": selected["analysis_run_id"],
            "snapshot_id": selected["snapshot_id"],
            "baseline_receipt": selected["receipt"],
            "information_cutoff": rows["run"].context_json["quant_context"]["information_cutoff"],
            "source_documents": rows["run"].context_json["sources"]["documents"],
            "snapshot": serialized(rows["snapshot"]),
            **{
                key: [serialized(r) for r in rows[key]]
                for key in ("features", "evidence", "challenges", "rejected")
            },
        }
        path = out / "dossiers" / (quarter + ".json")
        base.gates.save(path, dossier)
        dossiers[quarter] = resume.byte_reference(path)
        lines = [
            f"# {quarter} — 核准基線證據冊",
            "",
            f"Run {selected['analysis_run_id']} / snapshot {selected['snapshot_id']}；PromptSetV6。",
            "以下為 AI 原始解讀與當時可用的引用，語義正確性仍待真人判定。",
            "",
            f"完整結構資料：[dossier JSON]({quarter}.json)。",
            "",
            "## 特徵與原始解讀",
            "",
        ]
        for feature in rows["features"]:
            lines += [
                f"### {feature.feature_name}",
                "",
                f"值：{feature.feature_value}；信心：{feature.confidence}；方向：{feature.direction}",
                "",
                html.escape(feature.rationale),
                "",
            ]
            keys = feature.metadata_json.get("evidence_keys", [])
            lines += [
                "引用："
                + ", ".join(
                    f"[evidence {e.id}](#evidence-{e.id})"
                    for e in rows["evidence"]
                    if e.evidence_key in keys
                ),
                "",
            ]
        lines += [
            "明確缺漏：" + ", ".join(rows["snapshot"].metadata_json.get("missing_features", [])),
            "",
            "## 分節解讀",
            "",
        ]
        for name, section in rows["snapshot"].metadata_json.get("sections", {}).items():
            lines += [
                f"### {html.escape(name)}",
                "",
                html.escape(section["summary"]),
                "",
                "引用："
                + ", ".join(
                    f"[evidence {eid}](#evidence-{eid})" for eid in section.get("evidence_ids", [])
                ),
                "",
            ]
        lines += ["## 反方檢驗", ""]
        for challenge in rows["challenges"]:
            lines += [
                f"### {challenge.kind} / {challenge.target_variable}",
                "",
                html.escape(challenge.description),
                "",
                "引用："
                + ", ".join(f"[evidence {eid}](#evidence-{eid})" for eid in challenge.evidence_ids),
                "",
            ]
        lines += ["## 正式證據", ""]
        for evidence in rows["evidence"]:
            lines += [
                f'<a id="evidence-{evidence.id}"></a>',
                f"### Evidence {evidence.id} — {evidence.topic}",
                "",
                f"Source {evidence.source_document_id} / block `{evidence.block_id}` / SHA-256 `{evidence.source_hash}`",
                f"Available at: {evidence.available_at.isoformat()}",
                "",
                "<pre>" + html.escape(evidence.span) + "</pre>",
                "",
                "AI implication: " + html.escape(evidence.implication),
                "",
            ]
        lines += [
            "## 隔離拒絕紀錄",
            "",
            "以下候選不構成正式支持：",
            "",
            "<pre>"
            + html.escape(json.dumps(canonical(dossier["rejected"]), ensure_ascii=False, indent=2))
            + "</pre>",
            "",
        ]
        text_once(out / "dossiers" / (quarter + ".md"), "\n".join(lines))
    cards = review_cards(plan, dossiers)
    base.gates.save(out / "human-review-cards.generated.json", cards)
    base.gates.save(
        out / "human-review-status.json",
        {
            "required": 35,
            "completed": 0,
            "pending": 35,
            "package_submissions": 0,
            "counts_are_for_this_new_package": True,
            "database_reviews_not_modified": True,
            "correct_rate": None,
            "correct_plus_partial_rate": None,
            "unsupported_rate": None,
            "miss_rate": None,
            "rate_denominator": 0,
            "human_gate_complete": False,
        },
    )
    labels = {
        "demand": "需求",
        "supply": "供給",
        "competition": "競爭",
        "product_cycle": "產品週期",
        "management": "管理層",
        "anomalies": "異常",
        "model_challenge": "模型挑戰",
    }
    guide = [
        "# StockOS M4.1 真人審查包",
        "",
        "35 張卡均待真人填寫；沒有預填 PASS，也沒有寫入正式 DB 的真人判定。",
        "",
        "每張卡先閱讀對應季度證據冊，核對原始引用與 AI 解讀。檢查擷取、語義支持、無支持推論、漏失洞察與未來資訊洩漏。",
        "",
        "允許 verdict：correct、partially_correct、unsupported、missed。reviewer、含時區 reviewed_at、notes 及 evidence_ids 必須由真人提供。",
        "原始 generated 檔保持不變；將填答保存為新的 submission 檔案，之後再驗證及匯入。",
        "",
        "| 季度 | 類別 | Run / snapshot | 卡片 |",
        "|---|---|---|---|",
    ]
    for card in cards:
        q, category = card["quarter"], card["category"]
        name = q + "-" + category + ".md"
        content = [
            f"# {q} — {labels[category]}",
            "",
            f"Run {card['analysis_run_id']} / snapshot {card['snapshot_id']}，{card['prompt_version']}。",
            "",
            "狀態：待真人審查。",
            "",
            f"[季度完整證據冊](../dossiers/{q}.md) · [結構化引用](../dossiers/{q}.json)",
            "",
            "請針對此類別核對擷取是否正確、解讀是否有足夠支持、是否有無支持推論或漏失洞察，以及是否用了截止日後資訊。",
            "",
            "| 真人填答欄位 | 答案 |",
            "|---|---|",
            "| verdict | 待填 |",
            "| reviewer | 待填 |",
            "| reviewed_at（含時區） | 待填 |",
            "| notes／判斷理由 | 待填 |",
            "| evidence_ids | 待選 |",
            "",
        ]
        text_once(out / "cards" / name, "\n".join(content))
        guide.append(
            f"| {q} | {labels[category]} | {card['analysis_run_id']} / {card['snapshot_id']} | [開啟](cards/{name}) |"
        )
    text_once(out / "REVIEW_GUIDE.md", "\n".join(guide) + "\n")
    base.gates.save(
        out / "manifest.json",
        {
            "version": "CodexHumanReviewPackageV1",
            "accepted_results": plan["accepted_results"][:5],
            "required": 35,
            "generated": len(cards),
            "human_judgments": 0,
            "files": [resume.byte_reference(p) for p in sorted(out.rglob("*")) if p.is_file()],
        },
    )
    return {
        "generated_cards": len(cards),
        "human_judgments": 0,
        "guide": str((out / "REVIEW_GUIDE.md").resolve()),
    }


def execute_repeat(db, settings, quarter, plan, refs, isolation, kernel, journal):
    baseline = next(r for r in plan["accepted_results"] if r["quarter"] == quarter)
    if (
        rows_hash(base.run_rows(db, baseline["analysis_run_id"]))
        != plan["accepted_data_hashes"][quarter]
    ):
        raise ValueError("Baseline changed immediately before repeat")
    row = base.run_quarter(
        db,
        settings,
        quarter,
        plan["inputs"][quarter],
        refs,
        isolation,
        kernel,
        journal,
        budget_version=BUDGET_VERSION,
    )
    comparison = None
    if row["gate"] == "PASS":
        comparison = compare_pair(db, baseline["analysis_run_id"], row["analysis_run_id"])
        base.gates.save(journal.path / "quarters" / quarter / "comparison.json", comparison)
    return {
        "quarter": quarter,
        "gate": comparison["gate"] if comparison else "FAIL",
        "baseline_run_id": baseline["analysis_run_id"],
        "result": row,
        "comparison": comparison,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-receipt", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-plan", type=Path)
    mode.add_argument("--export-review", type=Path)
    mode.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args(argv)
    if args.plan and not base.gates._is_sha256(args.plan_sha256):
        parser.error("Execution requires the exact --plan-sha256")
    cohort_ref, _ = base.reference(args.cohort_receipt)
    settings = Settings()
    if not settings.qve_database_url.startswith("sqlite:///"):
        raise ValueError("Repeatability requires the verified formal SQLite checkout")
    path = Path(settings.qve_database_url.removeprefix("sqlite:///")).resolve()
    readonly = create_engine(
        "sqlite://", creator=lambda: sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    )
    try:
        with Session(readonly) as db:
            expected = prepare_plan(db, settings, cohort_ref)
            if args.export_review:
                print(json.dumps(export_review(db, expected, args.export_review)))
                return 0
    finally:
        readonly.dispose()
    if args.prepare_plan:
        base.gates.save(args.prepare_plan, expected)
        print(
            json.dumps(
                {"plan": resume.byte_reference(args.prepare_plan), "quarters": expected["quarters"]}
            )
        )
        return 0
    plan_ref, plan = base.reference(args.plan)
    if plan_ref["sha256"] != args.plan_sha256 or plan != expected:
        raise ValueError("Repeat plan bytes or current baseline changed")
    refs = {**plan["references"], "repeat_plan": plan_ref}
    isolation, kernel = (resume.read_bound(refs[k]) for k in ("isolation", "kernel"))
    journal = AttemptJournal(
        base.gates.OUT / "attempts",
        purpose="codex_pit_repeatability_v6",
        manifest={
            "git": workspace_fingerprint(Path.cwd()),
            "references": refs,
            "execution_budget": plan["execution_budget"],
            "contract": base.contract(),
        },
    )
    results = []
    outcome, error_type = "failed", None
    try:
        journal.emit("runner_started", stage="repeatability", status="started", pid=os.getpid())
        with Session(engine(settings.qve_database_url)) as db:
            if prepare_plan(db, settings, cohort_ref) != plan:
                raise ValueError("Repeat prerequisites changed at activation")

            def record(current):
                results[:] = current
                base.gates.save(
                    journal.path / f"progress-{len(current):02d}.json", {"results": current}
                )

            base.execute_quarters(
                plan,
                lambda q: execute_repeat(db, settings, q, plan, refs, isolation, kernel, journal),
                record,
            )
        if len(results) == 2 and all(row["gate"] == "PASS" for row in results):
            outcome = "completed"
        return 0 if outcome == "completed" else 1
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        base.gates.save(
            journal.path / "repeatability.json",
            {
                "gate": "PASS" if outcome == "completed" else "FAIL",
                "results": results,
                "completed_comparisons": sum(row["gate"] == "PASS" for row in results),
                "required_comparisons": 2,
                "attempt_id": journal.attempt_id,
                "references": refs,
                "execution_budget": plan["execution_budget"],
                "error_type": error_type,
                "process_state_unknown": journal.process_state_unknown,
                "semantic_stability": "human_interpretation_required",
                "m4_1_final_pass": False,
            },
        )
        journal.finish(
            status="unknown" if journal.process_state_unknown else outcome,
            failure_kind="termination_unconfirmed" if journal.process_state_unknown else None,
            error_type=error_type,
        )


if __name__ == "__main__":
    raise SystemExit(main())
