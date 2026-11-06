#!/usr/bin/env python3
"""
StockOS 26-Quarter Historical Cohort Expansion Generator.
Scales fundamental valuation and expectations gap analysis from the 7 pilot quarters
to all 26 historical quarters (FY2021-Q1 through FY2027-Q2, 2020-05-22 to 2026-08-27).
Outputs valuation_bridge_manifest_26q.json.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from valuation_engine.valuation.bridge import ValuationBridgeV2

QVE_DB = ROOT / "data/qve.db"
COHORT_DB = ROOT / "data/m41/fsi/cohort/candidate.db"
OUTPUT_MANIFEST_26Q = ROOT / "data/m41/fsi/cohort/receipts/valuation_bridge_manifest_26q.json"

PANEL_26_QUARTERS = [
    ("FY2021-Q1", "2020-05-22", "Ampere 架構發表、疫情初期雲端需求急增"),
    ("FY2021-Q2", "2020-08-20", "資料中心首度超越遊戲、Mellanox 併購完成"),
    ("FY2021-Q3", "2020-11-19", "RTX 30 系列上市、加密貨幣挖礦熱潮復甦"),
    ("FY2021-Q4", "2021-02-25", "全年營收創歷史高、CMP 專用挖礦晶片推出"),
    ("FY2022-Q1", "2021-05-27", "Grace CPU 藍圖發表、單季營收達 56.6 億"),
    ("FY2022-Q2", "2021-08-19", "普通股 1:4 分割生效、遊戲/數據中心雙引擎"),
    ("FY2022-Q3", "2021-11-18", "Omniverse 平台擴張、Metaverse 敘事高峰"),
    ("FY2022-Q4", "2022-02-17", "Arm 併購終止費用打銷、軟體授權營收萌芽"),
    ("FY2023-Q1", "2022-05-26", "PC 遊戲需求放緩、俄烏戰爭與通膨降溫"),
    ("FY2023-Q2", "2022-08-25", "遊戲庫存修正初期、Hopper 架構發表 (Pilot 1)"),
    ("FY2023-Q3", "2022-11-17", "庫存打銷谷底、RTX 40、美出口管制新規 (Pilot 2)"),
    ("FY2023-Q4", "2023-02-23", "ChatGPT 觸發生成式 AI 拐點、DGX Cloud 發表"),
    ("FY2024-Q1", "2023-05-25", "生成式 AI 拐點爆發、指引跳增 53% (Pilot 3)"),
    ("FY2024-Q2", "2023-08-24", "單季營收突破百億、CoWoS 先進封裝緊俏 (Pilot 4)"),
    ("FY2024-Q3", "2023-11-22", "特規中國晶片 H20 研發、AI 晶片供不應求"),
    ("FY2024-Q4", "2024-02-22", "全年淨利飆增 581%、主權 AI 國家級投資啟動"),
    ("FY2025-Q1", "2024-05-23", "宣佈 1:10 拆股、Blackwell 晶片全面投產"),
    ("FY2025-Q2", "2024-08-29", "1:10 拆股生效、Blackwell 設計掩模修改"),
    ("FY2025-Q3", "2024-11-21", "單季營收逾 350 億、雲端巨頭資本支出持續擴張"),
    ("FY2025-Q4", "2025-02-27", "Blackwell 量產出貨、全球主權 AI 擴張 (Pilot 5)"),
    ("FY2026-Q1", "2025-05-29", "Blackwell Ultra / Rubin 藍圖、特規審查 (Pilot 6)"),
    ("FY2026-Q2", "2025-08-28", "企業級 AI 代理（Agentic AI）全面普及"),
    ("FY2026-Q3", "2025-11-20", "次世代推理運算佔比突破 60%"),
    ("FY2026-Q4", "2026-02-26", "實體 AI（Physical AI）與機器人晶片放量"),
    ("FY2027-Q1", "2026-05-21", "Rubin 架構試產、超大規模集群交付"),
    ("FY2027-Q2", "2026-08-27", "次世代成熟期、全週期模型驗證 (Pilot 7)"),
]


def expand_26_quarters():
    print("=========================================================================================")
    print(" StockOS P1: 26-Quarter Historical Cohort Expansion (FY2021-Q1 ~ FY2027-Q2)")
    print("=========================================================================================")

    bridge = ValuationBridgeV2()
    results = {}

    uri_qve = f"file:{QVE_DB.resolve()}?mode=ro"
    uri_cohort = f"file:{COHORT_DB.resolve()}?mode=ro" if COHORT_DB.exists() else None

    with sqlite3.connect(uri_qve, uri=True) as qve_conn:
        qve_c = qve_conn.cursor()
        cohort_c = None
        if uri_cohort:
            cohort_conn = sqlite3.connect(uri_cohort, uri=True)
            cohort_c = cohort_conn.cursor()

        for idx, (quarter, as_of_date, theme) in enumerate(PANEL_26_QUARTERS):
            # 1. Fetch Quant Valuation
            row = qve_c.execute(
                "SELECT dcf_base, metadata_json FROM research_valuations WHERE as_of_timestamp LIKE ? ORDER BY id DESC LIMIT 1",
                (f"{as_of_date}%",),
            ).fetchone()

            meta = json.loads(row[1]) if row and row[1] else {}
            market_price = float(meta.get("price", 0.0))
            raw_dcf = row[0] if row else None

            # For the first two quarters where trailing DCF was None, use ratio-anchored forward baseline
            if raw_dcf is not None:
                quant_dcf_base = float(raw_dcf)
            else:
                # Proportional estimate from FY21-Q3 ($200.27 at price $528.51)
                quant_dcf_base = round(200.27 * (market_price / 528.51), 2)

            rdcf = meta.get("reverse_dcf", {})
            market_implied_growth = float(rdcf["implied_growth"]) if rdcf and "implied_growth" in rdcf else None

            # 2. Fetch Cohort Features if available
            features = {}
            challenges = []
            if cohort_c:
                feat_rows = cohort_c.execute(
                    "SELECT feature_name, feature_value, confidence FROM cohort_features WHERE quarter = ?",
                    (quarter,),
                ).fetchall()
                features = {r[0]: (float(r[1]), float(r[2])) for r in feat_rows}

                chal_rows = cohort_c.execute(
                    "SELECT kind, target_variable, direction, description FROM cohort_challenges WHERE quarter = ?",
                    (quarter,),
                ).fetchall()
                challenges = [
                    {"kind": r[0], "target_variable": r[1], "direction": r[2], "description": r[3]}
                    for r in chal_rows
                ]

            # 3. Evaluate Bridge under Dual-Track Contract
            res = bridge.evaluate(
                quarter=quarter,
                as_of_date=as_of_date,
                market_price=market_price,
                quant_dcf_base=quant_dcf_base,
                features=features,
                challenges=challenges,
                market_implied_growth_rate=market_implied_growth,
            )

            res_dict = res.to_dict()
            res_dict["theme"] = theme
            res_dict["has_cohort_features"] = bool(features)
            results[quarter] = res_dict

            feat_tag = f"({len(features)} feats)" if features else "(Quant Base)"
            print(
                f"[{idx+1:02d}/26] [{quarter}] Date: {as_of_date} | "
                f"Price: ${res.market_price:<7.2f} | Quant DCF: ${res.quant_dcf_base:<7.2f} | "
                f"AI Fair Value: ${res.ai_fair_value_base:<7.2f} | "
                f"Gap: {res.expectations_gap:+.1%} -> {res.valuation_stance:<15} {feat_tag}"
            )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "ValuationBridgeV2_26Q",
        "panel_total": len(PANEL_26_QUARTERS),
        "panel_quarters": results,
    }

    OUTPUT_MANIFEST_26Q.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MANIFEST_26Q, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("\n=========================================================================================")
    print(f"✓ 26-Quarter Valuation Bridge Manifest saved to: {OUTPUT_MANIFEST_26Q}")
    print("=========================================================================================")
    return manifest


if __name__ == "__main__":
    expand_26_quarters()
