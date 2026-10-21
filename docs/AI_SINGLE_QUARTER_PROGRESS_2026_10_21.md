# NVIDIA 單季 AI 驗收進度

日期：2026-10-21。PR #3 已合併到 main，merge commit 為 `4f45f2d0174c1dba77516a9a4cae03577f0eeae6`。本次後續工作限於 NVIDIA 的 FY2023-Q2 受控研究補充；不擴充股票，不把該季候選分析套到工作台的 FY2027-Q2。

## 本次實際完成與未完成

| 項目 | 當次證據 | 狀態 |
|---|---|---|
| 使用者授權 | 已收到合併 PR #3 與推進單季真實分析的明確指令；另存新授權紀錄，不改寫 W1 舊授權 | 已記錄 |
| 完整單季輸入 | 固定的 4 份來源、932 段 narrative、22 段排除紀錄，重新解析與內容雜湊相符 | 已核對 |
| 預算與研究版本 | 凍結 protocol、package、方法 B/C、Guard、schema、rubric 保持原值；20 個 extraction chunks，加 synthesis/challenge，每方法 22 次、合計 44 次 | 在上限內；未增加重試或 repeats |
| 當次工具身分 | 官方登入狀態確認使用 ChatGPT；原合約要求 `codex-cli 0.153.4`，現有工具為 `0.163.0-alpha.10.2`，已記錄當次 binary hash 與 feature 查詢 | 新版完整執行合約尚未重新驗證 |
| 作業系統隔離 | 同一 named profile 的外部讀取、工作區寫入、loopback 連線各有成功的 unrestricted control，受限操作均明確回報權限拒絕 | 三項 command probes 通過；不是完整 provider／C1–C12 通過 |
| 程序生命週期 | 本次自行建立的合成程序逾時後終止、wait/reap，並核對 process group 不存在 | 單一自有合成程序通過；不是實際模型及所有後代程序的驗收 |
| 全域排他 | 已原生收集完整 pid／ppid／executable census，保留原文及 hash；模型工具、桌面及 interpreter 程序均無隱含豁免 | 分類、共享鎖整合與實際 provider 殘留核驗未完成 |
| 官方新聞稿 | 兩份新聞稿目前的完整 HTML 與舊 cache bytes 不同；但 38/38 與 45/45 段所選研究文字均可在當次官方頁面比對到 | 當前文字核對通過；歷史發布分鐘與可用時間仍未獨立證實 |
| SEC 原件 | 當次直接擷取兩份指定 SEC 文件均回傳 HTTP 403，另有保存失敗紀錄；未覆蓋或替換原件 | 原件真實性與歷史可用時間仍待補證 |
| 新模型分析 | 本次真實模型 attempts = 0；沒有新輸出可供評分 | 尚未啟動 |
| 真人盲評 | 兩位獨立審查及必要裁決尚無新輸出可綁定 | 尚未進行；UNSCORED、winner=null、promotion_ready=false |
| 正式研究資料 | 正式 DB SHA-256 與單季準備時相同；W1 六個候選檔案仍符合原 manifest | 正式 DB 寫入、公式變更及新增股票均為 0 |

「偵測到候選程序」不代表全部都是殘留模型：桌面 app、本次工程工具、其他使用中的工作與 interpreter 也可能被列入。未經核對的程序不能當作乾淨環境，也不能直接終止。沒有刪除未知鎖、重啟既有模型或關閉其他工作。

初次 Python command probe 分別被擋在私人 Python 路徑與系統 Python 的開發工具啟動階段，兩份結果保留為 UNVERIFIED。後續使用系統內建 dd／sh／nc，才實際執行到三項受限操作；不以工具啟動失敗冒充隔離通過。

後續補測亦發現重複終止訊號會在第二次訊號時遇到 PermissionError，令該次收尾未完成。該失敗紀錄保留，不回填為 CLEAN。修正後只送出一次終止訊號，啟動即保存 PID／PGID 與 PENDING 狀態；拒絕終止或未知 group 狀態會保存 UNKNOWN 並停止。新增故障測試驗證「訊號一次、退出後才判定清理完成」及「拒絕時保留未知、不重試」。

## 可重現工具與邊界

`scripts/preflight_nvda_ai.py` 僅接受這一個固定 NVDA Q2 封包。先重算 protocol／package hash、全部 cached bytes、完整 narrative 及 exclusions，再收集原生程序、CLI discovery，並可擷取明確白名單內的官方來源。HTTP redirects 每一跳均重新驗證；不繼承環境中的 proxy 或 API key。當前網頁比對與歷史時間驗證分開記錄。

```sh
PYTHONPATH=src python scripts/preflight_nvda_ai.py \
  --preparation /absolute/private/q2-preparation \
  --raw-dir /absolute/private/raw \
  --executable /absolute/path/to/codex \
  --output-dir /absolute/private/NEW-audit-directory \
  --capture-official-sources

PYTHONPATH=src python scripts/probe_nvda_ai_runtime.py \
  --executable /absolute/path/to/codex \
  --output-dir /absolute/private/NEW-command-probe-directory
```

前者正常完成但有未解門檻時 exit code 為 2，`ready_for_live` 固定為 false；不是執行失敗被隱藏，也不是 live 授權開關。後者只測試 macOS 原生 command profile 與自有合成程序，不能解鎖 S2。兩者均拒絕重用既有輸出資料夾；不讀取 credential store，不登入或修改使用者設定，不呼叫模型，不開啟正式資料庫。

執行設定對照 [OpenAI 非互動模式](https://developers.openai.com/codex/noninteractive/) 與 [設定參考](https://developers.openai.com/codex/config-reference/)。官方文件的設定說明不取代當次原生驗證。新聞稿來源：[FY2023-Q2](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2023)、[FY2023-Q1](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2023)。

## 下一個可執行門檻

1. 為目前實際 CLI 固定獨立新版 transport 合約，補足 model-facing 隔離、工具事件及回報身分驗證；不能只改舊版號常數。
2. 審查全域程序分類與共享鎖的規則，取得本輪啟動／退出／失敗／殘留的完整記錄；只允許處理本輪可確認擁有的子程序。
3. 補齊 SEC 原件與所選來源的歷史時間佐證，維持未知時間的明確缺失狀態。
4. 前項通過後，才用固定封包與 22/44 上限產生新的 B/C 候選，保存完整 request／response／attempt／拒絕帳；失敗及 pending attempts 不重置。
5. 有完整新輸出後，依凍結規則製作盲評資料並交由真人評分。AI 品質、歷史 OOS、投資決策與正式升格仍分別驗收。

完整私有原件、來源 captures、程序 census 與原始收據保留本機。公開的 [驗證摘要](verification/2026-10-21-nvda-ai-native.json) 只記錄狀態、計數及檔案 hash，不包含私人 DB、auth、完整程序清單或研究輸出。

## 工程驗證

- 最終完整 Python：**1,352 passed、5 skipped、0 failed、0 errors**，64.24 秒。新增 24 個案例；5 個 skip 仍需隔離 PostgreSQL、實際 archive 或完整回測資料。
- Ruff 通過；142 檔格式檢查通過；mypy 檢查 85 個 source files 通過。
- 最終固定版 native command probes 三項通過；自有合成程序為 CLEAN、reaped=true、group_absent=true。這些計數不等於模型分析或人審通過。
- 初次受限環境的完整測試因 loopback／subprocess 隔離限制出現 3 failed、6 errors；保留原紀錄，取得原生測試權限後才完成上述通過結果。沒有修改產品程式來繞過測試。
- 本次沒有變更 UI，沿用 PR #3 的工作台瀏覽器驗證；沒有將它重報為本輪新增瀏覽器驗收。
