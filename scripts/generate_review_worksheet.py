#!/usr/bin/env python3
"""Generate an unfilled human-review worksheet from explicitly selected dossiers.

Inputs are exported run/snapshot dossiers and a JSON object mapping each quarter
onto {"analysis_run_id": <id>, "snapshot_id": <id>}. No historical IDs or database
are selected implicitly. The adjacent .bindings.json pins the exact source bytes
and must accompany the worksheet when importing actual human submissions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from valuation_engine.ai.contracts import ReviewDraft

BINDING_VERSION = "human-review-bindings-v1"
CATEGORIES = get_args(ReviewDraft.model_fields["category"].annotation)
QUARTER_PATTERN = re.compile(r"FY\d{4}-Q[1-4]")


def positive_id(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def validate_dossier(quarter: str, dossier: dict, selection: dict) -> None:
    """Fail closed on unavailable or internally inconsistent review evidence."""
    if not QUARTER_PATTERN.fullmatch(quarter):
        raise ValueError(f"Invalid quarter: {quarter}")
    if not isinstance(selection, dict) or set(selection) != {"analysis_run_id", "snapshot_id"}:
        raise ValueError(f"Explicit run/snapshot selection required for {quarter}")
    run_id = positive_id(selection["analysis_run_id"], "analysis_run_id")
    snapshot_id = positive_id(selection["snapshot_id"], "snapshot_id")
    run, snapshot = dossier.get("run"), dossier.get("snapshot")
    if not isinstance(run, dict) or not isinstance(snapshot, dict):
        raise ValueError(f"Completed run and snapshot unavailable for {quarter}")
    positive_id(run.get("id"), "run.id")
    positive_id(snapshot.get("id"), "snapshot.id")
    positive_id(snapshot.get("analysis_run_id"), "snapshot.analysis_run_id")
    positive_id(run.get("company_id"), "run.company_id")
    positive_id(snapshot.get("company_id"), "snapshot.company_id")
    for field in (
        "request_hash",
        "model_provider",
        "model_name",
        "model_version",
        "prompt_version",
        "schema_version",
    ):
        if not isinstance(run.get(field), str) or not run[field].strip():
            raise ValueError(f"Run {field} unavailable for {quarter}")
    if run.get("id") != run_id or run.get("quarter") != quarter:
        raise ValueError(f"Dossier run/quarter mismatch for {quarter}")
    if snapshot.get("id") != snapshot_id or snapshot.get("analysis_run_id") != run_id:
        raise ValueError(f"Dossier snapshot/run mismatch for {quarter}")
    for field in ("company_id", "prompt_version", "model_version"):
        if field in run and snapshot.get(field) != run[field]:
            raise ValueError(f"Dossier snapshot {field} mismatch for {quarter}")
    evidence = dossier.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(f"Evidence unavailable for {quarter}")
    evidence_ids, evidence_keys = set(), set()
    for row in evidence:
        if not isinstance(row, dict):
            raise ValueError(f"Invalid evidence row for {quarter}")
        positive_id(row.get("analysis_run_id"), "evidence.analysis_run_id")
        positive_id(row.get("source_document_id"), "evidence.source_document_id")
        for field in ("source_hash", "span_hash", "block_id"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError(f"Evidence {field} unavailable for {quarter}")
        eid = positive_id(row.get("id"), "evidence.id")
        key = row.get("evidence_key")
        if row.get("analysis_run_id") != run_id:
            raise ValueError(f"Evidence belongs to another run for {quarter}")
        if eid in evidence_ids or not isinstance(key, str) or not key or key in evidence_keys:
            raise ValueError(f"Duplicate or missing evidence identity for {quarter}")
        if not isinstance(row.get("span"), str) or not row["span"].strip():
            raise ValueError(f"Evidence span unavailable for {quarter}")
        evidence_ids.add(eid)
        evidence_keys.add(key)
    feature_names = set()
    for collection in ("features", "challenges"):
        rows = dossier.get(collection)
        if not isinstance(rows, list):
            raise ValueError(f"{collection} unavailable for {quarter}")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Invalid {collection} row for {quarter}")
            positive_id(row.get("id"), f"{collection}.id")
            positive_id(row.get("analysis_run_id"), f"{collection}.analysis_run_id")
            if row.get("analysis_run_id") != run_id:
                raise ValueError(f"{collection} belongs to another run for {quarter}")
            if collection == "features":
                name = row.get("feature_name")
                if not name or name in feature_names:
                    raise ValueError(f"Duplicate or missing feature identity for {quarter}")
                feature_names.add(name)
                if "feature_value" not in row or row["feature_value"] is None:
                    raise ValueError(f"Feature value unavailable for {quarter}")
                if not isinstance(row.get("metadata_json"), dict):
                    raise ValueError(f"Feature metadata unavailable for {quarter}")
                keys = row["metadata_json"].get("evidence_keys", [])
                if not isinstance(keys, list) or not set(keys) <= evidence_keys:
                    raise ValueError(f"Feature references unavailable evidence for {quarter}")
            else:
                ids = row.get("evidence_ids")
                if not isinstance(ids, list) or any(type(eid) is not int for eid in ids):
                    raise ValueError(f"Invalid challenge evidence for {quarter}")
                if not set(ids) <= evidence_ids:
                    raise ValueError(f"Challenge references unavailable evidence for {quarter}")


def load_dossiers(dossiers_dir: Path, selections: dict) -> dict[str, dict]:
    if not selections:
        raise ValueError("At least one explicit run/snapshot selection is required")
    dossiers = {}
    for quarter, selection in sorted(selections.items()):
        if not isinstance(quarter, str) or not QUARTER_PATTERN.fullmatch(quarter):
            raise ValueError(f"Invalid quarter: {quarter}")
        dossier = read_object(dossiers_dir / f"{quarter}.json")
        validate_dossier(quarter, dossier, selection)
        dossiers[quarter] = dossier
    return dossiers


def build_bindings(dossiers_dir: Path, selections: dict, dossiers: dict) -> dict:
    bindings: dict = {"schema_version": BINDING_VERSION, "dossiers": {}, "cards": {}}
    index = 1
    for quarter, dossier in dossiers.items():
        selection = selections[quarter]
        source_bytes = (dossiers_dir / f"{quarter}.json").read_bytes()
        if json.loads(source_bytes) != dossier:
            raise ValueError(f"Dossier changed while preparing bindings: {quarter}")
        bindings["dossiers"][quarter] = {
            **selection,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        }
        for category in CATEGORIES:
            bindings["cards"][f"CARD-{index:02d}"] = {
                "quarter": quarter,
                "category": category,
                **selection,
                "evidence_ids": sorted(e["id"] for e in dossier["evidence"]),
            }
            index += 1
    return bindings


CATEGORY_FEATURE_MAP = {
    "demand": [
        "demand_momentum",
        "demand_visibility",
        "customer_adoption",
        "inference_demand",
        "training_demand",
        "long_term_demand_durability",
    ],
    "supply": [
        "supply_constraint",
        "inventory_quality",
        "working_capital_quality",
    ],
    "competition": [
        "competition_outlook",
        "custom_asic_outlook",
        "customer_insourcing_outlook",
        "ecosystem_strength",
        "switching_cost_strength",
        "moat_strength_signal",
    ],
    "product_cycle": [
        "product_cycle_strength",
        "structural_outlook",
    ],
    "management": [
        "management_confidence",
        "guidance_visibility",
        "management_credibility_signal",
        "pricing_power",
        "margin_outlook",
        "revenue_quality",
        "customer_financing_quality",
        "customer_concentration_outlook",
    ],
    "anomalies": [
        "china_outlook",
        "export_control_outlook",
        "regulatory_outlook",
    ],
}


def load_focus_data(focus_json: Path | None) -> tuple[dict, dict[int, dict]]:
    if focus_json is None:
        return {"quarters": []}, {}
    data = read_object(focus_json)
    if not isinstance(data.get("quarters"), list) or not isinstance(data.get("evidence"), list):
        raise ValueError("Focus input requires quarters and evidence lists")
    evidence_map = {}
    for evidence in data["evidence"]:
        eid = positive_id(evidence.get("id"), "focus evidence.id")
        if eid in evidence_map:
            raise ValueError("Duplicate focus evidence ID")
        evidence_map[eid] = evidence
    for quarter in data["quarters"]:
        for item in quarter.get("priority_changes", []):
            for side in [item, *item.get("sides", [])]:
                if not set(side.get("evidence_ids", [])) <= evidence_map.keys():
                    raise ValueError("Focus references unavailable evidence")
    return data, evidence_map


def load_cases_data(cases_dir: Path | None) -> list[dict]:
    if cases_dir is None:
        return []
    paths = sorted(cases_dir.glob("feature-*.md"))
    if not paths:
        raise ValueError(f"Case inputs unavailable: {cases_dir}")
    cases = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        title_match = re.search(r"#\s+(feature-\d+)\s+—\s+([a-z_]+)", text)
        feature_id = title_match.group(1) if title_match else path.stem
        feature_name = title_match.group(2) if title_match else ""

        run_snap_match = re.search(r"Run / snapshot：(\d+)\s+/\s+(\d+)", text)
        run_id = int(run_snap_match.group(1)) if run_snap_match else 0
        snap_id = int(run_snap_match.group(2)) if run_snap_match else 0
        if not title_match or run_id <= 0 or snap_id <= 0:
            raise ValueError(f"Case run/snapshot identity unavailable: {path}")

        old_match = re.search(
            r"原狀態：([^；\n]+)；原分數：([^；\n]+)；原保存 confidence：([^\n]+)", text
        )
        old_status = old_match.group(1) if old_match else "unknown"
        old_score = old_match.group(2) if old_match else "unknown"
        old_conf = old_match.group(3) if old_match else "unknown"

        guard_match = re.search(r"新 G：([^；\n]+)", text)
        guard_reason = guard_match.group(1) if guard_match else "unknown"

        claim_match = re.search(r"## 原始主張\s*\n\s*Interpretation:\s*([^\n]+)", text)
        claim = claim_match.group(1) if claim_match else ""

        # Extract quotes
        quotes = []
        for quote_match in re.finditer(r">\s*([^\n]+)\s*\n\s*source=(\d+)", text):
            quotes.append(f"{quote_match.group(1).strip()} (source {quote_match.group(2)})")

        cases.append(
            {
                "id": feature_id,
                "feature_name": feature_name,
                "run_id": run_id,
                "snap_id": snap_id,
                "old_status": old_status,
                "old_score": old_score,
                "old_conf": old_conf,
                "guard_reason": guard_reason,
                "claim": claim,
                "quotes": quotes[:3],
            }
        )
    return cases


def generate_worksheet(
    *,
    dossiers_dir: Path,
    selection_path: Path,
    output_file: Path,
    focus_json: Path | None = None,
    cases_dir: Path | None = None,
) -> Path:
    selections = read_object(selection_path)
    dossiers = load_dossiers(dossiers_dir, selections)
    bindings = build_bindings(dossiers_dir, selections, dossiers)
    focus_data, evidence_map = load_focus_data(focus_json)
    cases_data = load_cases_data(cases_dir)
    binding_file = output_file.with_suffix(".bindings.json")
    if output_file.exists() or binding_file.exists():
        raise FileExistsError("Refusing to overwrite an existing worksheet or binding manifest")

    now_iso = datetime.now(UTC).astimezone().isoformat()

    lines: list[str] = []
    lines.append("# StockOS M4.1 真人審查集中工作表 (Consolidated Review Worksheet)\n")
    lines.append(f"- 產生時間：`{now_iso}`")
    lines.append("- 審查者、判定與含時區的實際審查時間均須由真人填寫；產生時間不是審查時間。")
    lines.append(
        "- 審查指引：核對原始財報事實，確認 AI 解讀是否有支持、是否有幻覺、是否遺漏關鍵反證。"
    )
    lines.append("\n### 合法判定標準（Verdict）說明：")
    lines.append("- `correct`：AI 主張有足夠財報文字支持，無重大推論扭曲或反證遺漏。")
    lines.append("- `partially_correct`：AI 抓到部分事實，但定性幅度誇大、輕微過度推論或方向偏誤。")
    lines.append("- `unsupported`：AI 主張缺乏財報支持、憑空捏造數字或關鍵支持證據為空（幻覺）。")
    lines.append("- `missed`：財報中有顯著且可檢驗的重要相反事實，但 AI 完全漏未提及。\n")
    lines.append("---\n")

    # ==========================================
    # Part 1: Supplied priority changes
    # ==========================================
    lines.append("## Part 1：核心翻轉與狀態變化特徵（重跑差異優先裁定）\n")
    lines.append(
        "> 說明：依所提供的重跑差異，以下指標出現了**正負翻轉**或**有值變為缺漏**。"
        "請檢閱原文與 AI 解讀，在下方表格中填入判定。\n"
    )

    p1_index = 1
    p1_items = []

    for quarter_obj in focus_data.get("quarters", []):
        quarter = quarter_obj["quarter"]
        for item in quarter_obj.get("priority_changes", []):
            diff = item["difference"]
            feature_name = diff["feature"]
            reason = item["review_reason"]
            first_val = diff.get("first_value")
            second_val = diff.get("second_value")

            # Extract baseline vs repeat interpretation
            sides = item.get("sides", [])
            base_side = sides[0] if len(sides) > 0 else {}
            repeat_side = sides[1] if len(sides) > 1 else {}

            base_feat = base_side.get("admitted_feature") or {}
            base_claim = (
                base_feat.get("rationale") or base_feat.get("net_assessment") or "無正式特徵"
            )

            repeat_feat = repeat_side.get("admitted_feature")
            if repeat_feat:
                repeat_claim = (
                    repeat_feat.get("rationale") or repeat_feat.get("net_assessment") or ""
                )
                repeat_status = f"有值 ({second_val})"
            else:
                rejected = repeat_side.get("rejected_candidates") or []
                if rejected:
                    raw = rejected[0].get("raw_claim") or {}
                    repeat_claim = f"[被拒候選]: {raw.get('net_assessment', '')}"
                    repeat_status = f"被隔離 ({rejected[0].get('reason', '')})"
                else:
                    repeat_claim = "無候選產物"
                    repeat_status = "缺漏 (None)"

            # Evidence sample spans
            evidence_ids = item.get("evidence_ids", []) or base_side.get("evidence_ids", [])
            sample_spans = []
            for eid in evidence_ids[:2]:
                if eid in evidence_map:
                    ev = evidence_map[eid]
                    span_text = ev.get("span", "").strip()
                    sec = ev.get("section", "")
                    sample_spans.append(f"「{span_text}」({sec})")

            item_id = f"P1-{p1_index:02d}"
            p1_items.append(
                {
                    "item_id": item_id,
                    "quarter": quarter,
                    "feature": feature_name,
                    "reason": reason,
                    "first_val": first_val,
                    "second_val": second_val,
                    "base_claim": base_claim,
                    "repeat_status": repeat_status,
                    "repeat_claim": repeat_claim,
                    "spans": sample_spans,
                    "evidence_ids": evidence_ids[:10],
                }
            )
            p1_index += 1

    for it in p1_items:
        lines.append(f"### [{it['item_id']}] {it['quarter']} — `{it['feature']}`")
        lines.append(
            f"- **變動類型**：{it['reason']}（基線: `{it['first_val']}` → 重跑: `{it['second_val']}`，狀態: {it['repeat_status']}）"
        )
        lines.append(f"- **基線 AI 解讀**：{it['base_claim']}")
        if it["repeat_claim"]:
            lines.append(f"- **重跑 AI 解讀**：{it['repeat_claim']}")
        if it["spans"]:
            lines.append("- **關鍵財報原文引用**：")
            for sp in it["spans"]:
                lines.append(f"  > {sp}")
        lines.append("\n**【填答區】**")
        lines.append("| 欄位 | 填寫值 |")
        lines.append("|---|---|")
        lines.append(f"| item_id | `{it['item_id']}` |")
        lines.append(
            "| verdict | 待填（選填: correct / partially_correct / unsupported / missed） |"
        )
        lines.append("| reviewer | 待填 |")
        lines.append("| reviewed_at | 待填（實際審查時間，含時區） |")
        lines.append("| notes / 理由 | 待填（簡要寫明對該指標變動的判讀理由） |")
        lines.append(f"| evidence_ids | {it['evidence_ids']} |")
        lines.append("\n")

    lines.append("---\n")

    # ==========================================
    # Part 2: Supplied empty-support cases
    # ==========================================
    lines.append("## Part 2：原空支持案例（Guard G 沒收合理性確認）\n")
    lines.append(
        "> 說明：下列案例來自明確指定的歷史審核材料。請依原始證據確認 Guard G 的處分是否合理。\n"
    )

    p2_index = 1
    for c in cases_data:
        case_code = f"P2-{p2_index:02d}"
        lines.append(
            f"### [{case_code}] {c['id']} — `{c['feature_name']}` (Run {c['run_id']} / Snapshot {c['snap_id']})"
        )
        lines.append(
            f"- **歷史給分**：`{c['old_score']}`（狀態: {c['old_status']}，Confidence: {c['old_conf']}）"
        )
        lines.append(f"- **Guard G 處分**：`{c['guard_reason']}`")
        if c["claim"]:
            lines.append(f"- **AI 原始解讀**：{c['claim']}")
        if c["quotes"]:
            lines.append("- **關聯引文片段**：")
            for q in c["quotes"]:
                lines.append(f"  > {q}")
        lines.append("\n**【填答區】**")
        lines.append("| 欄位 | 填寫值 |")
        lines.append("|---|---|")
        lines.append(f"| case_id | `{case_code}` |")
        lines.append("| guard_g_agree | 待填（選填: agree / disagree） |")
        lines.append(
            "| verdict | 待填（選填: correct / partially_correct / unsupported / missed） |"
        )
        lines.append("| reviewer | 待填 |")
        lines.append("| reviewed_at | 待填（實際審查時間，含時區） |")
        lines.append(
            "| notes | 待填（若同意 Guard G 擋得好可填: 確實缺乏支持證據；若不同意請說明理由） |"
        )
        lines.append("\n")
        p2_index += 1

    lines.append("---\n")

    # ==========================================
    # Part 3: Selected quarterly category review cards
    # ==========================================
    lines.append(f"## Part 3：{len(bindings['cards'])} 張季度大類審查卡（明確選定的審查範圍）\n")
    lines.append(
        "> 說明：每張卡依明確選定的 run / snapshot 與 dossier 產生。"
        "候選 Evidence IDs 僅供查閱，請真人核對原文並自行選填。"
        "空白工作表與自動產生的資料不算真人審查，也不代表 Final Pass。\n"
    )

    card_index = 1
    for quarter, dossier in dossiers.items():
        run_id = selections[quarter]["analysis_run_id"]
        snap_id = selections[quarter]["snapshot_id"]
        lines.append(f"### 【季度：{quarter}】（Run {run_id} / Snapshot {snap_id}）\n")
        features_list = dossier["features"]
        challenges_list = dossier["challenges"]

        # Build feature map for fast lookup
        f_by_name = {f["feature_name"]: f for f in features_list}

        # Build key_to_id for evidence lookup
        key_to_id = {e["evidence_key"]: e["id"] for e in dossier.get("evidence", [])}

        for cat in CATEGORIES:
            card_id = f"CARD-{card_index:02d}"
            card_filename = f"{quarter}-{cat}.md"

            rel_evidence_ids = set()

            if cat == "model_challenge":
                summary_texts = []
                for ch in challenges_list:
                    desc = ch.get("description", "")
                    kind = ch.get("kind", "")
                    var = ch.get("target_variable") or ch.get("metadata_json", {}).get(
                        "affected_model_variable", ""
                    )
                    summary_texts.append(f"[{kind}] 對變數 `{var}` 提出質疑: {desc}")
                    for eid in ch.get("evidence_ids", []):
                        rel_evidence_ids.add(eid)
                cat_summary = (
                    "；\n  ".join(summary_texts) if summary_texts else "該季度無模型挑戰項目"
                )
            else:
                target_names = CATEGORY_FEATURE_MAP.get(cat, [])
                summary_texts = []
                for tname in target_names:
                    if tname in f_by_name:
                        feat = f_by_name[tname]
                        val = feat["feature_value"]
                        net = feat.get("rationale") or feat.get("metadata_json", {}).get(
                            "net_assessment", ""
                        )
                        summary_texts.append(f"**`{tname}`** ({val}): {net}")
                        for k in feat.get("metadata_json", {}).get("evidence_keys", []):
                            if k in key_to_id:
                                rel_evidence_ids.add(key_to_id[k])
                cat_summary = (
                    "；\n  ".join(summary_texts)
                    if summary_texts
                    else "該大類於本季度無顯著有值特徵"
                )

            sorted_eids = sorted(list(rel_evidence_ids))[:15]

            lines.append(f"#### [{card_id}] {quarter} — {cat.upper()}（檔案: `{card_filename}`）")
            lines.append(f"- **類別範疇**：{cat}")
            lines.append(f"- **關聯 AI 解讀摘要**：{cat_summary}")
            lines.append(f"- **候選 Evidence IDs**：`{sorted_eids}`")
            lines.append("\n**【審查填答表】**")
            lines.append("| 欄位 | 填寫值 |")
            lines.append("|---|---|")
            lines.append(f"| card_id | `{card_id}` |")
            lines.append(f"| quarter | `{quarter}` |")
            lines.append(f"| category | `{cat}` |")
            lines.append(f"| analysis_run_id | `{run_id}` |")
            lines.append(f"| snapshot_id | `{snap_id}` |")
            lines.append(
                "| verdict | 待填（選填: correct / partially_correct / unsupported / missed） |"
            )
            lines.append("| reviewer | 待填 |")
            lines.append("| reviewed_at | 待填（實際審查時間，含時區） |")
            lines.append("| notes | 待填（至少 5 個字元的審核筆記） |")
            lines.append("| evidence_ids | 待填（自行核對後選擇整數列表） |")
            lines.append("\n")

            card_index += 1

    output_file.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing human work from regeneration.
    with binding_file.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(bindings, indent=2, ensure_ascii=False) + "\n")
    with output_file.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    print(f"Generated unfilled worksheet: {output_file}")
    print(f"Binding manifest: {binding_file}")
    print(f"Selected cards: {card_index - 1}; completed human reviews: 0")
    return binding_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dossiers-dir", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--focus-json", type=Path)
    parser.add_argument("--cases-dir", type=Path)
    args = parser.parse_args()
    try:
        generate_worksheet(
            dossiers_dir=args.dossiers_dir,
            selection_path=args.selection,
            output_file=args.output,
            focus_json=args.focus_json,
            cases_dir=args.cases_dir,
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Worksheet generation refused: {exc}\n")


if __name__ == "__main__":
    main()
