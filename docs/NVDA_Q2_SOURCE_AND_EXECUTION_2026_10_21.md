# NVIDIA Q2 來源核對與受控執行準備

後續原生執行結果見 [2026-10-22 診斷與研究紀錄](NVDA_AI_DIAGNOSTIC_2026_10_22.md)。本文保留原始準備階段的狀態。

本輪延續 PR #4，範圍仍為 NVIDIA FY2023-Q2。已補齊當前官方研究文字與保守時間界線的核對，並完成獨立的 V2 控制器與受控候選入口。**尚未執行真實模型，正在等候排他範圍及診斷額度的明確選擇。**

## 來源核查結果

原 HTTP 403 紀錄保留。透過正常瀏覽器讀取兩份 SEC 原件與正確的 `.htm` 申報索引，分段完整保存 DOM，避免單次字串擷取的長度限制。對 DOM 使用原有 canonical narrative parser，再與原固定封包逐段核對；沒有刪除字詞、標點或移除所有空白來放寬比對。

| 原件 | 完整原有研究段落 | 精確吻合 | 獨立觀測到的保守可用時間上界（UTC） |
|---|---:|---:|---|
| [Q2 官方新聞稿](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2023) | 38 | 38 | 2022-08-25 04:00；官方可見發布日的次日午夜 ET |
| [Q1 官方新聞稿](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2023) | 45 | 45 | 2022-05-26 04:00；官方可見發布日的次日午夜 ET |
| [10-Q 申報索引](https://www.sec.gov/Archives/edgar/data/1045810/000104581022000079/0001045810-22-000079-index.htm) | 237 | 237 | 2022-05-28 04:00；受理時間與 filing-date 次日界線取較晚者 |
| [10-K 申報索引](https://www.sec.gov/Archives/edgar/data/1045810/000104581022000036/0001045810-22-000036-index.htm) | 612 | 612 | 2022-03-19 04:00；受理時間與 filing-date 次日界線取較晚者 |
| 合計 | **932** | **932** | 全部早於固定 cutoff：2022-08-25 13:30 UTC |

這項結果是「目前官方研究文字一致、保守時間上界可核對」。DOM serialization 與歷史 HTTP 原始 bytes 的證明不同；舊分鐘級發布斷言仍未獨立證實，不回填為 exact publication，也不宣稱 historical OOS。原 package、原來源 hash、932 段及 22 筆排除紀錄均保留。

`scripts/verify_nvda_q2_sources.py` 可重現完整核查；它不連網、不執行模型、不開啟正式 DB，只讀取明確提供的原件及當次官方擷取證據。私有結果為 `source-proof.json`，狀態為 `VERIFIED_CURRENT_NARRATIVE_AND_CONSERVATIVE_PIT_BOUND`。

## V2 受控流程

新入口 `scripts/run_nvda_q2_candidate.py` 分為兩個明確階段：

1. `--phase diagnostic`：核對本輪 binary 與原生 kernel 收據，最多 7 次合成模型探測；保存完整 request、stdout、stderr、退出與觀測到的子程序狀態，再產生 C1–C12 gate 收據。模型快照身分仍不冒充已核實。
2. `--phase research`：重新核對固定封包、四份來源及保守時間界線，核對前 7 次完整、未遭更動且清理已確認的探測紀錄，才可執行既定方法 B/C。所有模型請求由控制器內部 adapter 啟動，不接受任意 provider 注入。

兩階段共用固定 state root 與 owner-bound `global-active.lock`，失敗、pending、清理未知或原紀錄被更動都停止。方法 B/C 仍受 22／44 上限限制；原 `--live`／`LIVE_EXECUTION` 入口繼續拒絕啟動。候選另存新的 SQLite，不寫入正式 `qve.db`。

已加入原始串流、attempt 及 result 的 hash 綁定、二進位漂移拒絕、未知事件／工具嘗試即停止、成功輸出後的有限正常退出等待，以及未知清理時保留鎖。完整驗證仍需實際模型探測和真實候選結果，合成測試不代替它們。

## 待決策項目

具體方案與影響見 [執行範圍決策](NVDA_AI_RUNTIME_V2_DECISION.md)。此版本的合約 hash 為 `dcc0d45a1a9b49141fd916bf94371a11fa1e0e60c9541a69fb89abab0ff9ffb9`。

- 建議只序列化及清理 StockOS 本輪自己啟動的程序，保留其他專案正常運作；不宣稱整台主機只有一個 AI 程序。
- 新增最多 7 次合成模型探測，研究仍維持最多 44 次，合計最多 51 次控制器啟動，零外層重試。
- 原生設定核對發現新版 CLI 禁止覆寫內建 OpenAI provider 的 retry 設定。未改用其他 provider；內部 HTTP 重連次數保持未獨立計量，不把 CLI 啟動次數當作 HTTP 或計費次數。
- 沒有綁定本合約與 shared state root 的實際使用者決策，控制器會拒絕啟動。測試中的模擬決策檔僅用於 fake CLI，不能被回報為人類已批准真實執行。

AI 仍是未核准研究補充。真人盲評、必要裁決、缺少 repeat 時的穩定性判讀、正式投資決策及 promotion 均未完成；不產生分數、winner、買賣建議或其他股票分析。

## 驗證與證據入口

本輪受影響路徑 **122 項測試通過**，包括來源日期／身分錯配、文字差異、鎖衝突、額度保留、失敗停止、未知清理與原始串流被更動等案例。最終完整 Python 為 **1,382 passed、5 skipped、0 failed、0 errors**，54.111 秒；Ruff、148 檔格式檢查與 88 個 source files 的 mypy 通過。5 個 skip 仍需要隔離 PostgreSQL、實際 archive 或完整回測資料。

狀態與檔案雜湊見 [本輪驗證摘要](verification/2026-10-21-nvda-q2-execution.json)。原始來源、完整 DOM、程序清單、模型測試中的 fake CLI 及私有研究封包均不隨程式碼提交。真實模型探測與分析仍為 0 次。
