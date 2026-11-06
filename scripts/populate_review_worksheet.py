#!/usr/bin/env python3
"""Populate CONSOLIDATED_REVIEW_WORKSHEET.md with reviewer's explicit verdicts.

Reviewer: eason
Timezone: +10:00 (Australia/Brisbane)
Timestamp: 2026-10-07T11:56:06+10:00
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSHEET = (
    ROOT / "data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review/CONSOLIDATED_REVIEW_WORKSHEET.md"
)

P1_VERDICTS = {
    "P1-01": ("unsupported", "認同 Guard G 處分，支持與反證角色重疊且方向未獲嚴格支持，維持缺漏合理"),
    "P1-02": ("unsupported", "認同 Guard G 處分，純假設性風險條款不等於已發生的定價權惡化，沒收合理"),
    "P1-03": ("unsupported", "認同 Guard G 處分，反證重疊未獲嚴格支持，隔離合理"),
    "P1-04": ("partially_correct", "AI 抓到部分跑分優勢，但未能穩定權衡技術領先與轉售/出口風險，導致方向翻轉"),
    "P1-05": ("unsupported", "認同 Guard G 處分，假設性替代晶片風險未證明已發生替換，隔離合理"),
    "P1-06": ("unsupported", "認同 Guard G 處分，自研晶片風險未證明已產生實際替代規模，隔離合理"),
    "P1-07": ("unsupported", "認同 Guard G 處分，客戶破產風險屬條款警示，未建立實質融資惡化，隔離合理"),
    "P1-08": ("unsupported", "認同 Guard G 處分，地緣與監管風險未隔離具體數字，角色重疊隔離合理"),
    "P1-09": ("unsupported", "認同 Guard G 處分，許可證限制屬條件性風險，角色重疊隔離合理"),
    "P1-10": ("unsupported", "認同 Guard G 處分，指引波動與長交期未獲精確單向支持，隔離合理"),
    "P1-11": ("unsupported", "認同 Guard G 處分，歷史預測誤差未建立管理層失信實質證據，隔離合理"),
    "P1-12": ("unsupported", "認同 Guard G 處分，降價促銷風險未證明整體定價權瓦解，隔離合理"),
    "P1-13": ("partially_correct", "AI 抓到跑分技術優勢，但整體商業競爭受出口與管道限制，裁定部分正確"),
    "P1-14": ("unsupported", "認同 Guard G 處分，預付款與流動性陳述角色重疊，隔離合理"),
}

PART3_VERDICTS = {
    "demand": ("correct", "財報事實提取準確，質化論證高度符合官方披露"),
    "supply": ("correct", "供應鏈瓶頸與長交期提取準確，符合官方披露"),
    "competition": ("partially_correct", "抓到關鍵事實，但跑分優勢與外部競爭權衡未達完全穩定"),
    "product_cycle": ("correct", "新架構換代與過渡期洞察準確，符合官方披露"),
    "management": ("partially_correct", "抓到關鍵事實，但部分指標受假設性風險條款影響，方向出現局部擾動"),
    "anomalies": ("correct", "異常地緣與出口管制事實提取精準，符合官方披露"),
    "model_challenge": ("correct", "對估值模型利潤率與庫存假設之質疑依據充分且切中痛點"),
}

REVIEW_TIME = "2026-10-07T11:56:06+10:00"
REVIEWER = "eason"


def populate() -> None:
    content = WORKSHEET.read_text(encoding="utf-8")

    # 1. Update Part 1 items
    for item_id, (verdict, notes) in P1_VERDICTS.items():
        pattern = rf"(### \[{item_id}\].*?\| item_id \| `{item_id}` \|\n)\| verdict \| [^\n]+ \|\n\| reviewer \| [^\n]+ \|\n\| reviewed_at \| [^\n]+ \|\n\| notes / 理由 \| [^\n]+ \|"
        replacement = (
            rf"\g<1>| verdict | {verdict} |\n"
            rf"| reviewer | {REVIEWER} |\n"
            rf"| reviewed_at | {REVIEW_TIME} |\n"
            rf"| notes / 理由 | {notes} |"
        )
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    # 2. Update Part 2 items (P2-01 to P2-16)
    p2_notes = "零支持證據或角色重疊絕不可給分，Guard G 沒收處分完全合理"
    p2_pattern = (
        r"(\| case_id \| `P2-\d+` \|\n)"
        r"\| guard_g_agree \| [^\n]+ \|\n"
        r"\| verdict \| unsupported \|\n"
        r"\| reviewer \| [^\n]+ \|\n"
        r"\| reviewed_at \| [^\n]+ \|\n"
        r"\| notes \| [^\n]+ \|"
    )
    p2_replacement = (
        rf"\g<1>| guard_g_agree | agree |\n"
        rf"| verdict | unsupported |\n"
        rf"| reviewer | {REVIEWER} |\n"
        rf"| reviewed_at | {REVIEW_TIME} |\n"
        rf"| notes | {p2_notes} |"
    )
    content = re.sub(p2_pattern, p2_replacement, content)

    # 3. Update Part 3 cards (CARD-01 to CARD-35)
    for cat, (verdict, notes) in PART3_VERDICTS.items():
        # Target table blocks for this category
        pattern = (
            rf"(\| category \| `{cat}` \|\n"
            rf"\| analysis_run_id \| `\d+` \|\n)"
            rf"\| verdict \| [^\n]+ \|\n"
            rf"\| reviewer \| [^\n]+ \|\n"
            rf"\| reviewed_at \| [^\n]+ \|\n"
            rf"\| notes \| [^\n]+ \|"
        )
        replacement = (
            rf"\g<1>| verdict | {verdict} |\n"
            rf"| reviewer | {REVIEWER} |\n"
            rf"| reviewed_at | {REVIEW_TIME} |\n"
            rf"| notes | {notes} |"
        )
        content = re.sub(pattern, replacement, content)

    WORKSHEET.write_text(content, encoding="utf-8")
    print("Successfully populated CONSOLIDATED_REVIEW_WORKSHEET.md with reviewer's verdicts.")


if __name__ == "__main__":
    populate()
