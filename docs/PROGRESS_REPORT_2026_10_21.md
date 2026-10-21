# StockOS 進度與分支整合報告

日期：2026-10-21（Australia/Brisbane）。範圍：`1121eason/StockOS` 遠端分支、整合後原始碼、版本內驗收文件，以及本次離線測試。

## 四層進度

| 層次 | 目標 | 狀態 |
|---|---|---|
| 第一層：看懂財務數字 | 收集財報、整理資料、做財務預測及估值 | 已完成 NVIDIA 的研究核心 |
| 第二層：理解公司經營狀況 | 用數據辨識營運階段，並讓 AI 分析產業與企業風險 | Regime 已完成；AI 待正式驗收 |
| 第三層：形成可靠的投資判斷 | 整合估值、成長、風險，建立並驗證投資決策 | 已有部分程式；正式驗收未完成 |
| 第四層：長期自動運作 | 自動更新、多公司分析、可持續使用的產品 | 尚未完成 |

「已完成」沿用既有里程碑的研究範圍；本次沒有重新執行歷史實驗或給予新的產品驗收。

## 狀態依據與缺口

| 層次 | 可核對的現有成果 | 尚未完成的驗收或產品能力 |
|---|---|---|
| 第一層 | M1.1 財報與 PIT 資料契約、M2 財務預測、DCF／Reverse DCF 與估值；已有 NVIDIA 研究與驗收紀錄 | 新 clone 不含正式資料庫、原始研究封包及全部歷史輸出；此次通過的合成測試不等於重新驗證實際財務結果 |
| 第二層 | M3／M3.1 Regime、信心與轉換契約；AI 證據准入、守衛、人工審核與實驗隔離工具 | 整合版本尚無新的完整正式 AI 驗收；舊 provider 配額、登入與試驗數字只屬歷史文件，不代表目前即時狀態 |
| 第三層 | `ValuationBridge`、`SignalFusion`、`WalkForwardBacktester` 與重建診斷；已有時序與輸入完整性檢查 | 原始 source／model／price vintage 未完成驗證，不能宣稱 historical out-of-sample；AI 候選升格契約與正式投資決策驗收未完成 |
| 第四層 | 本機繁中 UI、隔離研究匯入、唯讀查詢及 cadence 輸入契約 | cadence 只允許 dry-run；自動資料更新、正式排程、多公司真實流程及長期維運驗收未完成 |

主要文件：

- [M1.1 結案](MILESTONE_1_1_FINAL_CLOSURE_REPORT.md)、[M2 執行報告](MILESTONE_2_EXECUTION_REPORT.md)。
- [M3.1 執行報告](MILESTONE_3_1_EXECUTION_REPORT.md)、[Regime 輸出契約](REGIME_OUTPUT_CONTRACT.md)。
- [M4.1 歷史執行報告](MILESTONE_4_1_EXECUTION_REPORT.md)、[AI 方法與正式基線](AI_ANALYST_METHOD.md)。
- [回測時序與限制](BACKTEST_TEMPORAL_AUDIT.md)、[cadence 契約](CADENCE_CONTRACT.md)。
- [隔離研究流程](RESEARCH_WORKSPACE.md)、[內部政策來源契約](INTERNAL_POLICY_RECONSTRUCTION.md)。

## 分支整合

盤點時共 7 個遠端分支：`main` 與以下 6 個分支。原始 `main` 為 `a85acc9b5c66b3888b6aeb07cd80771b2dd598af`。本次使用獨立 clone 整合，保留各分支提交歷史，不刪除原有分支。

| 分支 | 盤點時提交 | 納入方式 |
|---|---|---|
| `agent/init-d459c678-ffe9-4988-a374-b1be58e35eea` | `0cc120211d1d9c80acdc0306902228cc87edfea6` | 先前 PR #1 已合併至原始 main |
| `codex/stockos-offline-source-20261015` | `0c9d858da7eb92e2387cb918bbbe5968ad2a1a54` | 已是最新 internal-policy 分支的祖先，一併納入 |
| `codex/stockos-ui-20261016` | `640f77c9e3cc5a850803dcc5d79b3f89c065a61b` | 已是最新 internal-policy 分支的祖先，一併納入 |
| `codex/stockos-real-flow-20261017` | `74bdf6011d8d1faf768fd7d43278ea9d238ce50d` | 已是最新 internal-policy 分支的祖先，一併納入 |
| `codex/stockos-internal-policy-20261018` | `0d71b713d64deccfbf1f77614dbea4bed8d63fe1` | 作為已整合 UI、來源驗證與實際研究流程的程式基底 |
| `sync/mac-source` | `c17cb8da0b54689b99bf6772e715887cf3d268d5` | 使用保留雙親的 merge 納入歷史；重疊／不相容內容採用較新、已有防回歸測試的基線 |

合併完成的判準是每個原有分支頭都能通過 `git merge-base --is-ancestor <branch-head> origin/main`，而非要求已合併的分支指標全部移到同一個提交。

### sync/mac-source 的處理

此分支有 7 處衝突，涉及 FSI 工單、4 個研究／審核腳本、AI 守衛與人工審核測試。另有 5 個無文字衝突、但會改變正式 AI 契約的檔案，亦逐一核對。

該匯出會把正式版本由 `AIAnalystPolicyV1 / PromptSetV1 / FeatureSchemaV1` 切換到實驗性 FSI 版本，並在 `service.py` 匯入此分支未提交的 `quarter_package.py`。此外，它會讓指定 Claude 的審核查詢回退至 Codex，並改變正式 snapshot 選取次序。較新分支的 `tests/unit/test_ai_formal_baseline.py` 明確防止上述基線變更。

因此以下 12 個檔案保留 internal-policy 分支版本。這項取捨保留新版 FSI lineage、候選隔離與人工審核防護；沒有將舊匯出的全部內容當作可升格的功能。舊內容仍可從 `c17cb8d` 與 merge 歷史取回：

- `docs/AI_ANALYST_METHOD.md`、`docs/FSI_S2_EXECUTION_WORKORDER.md`。
- `scripts/generate_review_worksheet.py`、`scripts/import_review_submissions.py`、`scripts/run_fsi_cohort_expansion.py`、`scripts/run_fsi_s2_experiment.py`。
- `src/valuation_engine/ai/contracts.py`、`guards.py`、`prompts.py`、`service.py`、`validation.py`。
- `tests/unit/test_human_review_tools.py`。

另外修整待合併程式既有的匯入、型別註記與格式問題，並將原有 `zip` 截斷行為明示為 `strict=False`。未更動正式 AI 模組、財務公式、策略門檻或配置係數。

## 本次驗證

| 檢查 | 結果 |
|---|---|
| 完整 Python 測試 | **1,309 passed、5 skipped、0 failed** |
| UI 互動測試 | **20 passed、0 failed、0 skipped** |
| Ruff 靜態檢查 | PASS |
| Ruff 格式檢查 | PASS，135 個檔案 |
| Mypy | PASS，80 個原始碼檔案 |
| UI JavaScript 語法檢查 | PASS |
| UI 打包 | PASS；含 API 的使用方式仍需本機 Python server |
| 差異空白／衝突檢查 | PASS |
| GitHub Actions | 此程式庫未提供 workflow；本次證據為本機整合測試，不宣稱遠端 CI 通過 |

5 項跳過原因：1 項需獨立 PostgreSQL，3 項需實際 NVIDIA archive bundle，1 項需完整回測 manifest／`qve.db`。以上均未當作通過。

首輪受執行沙箱限制，本機 HTTP socket 與模擬 transport 測試無法正常執行；取得所需執行權限後，使用相同離線資料與模擬 provider 完整重跑，得到上表最終結果。UI 測試亦使用所需的本機 loopback 權限重跑後全數通過。

機器可讀摘要與原始測試紀錄雜湊：[驗證收據](verification/2026-10-21-merge.json)。

本次沒有啟動真實模型、寫入正式資料庫、執行部署或移動原始本機工作目錄的未提交修改。原始目錄及其隔離 W1 工作成果不屬於本次遠端分支整合的額外匯入範圍。

## 下一階段完成條件

1. 在確定的程式／模型／資料版本上完成 AI 正式驗收，包含實際輸出、重複性、人工審核與候選升格依據。
2. 補齊決策與回測所需的歷史來源／模型／價格版本證據，再進行正式策略驗收。
3. 完成可持續的自動更新、排程、多公司真實流程及維運驗收。

本次分支整合與程式測試完成，不會使上述驗收自動通過。
