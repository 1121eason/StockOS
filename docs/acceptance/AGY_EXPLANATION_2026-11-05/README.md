# AGY 本季候選接線與實際檢查

建立：2026-11-05。更新：2026-11-06。適用 NVDA FY2027-Q2；截至 strict-v6 保存收據。

使用者已明確授權：「好，幫我暫時收緊 AGY 權限，確認限制生效後再跑本季 AI 分析，完成後還原原設定；不要寫正式資料庫、commit、push 或部署。」

**目前停止，尚未送出財報或開始本季研究。原生檔案控制與部分 AGY 工具拒絕已有實證，但完整負向工具覆蓋及結構化輸出仍未通過。attempt-0001～0006 全部保留 FAILED；已完成各輪的暫時設定均已還原。**

同日後續：回傳格式的**離線相容修補已完成**，667 項相關測試通過；未啟動 AGY 重驗，權限門檻及六敗狀態不變。以下 strict-v6 收據仍描述修補前實際執行，不能重判為 PASS。

## 實際執行歷史

| 階段／reservation | 實際結果 | 研究與保護狀態／收據 |
|---|---|---|
| 初次連線／attempt-0001 | init 指定 agent／模型，但 always-proceed 且列出 60 工具；立即中止 | FAILED；財報 0、研究 0，未改原設定。[診斷](../../../outputs/agy-explanation-20261105/diagnostic-0001.json)／[資格收據](../../../outputs/agy-explanation-20261105/qualification.json) |
| strict-v1／未 reserve | 原生讀取對照未建立；runner 工作目錄設定有誤，在 AGY 前停止 | 不占診斷 reservation；settings／hooks 原 bytes、mode 已還原。[摘要](../../../outputs/agy-explanation-strict-20261106/summary.json)／[原生控制 FAIL](../../../outputs/agy-explanation-strict-20261106/native-controls.json)／[還原](../../../outputs/agy-explanation-strict-20261106/restoration.json) |
| strict-v2／attempt-0002 | 原生控制 PASS、strict init；executor 不接受 custom component `call_mcp_tool`，啟動失敗 | FAILED；owned DB 僅 USER_INPUT＋ERROR_MESSAGE，gen／executor metadata 0；不據此宣稱後端零派送。[摘要](../../../outputs/agy-explanation-strict-20261106-v2/summary.json)／[結果](../../../outputs/agy-explanation-strict-20261106-v2/attempt-0002/result.json)／[還原](../../../outputs/agy-explanation-strict-20261106-v2/restoration.json) |
| strict-v3／attempt-0003 | SessionStart hook 已載入；Data Agent Kit 設定提示映為 unknown step；尚無 PreInvocation 或工具事件即停止 | FAILED；owned DB type 90 為 EPHEMERAL_MESSAGE，gen／executor metadata 0。不是第二次 component registry 錯誤。[摘要](../../../outputs/agy-explanation-strict-20261106-v3/summary.json)／[診斷](../../../outputs/agy-explanation-strict-20261106-v3/startup-diagnosis.json)／[還原](../../../outputs/agy-explanation-strict-20261106-v3/restoration.json) |
| strict-v4／attempt-0004 | 10 個 plugins 暫時停用；可信 Session＋PreInvocation 0 後，`view_file` pre 被拒；CLI ERROR state 被舊 parser 拒收 | FAILED；一筆合成資料 generation、executor metadata 0。owned 診斷將同一工具、step、args SHA 與完整 pre-hook 拒絕訊息配對；沒有 PostToolUse。[摘要](../../../outputs/agy-explanation-strict-20261106-v4/summary.json)／[協定診斷](../../../outputs/agy-explanation-strict-20261106-v4/protocol-diagnosis.json)／[還原](../../../outputs/agy-explanation-strict-20261106-v4/restoration.json) |
| strict-v5／attempt-0005 | 已觀察 3 次檔案讀取、URL 讀取、搜尋的可信 pre deny＋ERROR 空輸出；terminal SUCCESS，但沒有准入的 structured object | FAILED；owned DB 有 5 筆合成 generation、1 executor。命令／寫入／子代理未實測，原始 JSON 文字不作格式通過。[摘要](../../../outputs/agy-explanation-strict-20261106-v5/summary.json)／[模式診斷](../../../outputs/agy-explanation-strict-20261106-v5/plan-mode-diagnosis.json)／[有限範圍拒絕收據](../../../outputs/agy-explanation-strict-20261106-v5/observed-denials.json)／[還原](../../../outputs/agy-explanation-strict-20261106-v5/restoration.json) |
| strict-v6／attempt-0006 | 執行契約改為 accept-edits，strict／deny 保留；仍只有 3×`view_file`、URL、搜尋的 5 個拒絕，缺命令／寫入／子代理；terminal SUCCESS、exit 0，但 structured_output 缺席 | FAILED，`PROVIDER_OR_SCHEMA_FAILURE`；財報 0、研究 0，原程序群已消失。settings／hooks／plugins 全部還原。[契約](../../../outputs/agy-explanation-strict-20261106-v6/contract.json)／[摘要](../../../outputs/agy-explanation-strict-20261106-v6/summary.json)／[結果](../../../outputs/agy-explanation-strict-20261106-v6/attempt-0006/result.json)／[還原](../../../outputs/agy-explanation-strict-20261106-v6/restoration.json) |

各輪 FAIL 原件保留，後續修補不改判前次失敗。v4 的 ERROR 協定修補只接受可信 pre 與精確完整 CLI 拒絕訊息；`error.type` 僅供形狀檢查，不能猜作權限 enum。v5 的有限拒絕收據明列 `NOT_QUALIFICATION`，未被沿用為後續完整研究准入。

## 已證明的範圍與剩餘缺口

| 證據層 | 已核對 | 尚未通過／限制 |
|---|---|---|
| 工程 | strict-v6 合併離線測試 615 passed，Ruff／mypy 通過；後續相容修補 667 項見下節 | 合成測試不能取代原生控制、真實工具邊界或內容品質 |
| 原生檔案控制 | strict-v2～v6 的正控制可讀／寫，受限控制拒絕 outside canary、合成 repo HEAD、合成 SQLite 讀取與合成 marker 寫入 | 僅支持指定操作；父程序 example.com HTTP 200 只是正向可用性對照 |
| AGY 權限及部分工具 | init 回報 strict、指定 agent／gemini-4-argon-high；v4 有精確拒絕對照，v5／v6 有 5 個被拒嘗試 | 完整 6 類負向工具覆蓋尚缺 `run_command`、`write_to_file`、`invoke_subagent`；v6 不補造未觀察行為 |
| Plugins／MCP | v4～v6 官方 inventory 確認 10 個 installed plugins 暫時 disabled；standalone MCP list 為 absent | standalone MCP absence 不涵蓋 plugin 提供的 MCP；原先 10 個 enabled plugins 的存在另有收據。未宣稱已執行 MCP 並拒絕 |
| 模式與格式 | 官方文件說明 plan 加入 `/plan` 並以唯讀調查為主；v6 契約採 accept-edits，仍維持 strict／deny | 缺 structured object 的原因未獨立確定；改模式後仍失敗。`finish` 可實際使用及正確結構化完成仍 UNVERIFIED；不從原始 JSON fallback |
| 還原與正式來源 | strict-v1～v6 的 protection-before／after 相等，settings／hooks 原 bytes／mode 已還原；v4～v6 plugins 原 bytes／mode 亦還原 | 合成 SQLite 控制另列，不是正式 DB 寫入；還原成功不代表研究門檻通過 |
| 本季內容／正式准入 | 財報傳送 0、研究完成 0/22、獨立審查 0/2、品質 UNSCORED、promotion=false | 無本季候選、AI 綜合估值、正式投資判斷或自動 AI 排程證據；不改判舊 W1／FSI-S2 |

官方模式依據：[Choose an execution mode](https://antigravity.google/docs/cli/modes/)。明確權限規則與 strict 在各執行模式皆優先；模式切換本身不是放寬 deny，也不保證工具或輸出契約可用。[權限](https://antigravity.google/docs/permissions?tab=cli)與[hooks](https://antigravity.google/docs/hooks/)的能力宣告仍需本機實測。

最終另行核對的[獨立收據](../../../outputs/agy-explanation-strict-20261106-v6/final-audit.json)確認：正式 qve.db 與三份全域設定的 SHA／mode 均符合操作前原件；官方 plugin list 重新列出原本 10 個 enabled plugins；Git HEAD 仍為原基線；保留六敗且研究 reservations 為 0。此核對沒有啟動模型。

## 繼續前必須完成的修補

1. 原生重驗本節下方的回傳相容修補。v6 terminal 列出 `response`、`json_schema` 等欄位，未提供文件定義的 `structured_output`；離線修補不代表 AGY 原生輸出已通過，不能將 terminal SUCCESS 當成內容准入。
2. 明確確認診斷 agent 的實際 backend components。省略 tools 後，即使改為 accept-edits，仍沒有命令、寫檔或子代理嘗試；應取得可用 component 與有效子代理目標的證據，不能從廣告 registry 或模型說法推定可用。
3. 另立綁定這六筆失敗的受控續跑方案，再驗證完整工具拒絕及零外部嘗試的注入／格式測試。現有失敗仍停止後續 reserve；不刪改失敗或自動提高上限。全部門檻通過後，才可開始固定的 22 個研究 stages。

## 2026-11-06 回傳格式離線相容修補

先前「接頭找錯欄位」的說法不夠精確。[官方 headless 文件](https://antigravity.google/docs/cli/headless/)確實定義 `structured_output`；本機 v6 卻只回傳 `response`、`json_schema` 等欄位。此次補的是這個實際差異的相容處理，沒有把供應商 schema 保證視為已驗證。

`decode_result` 現在優先使用原生物件；只有 `structured_output` **完全缺席**時，才允許解析 `response` 的整段 JSON 字串。兩條路徑皆要求回傳的 schema 與本次請求完全一致。若原生欄位存在卻為 null／錯誤型別，不會退回文字路徑；雙份答案矛盾、重複鍵、非有限數字、Markdown 包裝、前後雜文及非物件皆拒收。

解碼只產生待驗證物件，不是通用 JSON Schema validator。既有 extraction／synthesis／challenge 或合成測試的必要階段驗證仍在 `request()` 中執行，通過後才寫 admitted 檔及 COMPLETED；錯誤內容及冒充人工准入的輸出仍拒收。工具邊界、來源引文、固定預算與人類審查要求均未放寬。沒有安裝新依賴。

[新合併測試收據](../../../reports/ai-completion-20261105/agy-response-compat-tests-20261106.xml)：**667 passed、0 failed、0 errors、0 skipped**，其中新相容性回歸 52 項。包括真實 challenge validator 對假核准、錯誤布林值與額外欄位的拒收，以及在拒收時不寫 admitted／不標 COMPLETED。Ruff、格式、mypy 通過；這些都是離線證據。

[本輪保護前快照](../../../outputs/agy-response-compat-20261106/protection-before.json)及[離線修補收據](../../../outputs/agy-response-compat-20261106/receipt.json)分列來源版本、測試與保護核對。此輪 AGY／模型啟動 0、全域設定變更 0、正式 DB 寫入 0、commit／push／部署 0。既有六敗及原生診斷缺口保留，沒有沿用舊失敗回覆作新的通過結果；尚未重跑本季分析。

## 不可重設的額度與保留原件

總上限始終為診斷 7、研究 22；outer retries 0。strict-v1 沒有 AGY reserve。截至 v6，六筆 diagnostic reservations 全為 FAILED，計 **6/7；研究 0/22**。帳面剩餘 **1/22**，但 attempt-0006 未獲任何固定修補例外，故失敗停止規則仍阻擋下一次 reserve；有剩餘額度不等於可重試。

| FAILED attempt | Reservation SHA-256 | Outcome SHA-256 |
|---|---|---|
| 0001 | `0ecf42bd9599d037f697dbedd7008f9da32923e7bf6676d2bf720346c9df1cec` | `ada63f13698124e8bf8930c2751d58ad2ad5bacd07e17c1ca8ccbd92f2a9d6d7` |
| 0002 | `fa926dccc8f0716464e46fdcc8a28c8d5b6ceffca043e501b83b3a12394c7636` | `47e7854ee7df58c00342cfdee5d40a13aa1fa57ce50ee3039513f371ccb44f17` |
| 0003 | `b070d9b3e8b18d314486c66717e2960d3d842c7f528a44e92635d1fd7ea5da79` | `a9f652e546f3a2e4901b5224995889d64bbd62f00ba78938989397c2a7b25aad` |
| 0004 | `4b734a5ba8330be1eda6d8692f26eea10709ecc613d451a184bfeee1e547d41f` | `5d32e549dde53fe5a36bbc413f4a1088acd41041c3a73545bfeed7eaf3d5b11b` |
| 0005 | `c5228552fb02ce3faa68405db2f0563c36236d05f6c013edf6c056680f228f00` | `81b5b1a6126db41ba2a137e621c87db2bbf266143ee3fffa07e26c60ce3b5244` |
| 0006 | `4f1e7aecad53c2278aa0701ba37658ae28b5b887cec21a2a2687a48e093dd5b1` | `13d4d7986f35ec1d91c029a3a94eeec7f3463968d0ebf59f706f011a8fef2ac6` |

原 ledger 位於 `/Users/eason/Documents/Coding/StockOS/data/ai-provider-state/agy-explanation-20261105/`。五份獨立 immutable amendments 分別綁 attempt-0001～0005 的 reservation／outcome／result，以及適用的 owned diagnosis／snapshot、前份 amendment、完整使用者授權、本季 request／research binding 與新 policy。失敗不退款、不刪除、不改成 COMPLETED，沒有提高 7／22 上限。

對應工作單：[首次 recovery](../../../outputs/agy-explanation-strict-20261106-v2/recovery-approval.json)、[executor startup repair](../../../outputs/agy-explanation-strict-20261106-v3/startup-repair-approval.json)、[plugin startup repair](../../../outputs/agy-explanation-strict-20261106-v4/plugin-startup-repair-approval.json)、[denial protocol repair](../../../outputs/agy-explanation-strict-20261106-v5/denial-protocol-repair-approval.json)、[plan-mode repair](../../../outputs/agy-explanation-strict-20261106-v6/plan-mode-repair-approval.json)。這些是固定的配置／協定例外，不是內容品質重試或一般錯誤復原權限。

## 工程收據與歷史連結

[strict-v6 合併收據](../../../reports/ai-completion-20261105/agy-final-preflight-v6-20261106.xml)為當次單次 **615 passed、0 failed、0 errors、0 skipped**：額度／恢復 354、設定／hooks／plugins 65、guarded transport 158、分析 stages 38。它只支持這些離線工程範圍。

歷史工程收據保留，但範圍重疊，不與 615 重複加總：[v3 core 217](../../../reports/ai-completion-20261105/agy-preflight-20261106-v3-core.xml)、[早期 guard／hook](../../../reports/ai-completion-20261105/agy-guarded-tests.xml)、[初次接頭 51](../../../reports/ai-completion-20261105/agy-offline-tests.xml)、[初次設定 32](../../../reports/ai-completion-20261105/agy-policy-tests.xml)、[較早合併工程](../../../reports/ai-completion-20261105/agy-combined-tests.xml)。

原生控制及還原來源：[v2 native](../../../outputs/agy-explanation-strict-20261106-v2/native-controls.json)、[v6 native](../../../outputs/agy-explanation-strict-20261106-v6/native-controls.json)、[v6 plugin control](../../../outputs/agy-explanation-strict-20261106-v6/plugin-configuration-control.json)、[v3 原 plugin inventory](../../../outputs/agy-explanation-strict-20261106-v3/plugin-inventory-after-restoration.json)。正式來源指紋：[v1 前](../../../outputs/agy-explanation-strict-20261106/protection-before.json)／[後](../../../outputs/agy-explanation-strict-20261106/protection-after.json)、[v2 前](../../../outputs/agy-explanation-strict-20261106-v2/protection-before.json)／[後](../../../outputs/agy-explanation-strict-20261106-v2/protection-after.json)、[v6 前](../../../outputs/agy-explanation-strict-20261106-v6/protection-before.json)／[後](../../../outputs/agy-explanation-strict-20261106-v6/protection-after.json)。

executor 舊診斷：[原件](../../../outputs/agy-explanation-strict-20261106-v2/startup-diagnosis.json)與[含來源／sidecar／一致快照指紋的版本](../../../outputs/agy-explanation-strict-20261106-v2/startup-diagnosis-v2.json)均保留；不依賴 live provider DB 後續 housekeeping 維持舊快照內容。[初版修補提案](../../../outputs/agy-explanation-20261105/hardening-proposal/README.md)仍保留其當時「尚未套用」狀態，實際暫時套用／還原以各輪收據為準。

設定交易使用原 bytes／mode 備份、固定 owner lock 與可觀察並行變更保護；一般檔案比較／rename 不是不可分割 CAS，遇衝突不能盲目覆寫。各完成輪次的正式 DB 寫入、commit、push、部署均為 0。

[驗收矩陣](ACCEPTANCE_MATRIX.md)／[來源與凍結版本附錄](../AI_EXPLANATION_2026-11-05/VERSION_MANIFEST.md)／[前階段本季資料與產品接線](../AI_EXPLANATION_2026-11-05/README.md)。
