# 本季 AI 解釋驗收矩陣

日期：2026-11-05。適用 FY2027-Q2。矩陣不回寫或改判舊 W1／FSI-S2 歷史證據。

| ID | 要完成的能力 | 驗收標準 | 本輪狀態 | 證據／限制 |
|---|---|---|---|---|
| E01 | 研究版本綁定 | 公司、季度、checkpoint、information cutoff、Quant／來源內容及 request SHA 全部相符；報價變動不改研究 binding | 工程測試通過（本輪 117 項目標測試範圍） | `synthesis.research_binding`、`validate_candidate`；錯季不可 fallback |
| E02 | 完整本季輸入 | 已核對財務、前季對照、修訂、Regime、DCF 與合格官方文件原文；保留表格；來源／排除有清單；不截斷 | 工程測試通過；v2 本季包已離線準備 | `ai_request.build_request`；期間由來源 URL 標示，不代表語意驗收 |
| E03 | 來源與時間 | 明確 raw 目錄、拒絕 symlink、逐檔 SHA 核對，來源可用時間不得晚於 cutoff；缺資料停止 | 工程測試通過（本輪 117 項目標測試範圍） | 原件雜湊吻合不是獨立發布時間證明 |
| E04 | 可追溯 AI 觀點 | 四類為營運驅動、風險、不確定性、失效條件；觀點種類明列；每條有正確 paragraph_id 與逐字引文；引文不超過既定上限 | 機械核對測試通過 | 尚未取得本季實際模型輸出；不證明引文完整子句或推論正確 |
| E05 | 輸出隔離 | 額外 confidence/value/approval 等未核准欄位拒收；待審內容永不自動准入、不改估值 | 工程測試通過 | 目前始終 `decision_ready=false`、`promotion_ready=false` |
| E06 | AI 失敗不拖垮財務 | 無檔、錯 JSON、深層遞迴、錯來源／季度等，只阻 AI；Quant、保存快照及 pointer 不被更動 | 工程測試通過（含唯讀接線與失敗隔離） | [隔離與接線測試收據](../../../reports/ai-completion-20261105/agent-synthesis-validation.json)；合成測試不是產品正式驗收 |
| E07 | 白話綜合頁 | 財務／前季／修訂／Regime／DCF 與 AI 待審狀態一併呈現；零值、負值、缺值正確；所有內容安全轉義 | 36 項無監聽 UI 測試通過 | 36 項無監聽 UI 測試通過；沒有新產品服務或瀏覽器實機驗收聲明 |
| X01 | 可執行的本季模型工作單 | 凍結請求包、模型／後端識別、分段、總呼叫及重試上限、失敗中止與紀錄規則；符合既有批准邊界 | 離線分段 plan 已定；執行器綁定／診斷仍待 | 建議 20 extraction + 1 synthesis + 1 challenge = 22 research stages；另最多 7 fresh isolation diagnostics，共最多 29 次 StockOS-owned CLI 啟動；尚未授權或執行 |
| X02 | 本季實際分析 | 受控執行產生 FY2027-Q2 候選，輸入／輸出／請求／執行收據可重核 | 未執行 | 本輪模型呼叫 0；FY2023-Q2 舊輸出不適用 |
| X03 | 後端與隔離證據 | 記錄實際服務後端／模型 snapshot；工具與程序隔離範圍可核對 | 待驗收 | 原歷史執行的 backend snapshot 仍 UNVERIFIED；本輪不補造 |
| Q01 | 內容覆蓋與正確性 | 人工核對事實、展望、推論；本季／前季歸因正確；重要反證、缺項與失效條件明確 | 待驗收 | 精確引文與 schema 通過不能取代語意審查 |
| Q02 | 獨立品質評分 | 兩位獨立審查者綁定本次候選與 request；分歧依既定規則處理；未評維持未評 | 未完成，0/2 | 舊審查、採用意見、AI 代填草稿均不算新本季獨立審查 |
| A01 | 正式准入 | Q01／Q02 及適用正式契約全部通過，准入記錄綁定同一候選；不得以本 schema 取代 FSI-S2 | 不通過 | 現行程式沒有核准或自動 promotion 路徑 |
| A02 | 自動 AI 研究 | 財報更新後可排入有預算／重試上限的獨立 AI 工作，錯季／失敗不覆寫前版合格報告 | 尚未接通 | 本輪僅候選唯讀接線，沒有自動模型任務 |

本輪 [Python 收據](../../../reports/ai-completion-20261105/python-tests.xml)為 **117 passed、0 failed、0 skipped**；[無監聽 UI 收據](../../../reports/ai-completion-20261105/ui-focused.log)為 **36 passed、0 failed**；語法檢查與 UI build 通過。初次完整 UI 有 35 passed、5 個既有 fixture 因 `listen EPERM` 受阻，未取得原生重跑，不能宣稱整套 UI 通過。

任何工程 `PASS` 只適用其測試範圍，不改變 X／Q／A 狀態。

## 2026-11-06 AGY 本地執行附錄

上表保留 2026-11-05 的離線準備狀態。「尚未授權／本輪模型呼叫 0」是當時紀錄；其後已獲暫時收緊、驗證後執行及還原的授權，並已執行合成診斷。以下只更新本地 AGY 事實，不以工程測試、部分工具拒絕或 CLI terminal SUCCESS 改判 FSI-S2、Q01／Q02 或 A01。

| 對應項目 | 本地 AGY 最新狀態 | 證據與限制 |
|---|---|---|
| E01～E03／X01：版本與預算 | 凍結 FY2027-Q2 current_previous v2 包，request／binding 不變；診斷上限 7、研究 22 | [版本附錄](VERSION_MANIFEST.md)；六筆診斷全 FAILED，reserved 6/0、剩餘 1/22；第六敗未獲修補例外，剩餘額度不代表可再執行 |
| X01／X03：原生與暫時限制 | 指定原生檔案控制 v2～v6 PASS；strict init、v4～v6 官方確認 10 plugins 暫停 | [v6 native](../../../outputs/agy-explanation-strict-20261106-v6/native-controls.json)／[plugin control](../../../outputs/agy-explanation-strict-20261106-v6/plugin-configuration-control.json)；standalone MCP absence 不涵蓋 plugin MCP；backend snapshot UNVERIFIED |
| X03：真實工具拒絕 | v4 有精確 view_file pre deny／ERROR 配對；v5、v6 均有 3 次檔案讀取＋URL＋搜尋的 5 個拒絕 | [v4 協定診斷](../../../outputs/agy-explanation-strict-20261106-v4/protocol-diagnosis.json)／[v5 有限證據](../../../outputs/agy-explanation-strict-20261106-v5/observed-denials.json)／[v6 結果](../../../outputs/agy-explanation-strict-20261106-v6/attempt-0006/result.json)；run_command／write_to_file／invoke_subagent 未實測，有限證據不是研究 qualification |
| E04／E05／X02：輸出與本季研究 | v6 仍 PROVIDER_OR_SCHEMA_FAILURE；terminal SUCCESS／exit0，但 has_structured_output=false／NoneType；財報 0、研究 0/22 | [v6 摘要](../../../outputs/agy-explanation-strict-20261106-v6/summary.json)；原始 JSON 不 fallback，finish 可用性未證實，尚無本季候選 |
| X01：模式修補 | 官方 plan 模式會加 `/plan` 並偏向唯讀調查；v6 契約改 accept-edits，strict／deny 保留 | [官方模式說明](https://antigravity.google/docs/cli/modes/)／[v6 契約](../../../outputs/agy-explanation-strict-20261106-v6/contract.json)；缺結構化輸出的原因未獨立確定，改模式後仍失敗，不宣稱根因已排除 |
| E06：正式來源與還原 | 已完成各輪原設定 bytes／mode 還原、正式保護指紋前後相同；正式 DB 寫入 0 | [v6 還原](../../../outputs/agy-explanation-strict-20261106-v6/restoration.json)／[前](../../../outputs/agy-explanation-strict-20261106-v6/protection-before.json)／[後](../../../outputs/agy-explanation-strict-20261106-v6/protection-after.json)；commit／push／部署皆 0 |
| 工程驗證（v6） | 單次 615 passed，0 fail/error/skip；Ruff／mypy 通過 | [v6 合併收據](../../../reports/ai-completion-20261105/agy-final-preflight-v6-20261106.xml)；與上表 117 Python／36 UI 是不同階段，歷史重疊測試不相加、不作語意品質證據 |
| 同日後續回傳相容修補 | PASS 離線工程；原生 NOT RUN | 新增缺欄位時的嚴格完整 JSON 解碼與必要階段驗證；[667 項合併測試](../../../reports/ai-completion-20261105/agy-response-compat-tests-20261106.xml)／[修補收據](../../../outputs/agy-response-compat-20261106/receipt.json)。未啟動 AGY，六敗、工具權限缺口及研究 0/22 保留 |
| Q01／Q02／A01／A02 | 未通過／未完成 | 無本季候選、兩位獨立審查 0/2、品質 UNSCORED、promotion=false；未接自動模型排程，不更新正式綜合判斷 |

[AGY 詳細驗收矩陣](../AGY_EXPLANATION_2026-11-05/ACCEPTANCE_MATRIX.md)及[完整失敗／固定修補／還原歷史](../AGY_EXPLANATION_2026-11-05/README.md)保留工程、原生、部分工具、內容與正式准入的不同證據層次。v4／v5 的合成 generation 已明列，不宣稱整輪零推論；沒有財報傳送或本季研究完成證據。
