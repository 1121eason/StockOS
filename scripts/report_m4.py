"""M4 delivery report: infrastructure evidence must not masquerade as live AI or human review."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/m4/report"


def main():
    coverage = json.loads((OUT / "coverage.json").read_text())
    pg = json.loads((ROOT / "data/m4/postgresql/validation.json").read_text())
    preservation = json.loads((OUT / "preservation.json").read_text())
    test = (ROOT / "data/m4/test-results.txt").read_text().strip().splitlines()[-1]
    assert pg["test_exit_code"] == 0 and "passed" in test and "failed" not in test
    assert preservation["regime_26_states_and_ids_unchanged"]
    completed = sum(r["analysis_status"] == "completed" for r in coverage)
    # This closure records the current credential-blocked run. Never mark fixture output as live.
    assert completed == 0, (
        "Update this report to evaluate actual outputs and reviews before live acceptance"
    )
    criteria = [
        (
            "PARTIAL",
            "PIT retrieval/SEC bounds/future isolation tested; live historical responses and training-data leakage review not yet evaluated",
        ),
        (
            "PASS",
            "Whitelisted contexts and SQL guard exclude stock prices, valuations and future outcome tables",
        ),
        (
            "PASS",
            "FeatureSchemaV1 / PromptSetV1 / AIAnalystPolicyV1; strict bounded/polarity schema",
        ),
        (
            "PASS",
            "Exact source/block/span/hash admission; normalized feature/evidence joins; synthetic tests",
        ),
        (
            "PARTIAL",
            "Unbacked quotes/IDs/numeric prose rejected; live semantic entailment and hallucination rate unavailable",
        ),
        (
            "PARTIAL",
            "Guidance semantic feature contract and extraction path implemented; no actual provider result",
        ),
        (
            "PARTIAL",
            "Official transcript PDF management-turn parser tested; historical corrected-transcript upload time unresolved; no real AI call findings",
        ),
        (
            "PARTIAL",
            "Existing Quant anomaly codes only; evidence-backed explanation path implemented; real investigations pending",
        ),
        (
            "PARTIAL",
            "Advisory challenge pipeline and synthetic proposal tested; real seven-quarter challenges pending",
        ),
        (
            "PASS",
            "Only proposed rows, numeric ranges NULL, no forecast update path; immutable Quant preservation verified",
        ),
        (
            "PASS",
            "Full confirmed/candidate/status envelope supplied; advisory regime challenge cannot mutate Regime",
        ),
        (
            "PASS",
            "Exact prompts, settings, model/version, schemas, raw responses and hashes; model changes append",
        ),
        (
            "PASS",
            "AIProvider interface, OpenAI structured adapter, exact-hash RecordedProvider; no provider lock-in",
        ),
        (
            "PARTIAL",
            "Five quarters × seven categories = 35 review items prepared; zero completed human verdicts",
        ),
        (
            "PARTIAL",
            "Injection quarantine and malformed/unsupported output tests pass; actual LLM adversarial/semantic evaluation pending",
        ),
        (
            "PASS",
            f"SQLite {test}; actual PostgreSQL {pg['test_summary']}; original rows/26 Regime IDs and states preserved",
        ),
        ("PASS", "No trading, allocation or Opportunity Score implementation"),
        ("PASS", "No future-return ingestion/evaluation/optimization in AI pipeline"),
    ]
    ac = {
        f"M4-AC{i}": {"status": status, "evidence": reason}
        for i, (status, reason) in enumerate(criteria, 1)
    }
    (OUT / "acceptance.json").write_text(json.dumps(ac, indent=2) + "\n")
    summary = {
        "status": "implementation_ready_pending_live_provider_and_human_review",
        "prepared_quarters": len(coverage),
        "live_ai_snapshots": completed,
        "official_filing_coverage": sum(
            r["source_coverage"]["filing_status"] == "available" for r in coverage
        ),
        "official_call_coverage": sum(
            r["source_coverage"]["official_call_status"] == "available" for r in coverage
        ),
        "unique_source_documents": len(
            {s["source_document_id"] for r in coverage for s in r["sources"]}
        ),
        "human_review_items": 35,
        "completed_human_reviews": 0,
        "final_pass_recommended": False,
        "sqlite_tests": test,
        "postgresql_tests": pg["test_summary"],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = [
        "# Milestone 4 Execution Report",
        "",
        "**M4 核心實作與測試完成；尚未完成正式 AI 歷史重播與人工驗證，不建議 Final Pass。**",
        "",
        "M1、M1.1、M2、M3、M3.1 已依本次 PM 指示記錄為通過。未設定實際 AI provider/model/key；未用測試 fixture、規則式摘要或本對話回答冒充正式模型執行。",
        "",
        "## 1. Implementation Completed",
        "",
        "新增 11 張 append-only AI 表、28 個固定方向的 feature taxonomy、來源與 quote admission、兩段式 evidence/synthesis、challenge/proposal、Pydantic schemas、bounded retry、provider abstraction、CLI、read-only combined view、5 季人工審閱模板。Migration `0008_ai_analyst`；Quant schema/係數/計算未改。",
        "",
        "## 2. AI Architecture",
        "",
        "Official PIT documents → evidence extraction → exact-span validation → feature synthesis → wrapper confidence / contradiction check → advisory challenges → completed snapshot。`quant/ai_context.py` 提供 immutable Quant 與完整 Regime envelope；`ai/` 不讀 valuation、prices、returns。Combined research view 在 AI 之外才加入既有 valuation。",
        "",
        "## 3. Source Coverage",
        "",
        f"26/26 有 eligible releases 和 SEC filings，共 {summary['unique_source_documents']} 份 distinct source documents。最多兩份 release、兩份 filing、一份官方 transcript/Q&A/presentation，active lookback 200 天；逐季 source IDs、hashes、時間與 scope 在 coverage.json。",
        "",
        "目前 historical transcript 0/26 可入選。已找到 [FY2027 Q2 官方 transcript](https://investor.nvidia.com/files/content_files/TRANSCRIPT_-NVIDIA-Corp-NVDA-US-Q2-2027-Earnings-Call-26-August-2026-5_00-PM-ET.pdf)，但標為 Corrected Transcript，修正版上傳時間未知；沒有把 call date 當成歷史公開證據。原始 SEC HTML 若缺獨立 publication evidence，採 filing date 翌日午夜 ET 的保守界限，並清楚保留 published_at unknown。",
        "",
        "| Representative quarter | Narrative blocks | Eligible source count | AI status |",
        "|---|---|---|---|",
    ]
    for r in coverage[:7]:
        lines.append(
            f"| {r['quarter']} | {r['source_coverage']['narrative_blocks']} | {len(r['sources'])} | not executed |"
        )
    lines += [
        "",
        "## 4. Feature Taxonomy",
        "",
        "28 個 features 覆蓋 demand、visibility、pricing、supply、product、adoption/concentration、inference/training、competition/custom ASIC/insourcing、ecosystem/switching、margin/working capital/financing/revenue/inventory、China/export/regulation、management/guidance/credibility、structural/moat/durability。方向統一 +1 favorable，−1 adverse；supply_constraint 正值是供應限制緩解。無 evidence 為 missing/NULL，不能冒充 neutral 0。",
        "",
        "## 5. Historical AI Feature Results",
        "",
        "正式 live AI snapshots：**0/26**。7 個代表季度與全部 26 季 context 均已備妥；沒有填入任何虛構 feature values。配置 provider 後先執行七季，審查後才擴至全歷史。",
        "",
        "## 6. Evidence Coverage",
        "",
        "來源 coverage 已有；AI evidence/feature semantic coverage 目前 unavailable。模型輸出須指向本次 context 的 exact block/span，最多 55 words；時間、section/page 與 hash 由 wrapper 指派。反向 evidence 即使被 synthesis 漏列，wrapper 仍加入 contradicting_evidence 並降低 confidence。",
        "",
        "## 7. Earnings Call Findings",
        "",
        "目前沒有可報告的正式 AI earnings-call findings。已實作 PDF 管理層發言過濾、頁面指標與基本測試；未知 speaker、修訂公開時間及不存在的 transcript 保留為缺失。官方 transcript 的發現不是歷史 PIT 可用性的證明。",
        "",
        "## 8. Anomaly Investigations",
        "",
        "流程可對既有 CASH_FLOW_DIVERGENCE、CYCLICAL_PRESSURE、MARGIN_COMPRESSION 產生 evidence-linked explanation；未知 anomaly code 被拒絕，既有 flags 不變。目前尚無真實 NVIDIA AI 調查結論。",
        "",
        "## 9. Model Challenges",
        "",
        "已實作 upside/downside、regime、anomaly、adjustment schemas。提案只寫 proposed、evidence IDs、direction、variable/horizon，numeric suggested ranges 為 NULL。合成測試證明可建立 proposal 且不改 Quant；正式季度 challenge 待模型執行。",
        "",
        "## 10. Human Review Results",
        "",
        "5 季 × 7 類，共 **35 個待審閱項目**，在 human-review-set.json；實際完成 **0**。verdict/reviewer/notes 均未代填。correct / partially_correct / unsupported / missed 是待真人提交的分類，fixture tests 不算 human review。",
        "",
        "## 11. Hallucination / Unsupported Claim Results",
        "",
        "機械性 guards 測試通過：不存在的 span/block、無 evidence feature、numeric prose、方向衝突、格式錯誤皆 fail safely。實際模型 hallucination rate **unavailable**，不宣稱為零。引用存在不保證結論合理；語意 entailment、遺漏與跨次一致性仍待實際輸出和人工審閱。",
        "",
        "## 12. PIT / Leakage Tests",
        "",
        "測試覆盖 later documents/SEC filing bounds、price/outcome SQL isolation、source injection quarantine、完整 Regime envelope、無來源拒絕、provider failure、append-only、model versioning。26 季 Quant Regime state 與 snapshot IDs 與已接受 M3.1 完全一致；原有資料列與 delivery archives 均保留。",
        "",
        "## 13. Provider / Prompt Versioning",
        "",
        "AIAnalystPolicyV1 / PromptSetV1 / FeatureSchemaV1。Provider interface 有 analyze_document、extract_evidence、synthesize_features、generate_challenge。OpenAI adapter 使用 strict Responses schema；model/version 必須由本機設定並匹配實際 response model。RecordedProvider 使用 exact prompt hash，支援後續離線重播；原始 prompts/settings/raw response/hash 與各次失敗均保存。",
        "",
        "## 14. Test Results",
        "",
        f"- SQLite: **{test}**",
        f"- PostgreSQL: **{pg['test_summary']}**",
        f"- PostgreSQL server: {pg['server_version']}",
        f"- Core head: {pg['migration']}; labels unchanged.",
        "- Ruff 與 mypy 結果另附；測試為工程行為驗證，不是 live AI 的內容品質評估。",
        "",
        "## 15. Known Limitations",
        "",
        "- 沒有 provider/model/key，未進行真實模型 API 呼叫，無正式 AI feature/evidence snapshots。",
        "- Human review 未完成；不能以自動 checks 代替真人評分。",
        "- Historical corrected transcript 的上傳時間未確認；官方 call findings coverage 仍為零。",
        "- 200-day bounded corpus 非完整多年脈絡；未識別 speaker 與未建檔 source issue 可能導致遺漏。",
        "- Quote/numeric/injection guards 是機械防線，不能證明全部語意正確或全面 prompt-injection immunity。",
        "- 現代模型 training weights 可能含歷史 cutoff 後知識；PIT 檢索與 prompt 無法抹除它，仍需查核輸出是否引用未提供的後來事實。",
        "",
        "## 16. M4-AC1–M4-AC18",
        "",
        "| AC | Status | Evidence |",
        "|---|---|---|",
    ]
    lines += [f"| {k} | {v['status']} | {v['evidence']} |" for k, v in ac.items()]
    lines += [
        "",
        "## 17. PM Decisions Required",
        "",
        "1. 指定 provider 與 pinned model/version，並在本機環境或 .env 設定 API key；不要把 key 貼到對話。這是實際七季 AI 重播的必要輸入。",
        "2. 實際分析產出後，由指定真人完成五季 review set。未要求 PM 接受缺失 transcript 或放寬 PIT 規則。",
        "",
        "## 18. Recommendation",
        "",
        "**不建議 M4 Final Pass。** 工程流程可進入 provider 接線與代表季度驗證；必須取得真實模型輸出、評估來源與語意品質、完成至少五季人工審閱後，再決定是否擴至 26 季與 Final Pass。",
        "",
        "本次工作停留在 M4；未開始 Backtest、Opportunity Score、Buy/Hold/Sell 或新 milestone。",
    ]
    (ROOT / "docs/MILESTONE_4_EXECUTION_REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
