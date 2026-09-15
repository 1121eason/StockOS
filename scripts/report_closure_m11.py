"""Render the closure evidence into the PM's eleven requested sections."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "data/m11-closure/report"


def read(name):
    return json.loads((out / f"{name}.json").read_text())


s, quarters, gates, recon = (
    read(name) for name in ("summary", "quarterly-coverage", "pm-gates", "reconciliation")
)
live = s["live_sec"]
reviews = read("quality-review")
impact_path = out / "reconciliation-impact.json"
impact = json.loads(impact_path.read_text()) if impact_path.exists() else {}
runs = live.get("runs", [])
second = runs[1] if len(runs) == 2 else None
idem = bool(
    second
    and all(second[k] == 0 for k in ("filings_created", "facts_created", "documents_created"))
    and not second["errors"]
)
pg_path = root / "data/m11-closure/postgresql/validation.json"
pg = json.loads(pg_path.read_text()) if pg_path.exists() else {}
sqlite_path = root / "data/m11-closure/test-results.txt"
sqlite_test = sqlite_path.read_text().strip().splitlines()[-1] if sqlite_path.exists() else "未執行"
tests_pass = (
    "failed" not in sqlite_test and "passed" in sqlite_test and pg.get("test_exit_code") == 0
)
sec_ok = (
    s["sec_coverage"]["quarters_with_primary_filing"] == 26
    and len(runs) == 2
    and all(not r["errors"] for r in runs)
)
actual = s["sec_coverage"]["financial_facts"] > 0
all_gates = len(gates) == 3 and all(g["status"] == "PASS" for g in gates)
criteria = {
    "FC1": (
        "PASS" if sec_ok else "PARTIAL" if actual else "FAIL",
        "真實 SEC 匯入與目標季度主要文件覆蓋",
    ),
    "FC2": ("PASS" if idem else "FAIL", "第二次真實 SEC 匯入新增重複記錄為零"),
    "FC3": (
        "PASS" if actual and recon["status_counts"] else "FAIL",
        "真實 SEC/IR 對帳已執行並報告差異",
    ),
    "FC4": ("PASS" if s["share_observations"] else "FAIL", "具來源的真實股數觀測"),
    "FC5": ("PASS" if tests_pass else "PARTIAL", "available_at 邊界、晚公布股數與來源衝突測試"),
    "FC6": ("PASS" if tests_pass else "PARTIAL", "2021/2024 拆股換算與市值不變測試"),
    "FC7": (
        "PASS" if all(g["market_cap"] is not None for g in gates) and len(gates) == 3 else "FAIL",
        "代表季度的 PIT 市值",
    ),
    "FC8": ("PASS" if len(quarters) == 26 else "FAIL", "26 季估值覆蓋重新產生"),
    "FC9": ("PASS" if all_gates else "FAIL", "三個真實 PM Gate 無前視資訊洩漏"),
    "FC10": ("PASS" if tests_pass else "PARTIAL", "SQLite 與 PostgreSQL 完整測試"),
    "FC11": ("PASS" if s["counts"]["ai_features"] == 0 else "FAIL", "未引入 AI 生成財務事實"),
    "FC12": ("PASS", "未開始 Milestone 2"),
}
final_pass = (
    all(status == "PASS" for status, _ in criteria.values())
    and not any(r["blocking"] for r in reviews)
    and impact.get("none_selected") is True
    and s["all_source_hashes_verified"]
)
lines = [
    "# Milestone 1.1 Final Closure Report",
    "",
    f"**{'Final Pass candidate' if final_pass else 'PARTIAL — 尚不能建議 Final Pass'}**",
    "",
    "架構沿用已接受版本。本次只新增 PIT 股數觀測、接上市值／EV／FCF Yield、補齊 SEC 精確計數與收尾驗收。",
    "分鐘級公告邊界、明確標示的 research_reconstructed 行情已依 PM 決定接受；獨立付費行情與華爾街年度共識預測均不構成本里程碑阻塞。未新增 forward valuation、DCF、AI 或評分。",
    "",
    "## 1. Live SEC Results",
    "",
    f"執行狀態：`{live['status']}`。SEC filings **{s['sec_coverage']['filings']}**、facts **{s['sec_coverage']['financial_facts']}**、來源文件 **{s['sec_coverage']['source_documents']}**。目標季度有主要 10-Q/10-K 的覆蓋為 **{s['sec_coverage']['quarters_with_primary_filing']}/26**。",
    "",
]
if not runs:
    lines += [
        f"真實網路匯入未執行。原因：{live.get('reason', '尚無真實執行紀錄')}。以下『未執行』不代表執行後計數為零，也不以合成測試替代實際成果。",
        "",
    ]
if live.get("error"):
    lines += [f"實際下載錯誤：`{live.get('error_type', 'Error')}` — {live['error']}", ""]
for attempt in runs:
    if attempt.get("errors"):
        lines += [
            f"第 {attempt['run']} 次主要文件下載失敗：{len(attempt['errors'])} 份；逐筆錯誤見 live-sec.json。",
            "",
        ]
lines += [
    "來源與接收時間沿用 SEC submissions；保留 accession、公司事實原始 JSON、原始 10-Q/10-K、SHA-256 與 taxonomy。接收時間加三分鐘是明示的可用時間代理，並未改稱精確公開時間。",
    "技術依據：[SEC 官方 API 文件](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)。",
    "",
    "## 2. SEC Idempotency Results",
    "",
    "| 項目 | 第一次 | 第二次 |",
    "|---|---:|---:|",
]
for field in (
    "filings_created",
    "filings_skipped",
    "facts_created",
    "facts_skipped",
    "documents_created",
    "documents_skipped",
):
    values = [str(runs[i][field]) if i < len(runs) else "未執行" for i in (0, 1)]
    lines.append(f"| {field} | {values[0]} | {values[1]} |")
lines += [
    "",
    "Synthetic HTTP contract tests 驗證計數與唯一性；只有 `live-sec.json` 的兩次真實執行可用於 FC1/FC2。原始來源版本若真的變動，會保留新版本並如實顯示新增數量。",
    "",
    "## 3. SEC/IR Reconciliation Results",
    "",
    f"matched pairs：{recon['matched_pairs']}；conflicts：{recon['conflicts']}；unit mismatches：{recon['unit_mismatches']}；basis mismatches/unknown：{recon['basis_mismatches_or_unknown']}；無可比較 SEC 配對的 IR 觀測：{recon['unavailable_comparisons']}。",
    "",
    "| Metric | 配對結果 | 無配對 IR 觀測 |",
    "|---|---|---:|",
]
for metric, data in recon["metrics"].items():
    lines.append(
        f"| {metric} | {json.dumps(data['status_counts'])} | {len(data['unavailable_ir_fact_ids'])} |"
    )
lines += [
    "",
    f"Restatement candidates：{recon['restatement_candidate_pairs']}。已確認會計重編數量：未判定；後來不同數值可能來自拆股或呈現差異，不能直接宣稱會計重編。",
    "",
    "兩側來源不覆寫。Canonical PIT 維持先排除截止時間之後的資料，再採 earliest eligible originally_reported；同時點依 concept priority，仍衝突則 unavailable。",
    f"未解配對影響檢查：{impact.get('unresolved_pair_count', '待驗證')} 組；其 SEC 候選被 26 季財務 snapshot 或估值輸入採用：{len(impact.get('affected_candidates', [])) if impact else '待驗證'} 組。逐筆候選 ID 與檢查範圍見 `reconciliation-impact.json`。未被採用不代表差異已解決，也不批准未知基準資料供其他用途使用。",
    "",
    "## 4. Share Count Coverage",
    "",
    f"真實股數觀測 **{s['share_observations']}**；26 個估值日可用股數 **{s['coverage']['shares']}/26**。",
    "",
    "`share_count_observations` 是 append-only，保存日期、公開／可用時間、原始與正規化股數、split basis、來源雜湊、概念、confidence。`normalized_share_count` 是原始基準下的絕對股數；查詢時才換到估值日或指定 comparable basis，避免將可變的『目前基準』寫回舊觀測。",
    "",
    "先篩選 available_at ≤ T，再依最新股數所屬日期、同日期的 SEC cover → SEC structured → official disclosure 優先順序、同來源優先級的已知修訂選取。新公布的舊比較數不會倒退覆蓋更新的觀測；同優先級同時點衝突回傳 unavailable。缺新季度股數時可以使用先前已公布的合格觀測，並保留 age_days；完全不使用 diluted weighted-average shares 補市值。",
    "",
    "SEC 封面解析僅接受明確 DEI 股數、匹配的公司識別、instant 日期與 shares 單位。未映射的維度／share class、未知轉換或比較期基準會列入待核實，不猜值。",
    "",
    "| Quarter | 估值日 | 股數觀測 ID | 合格股數（估值日基準） | 股數所屬日期 | 股數 available_at | 市值 | EV | FCF Yield | Trailing P/E |",
    "|---|---|---:|---:|---|---|---:|---:|---:|---:|",
]
for q in quarters:
    shares = q["shares"] or {}
    values = [
        q["quarter"],
        str(q["valuation_at"]),
        shares.get("observation_id"),
        shares.get("share_count"),
        shares.get("shares_as_of_date"),
        shares.get("available_at"),
        q["market_cap"],
        q["enterprise_value"],
        q["fcf_yield"],
        q["trailing_pe"],
    ]
    lines.append("| " + " | ".join("—" if v is None else str(v) for v in values) + " |")
lines += [
    "",
    "## 5. Market Cap Coverage",
    "",
    f"**{s['coverage']['market_cap']}/26**。公式為 eligible price(T) × latest known eligible shares(T)。估值 snapshot 保存價格時間、價格基準、股數日期、股數基準、兩側來源與 `ratios-1.1-closure` 計算版本。",
    "",
    "## 6. EV / FCF Yield Coverage",
    "",
    f"EV **{s['coverage']['enterprise_value']}/26**；FCF Yield **{s['coverage']['fcf_yield']}/26**。",
    "",
    "EV = Market Cap + Debt − Cash。可沿用先前已知完整餘額，明示其期間、available_at 與 carried_forward；缺債務不設零。每筆保存 ev_completeness 與 ev_missing_components。FCF Yield = 四個可用季度的 engine FCF / Market Cap；engine-fcf-1.0 採 OCF − reported CapEx，保留與 issuer FCF 的定義差異。資料不足時留空，不強求條件性 EV／FCF Yield 全滿。",
    "",
    "## 7. Three PM Gate Results",
    "",
    "| Quarter | 結果 | 未通過檢查 |",
    "|---|---|---|",
]
for gate in gates:
    lines.append(
        f"| {gate['quarter']} | {gate['status']} | {', '.join(k for k, v in gate['checks'].items() if not v) or '無'} |"
    )
lines += [
    "",
    "完整 gate JSON 保留：issuer 邊界前／後、SEC acceptance proxy 邊界、財務 snapshot、可用 guidance、股數、首個許可價格、TTM EPS、各估值比率與完整 provenance。無實際 SEC 記錄時，SEC-only 階段明確失敗，不使用空集合的檢查結果宣稱成功。",
    "",
    "## 8. Test Results",
    "",
    f"- SQLite：{sqlite_test}",
    f"- PostgreSQL：{pg.get('test_summary', '尚未完成本轮驗證')}",
    f"- PostgreSQL core migration：{pg.get('migration', '待驗證')}；兩次 cached workflow 計數一致：{pg.get('counts_idempotent', '待驗證')}。",
    f"- 來源雜湊：{s['source_documents_verified']} 份全部通過：{s['all_source_hashes_verified']}。",
    "",
    "新增測試涵蓋股數可用邊界、晚公布資料、同日來源優先與衝突、拒用加權平均股數、不可修改限制、封面 iXBRL scale/unit/class、封面匯入冪等、兩次拆股換算、市值不變、EV 缺債務與 prior known cash provenance、FCF Yield 與估值冪等。測試資料明確標為 synthetic，未寫入研究資料庫。",
    "",
    "## 9. Remaining Blocking Data Issues",
    "",
]
lines += [
    f"最新 {len(reviews)} 項審查中，{sum(r['blocking'] for r in reviews)} 項標為阻塞；其餘為已解決、已接受或條件性缺值。原始記錄不刪除。",
    "",
]
excluded = sum(
    r["resolution"] == "unresolved_but_excluded_from_reviewed_snapshots" for r in reviews
)
if excluded:
    lines += [
        f"其中 {excluded} 項 source-disagreement 保留未解；逐筆檢查其不同候選均未被本次 26 季財務 snapshot 與估值輸入採用，因此僅對本驗收範圍列為非阻塞。原始 issue 與 reconciliation blocking 標記仍保留，未作全域解除。",
        "",
    ]
if not any(r["blocking"] for r in reviews):
    lines += ["本次 26 季快照範圍沒有剩餘阻塞項目。條件性缺值與未採用來源差異仍如下揭露。", ""]
if not sec_ok:
    lines.append(
        "- 真實 SEC 匯入、目標文件覆蓋與兩次實跑證據尚未齊備；具體執行狀態與錯誤見第 1 節及 live-sec.json。"
    )
if s["coverage"]["shares"] < 26:
    lines.append(
        f"- PIT 股數仍有 {26 - s['coverage']['shares']} 個估值日缺口；須取得可驗證的真實來源，才能填入市值與相依估值。"
    )
lines += [
    "- Raw paid vendor、Wall Street consensus 與分鐘級公告時間均非阻塞，不再要求 PM 重新決定。",
    "- 條件性 EV 缺項會明示，不以零補值；前面三季缺完整 TTM 保留 unavailable。",
    "",
    "## 10. FC1–FC12 PASS / PARTIAL / FAIL",
    "",
    "| FC | 結果 | 說明 |",
    "|---|---|---|",
]
lines += [f"| {fc} | {status} | {reason} |" for fc, (status, reason) in criteria.items()]
lines += [
    "",
    "## 11. Recommendation",
    "",
    "可提交 PM 審核 Final Pass。"
    if final_pass
    else "**目前不建議 Final Pass。** 不可用測試成功替代真實 SEC／股數與三季度 Gate 證據。須依以上未通過項目完成實際匯入、對帳、26 季覆蓋及 PM Gate 再驗證。",
    "",
    "Milestone 2 保持未開始。",
    "",
    "可重現指令：`uv run python scripts/close_m11.py --live-sec`（需要有效身份；只在欲實際下載時使用）；`uv run python scripts/close_m11.py` 只重播本地收尾資料；`uv run python scripts/validate_closure_postgres.py` 驗證 PostgreSQL；`uv run python scripts/report_closure_m11.py` 更新本報告。",
    "",
]
(root / "docs/MILESTONE_1_1_FINAL_CLOSURE_REPORT.md").write_text("\n".join(lines))
(out / "acceptance.json").write_text(
    json.dumps(
        {"criteria": criteria, "final_pass_recommended": final_pass}, indent=2, ensure_ascii=False
    )
    + "\n"
)
print("Closure report written; Final Pass recommended:", final_pass)
