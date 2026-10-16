#!/usr/bin/env python3
"""Generate a consolidated human review worksheet for M4.1 qualitative evaluation.

This script aggregates:
1. Part 1: 14 priority changed / flipped features from Q2/Q3 repeat runs.
2. Part 2: 16 original empty-support features re-evaluated under Guard G.
3. Part 3: 35 quarterly category review cards with associated dossier features and evidence IDs.

Output:
data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review/CONSOLIDATED_REVIEW_WORKSHEET.md
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUMAN_REVIEW_DIR = (
    ROOT / "data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review"
)
FOCUS_JSON = (
    ROOT
    / "data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/repeat-review-focus.json"
)
CASES_DIR = ROOT / "data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/final/cases"
OUTPUT_FILE = HUMAN_REVIEW_DIR / "CONSOLIDATED_REVIEW_WORKSHEET.md"

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


def load_focus_data() -> tuple[dict, dict[int, dict]]:
    with open(FOCUS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    evidence_map = {e["id"]: e for e in data.get("evidence", [])}
    return data, evidence_map


def load_cases_data() -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("feature-*.md")):
        text = path.read_text(encoding="utf-8")
        title_match = re.search(r"#\s+(feature-\d+)\s+—\s+([a-z_]+)", text)
        feature_id = title_match.group(1) if title_match else path.stem
        feature_name = title_match.group(2) if title_match else ""

        run_snap_match = re.search(r"Run / snapshot：(\d+)\s+/\s+(\d+)", text)
        run_id = int(run_snap_match.group(1)) if run_snap_match else 0
        snap_id = int(run_snap_match.group(2)) if run_snap_match else 0

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


def load_dossiers() -> dict[str, dict]:
    dossiers = {}
    dossiers_dir = HUMAN_REVIEW_DIR / "dossiers"
    for path in sorted(dossiers_dir.glob("*.json")):
        quarter = path.stem
        with open(path, encoding="utf-8") as f:
            dossiers[quarter] = json.load(f)
    return dossiers


def generate_worksheet() -> None:
    focus_data, evidence_map = load_focus_data()
    cases_data = load_cases_data()
    dossiers = load_dossiers()

    now_iso = datetime.now(UTC).astimezone().isoformat()

    lines: list[str] = []
    lines.append("# StockOS M4.1 真人審查集中工作表 (Consolidated Review Worksheet)\n")
    lines.append(f"- 產生時間：`{now_iso}`")
    lines.append("- 預設審查者（Reviewer）：`eason`")
    lines.append("- 預設時區：`+10:00` (Australia/Brisbane)")
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
    # Part 1: 14 Priority Changes
    # ==========================================
    lines.append("## Part 1：14 個核心翻轉與狀態變化特徵（重跑差異優先裁定）\n")
    lines.append(
        "> 說明：在同條件重跑中，這 14 個指標出現了**正負翻轉**或**有值變為缺漏**。"
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
        lines.append(f"| reviewed_at | {now_iso} |")
        lines.append("| notes / 理由 | 待填（簡要寫明對該指標變動的判讀理由） |")
        lines.append(f"| evidence_ids | {it['evidence_ids']} |")
        lines.append("\n")

    lines.append("---\n")

    # ==========================================
    # Part 2: 16 Empty Support Cases
    # ==========================================
    lines.append("## Part 2：16 個原空支持案例（Guard G 沒收合理性確認）\n")
    lines.append(
        "> 說明：在舊版分析中，這 16 個特徵被給予非零評分，但支持證據為空或角色重疊。"
        "新守衛 Guard G 將它們全數沒收（改判 rejected）。請確認 Guard G 的處分是否合理。\n"
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
        lines.append("| verdict | unsupported |")
        lines.append("| reviewer | 待填 |")
        lines.append(f"| reviewed_at | {now_iso} |")
        lines.append(
            "| notes | 待填（若同意 Guard G 擋得好可填: 確實缺乏支持證據；若不同意請說明理由） |"
        )
        lines.append("\n")
        p2_index += 1

    lines.append("---\n")

    # ==========================================
    # Part 3: 35 Quarterly Category Review Cards
    # ==========================================
    lines.append("## Part 3：35 張季度大類審查卡（M4.1 結案正式計數）\n")
    lines.append(
        "> 說明：此處為正式推進 M4.1 Final Pass 所需的 35 張審查卡（前 5 季 × 7 大類）。"
        "我們已自動將每張卡關聯到對應季度的財報特徵、AI 主張精要與候選 Evidence IDs。"
        "您填妥後將自動匯入系統打破 0/35 卡點。\n"
    )

    run_map = {
        "FY2023-Q2": (15, 4),
        "FY2023-Q3": (17, 5),
        "FY2024-Q1": (18, 6),
        "FY2024-Q2": (20, 7),
        "FY2025-Q4": (21, 8),
    }
    categories = (
        "demand",
        "supply",
        "competition",
        "product_cycle",
        "management",
        "anomalies",
        "model_challenge",
    )

    card_index = 1
    for quarter, (run_id, snap_id) in run_map.items():
        lines.append(f"### 【季度：{quarter}】（Run {run_id} / Snapshot {snap_id}）\n")
        dossier = dossiers.get(quarter, {})
        features_list = dossier.get("features", [])
        challenges_list = dossier.get("challenges", [])

        # Build feature map for fast lookup
        f_by_name = {f["feature_name"]: f for f in features_list}

        # Build key_to_id for evidence lookup
        key_to_id = {e["evidence_key"]: e["id"] for e in dossier.get("evidence", [])}

        for cat in categories:
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
                        val = feat.get("feature_value", 0.0)
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
            if not sorted_eids and dossier.get("evidence"):
                # Fallback to first evidence id for that run
                sorted_eids = [dossier["evidence"][0]["id"]]

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
            lines.append(
                "| verdict | 待填（選填: correct / partially_correct / unsupported / missed） |"
            )
            lines.append("| reviewer | 待填 |")
            lines.append(f"| reviewed_at | {now_iso} |")
            lines.append("| notes | 待填（至少 5 個字元的審核筆記） |")
            lines.append(f"| evidence_ids | {sorted_eids} |")
            lines.append("\n")

            card_index += 1

    HUMAN_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Successfully generated worksheet: {OUTPUT_FILE}")
    print(f"Total Part 1 items: {len(p1_items)}")
    print(f"Total Part 2 items: {len(cases_data)}")
    print(f"Total Part 3 cards: {card_index - 1}")


if __name__ == "__main__":
    generate_worksheet()
