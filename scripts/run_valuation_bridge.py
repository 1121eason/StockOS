#!/usr/bin/env python3
"""Run ValuationBridgeV1 across the full 7-quarter historical panel."""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure ROOT/src is prioritized
if "PWD" in os.environ:
    os.getcwd = lambda: os.environ.get("PWD", "/Users/eason/Documents/Coding/StockOS")

ROOT = Path(os.environ.get("PWD", "/Users/eason/Documents/Coding/StockOS"))
sys.path.insert(0, str(ROOT / "src"))

from valuation_engine.valuation.bridge import ValuationBridgeV1

QVE_DB = ROOT / "data/qve.db"
COHORT_DB = ROOT / "data/m41/fsi/cohort/candidate.db"
OUTPUT_MANIFEST = ROOT / "data/m41/fsi/cohort/receipts/valuation_bridge_manifest.json"

PANEL_QUARTERS = {
    "FY2023-Q2": ("2022-08-25%", "遊戲庫存修正初期、Hopper 架構發表"),
    "FY2023-Q3": ("2022-11-17%", "庫存打銷谷底、RTX 40、美出口管制新規"),
    "FY2024-Q1": ("2023-05-25%", "生成式 AI 拐點爆發、指引跳增 53%"),
    "FY2024-Q2": ("2023-08-24%", "單季營收突破百億、CoWoS 先進封裝緊俏"),
    "FY2025-Q4": ("2025-02-27%", "Blackwell 量產出貨、全球主權 AI 擴張"),
    "FY2026-Q1": ("2025-05-29%", "Blackwell Ultra / Rubin 藍圖、特規審查"),
    "FY2027-Q2": ("2026-08-27%", "次世代成熟期、全週期模型驗證"),
}


def run_bridge():
    bridge = ValuationBridgeV1()
    results = {}

    with sqlite3.connect(QVE_DB) as qve_conn, sqlite3.connect(COHORT_DB) as cohort_conn:
        qve_c = qve_conn.cursor()
        cohort_c = cohort_conn.cursor()

        print("=========================================================================================")
        print(" StockOS Valuation Bridge V1 — 7-Quarter Historical Panel Evaluation")
        print("=========================================================================================")

        for quarter, (date_pattern, theme) in PANEL_QUARTERS.items():
            # 1. Fetch Quant Valuation
            qve_row = qve_c.execute(
                "SELECT dcf_base, metadata_json FROM research_valuations WHERE as_of_timestamp LIKE ? ORDER BY id DESC LIMIT 1",
                (date_pattern,),
            ).fetchone()

            if not qve_row:
                raise ValueError(f"Missing quant valuation for {quarter} ({date_pattern})")

            meta = json.loads(qve_row[1]) if qve_row[1] else {}
            market_price = float(meta.get("price", 0.0))
            quant_dcf_base = float(qve_row[0]) if qve_row[0] else 0.0
            as_of_date = date_pattern.replace("%", "")

            # 2. Fetch Cohort Features
            feat_rows = cohort_c.execute(
                "SELECT feature_name, feature_value, confidence FROM cohort_features WHERE quarter = ?",
                (quarter,),
            ).fetchall()
            features = {r[0]: (float(r[1]), float(r[2])) for r in feat_rows}

            # 3. Fetch Cohort Challenges
            chal_rows = cohort_c.execute(
                "SELECT kind, target_variable, direction, description FROM cohort_challenges WHERE quarter = ?",
                (quarter,),
            ).fetchall()
            challenges = [
                {"kind": r[0], "target_variable": r[1], "direction": r[2], "description": r[3]}
                for r in chal_rows
            ]

            # 4. Evaluate Bridge
            res = bridge.evaluate(
                quarter=quarter,
                as_of_date=as_of_date,
                market_price=market_price,
                quant_dcf_base=quant_dcf_base,
                features=features,
                challenges=challenges,
            )

            res_dict = res.to_dict()
            res_dict["theme"] = theme
            results[quarter] = res_dict

            print(f"[{quarter}] Price: ${res.market_price:<7.2f} | Quant DCF: ${res.quant_dcf_base:<7.2f} | AI Score: {res.ai_composite_score:+.2f} | Haircut: {res.tail_risk_haircut:.2f} | AI Fair Value: ${res.ai_fair_value_base:<7.2f} | Gap: {res.expectations_gap:+.1%} -> {res.valuation_stance}")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "ValuationBridgeV1",
        "panel_total": len(PANEL_QUARTERS),
        "panel_quarters": results,
    }

    OUTPUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("\n=========================================================================================")
    print(f"✓ Valuation Bridge manifest successfully saved to: {OUTPUT_MANIFEST}")
    print("=========================================================================================")
    return manifest


if __name__ == "__main__":
    run_bridge()
