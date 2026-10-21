# NVIDIA 季度研究工作台

此版本將既有 NVDA 正式研究接成同一頁：最近一季與上一季財務、模型估值及敏感度、Regime、同一財年預測修訂、來源與限制。正式資料庫只讀；沒有安裝資料封包的 clone 不會自動取得研究結果，也不會用示範數字補位。

## 開啟與更新

本機已配置的使用者，可執行交付時提供的啟動檔，再打開工作台網址。一般安裝方式：

```sh
uv sync --locked
uv run python scripts/serve_ui.py --port 8510 \
  --source-db /absolute/path/qve.db \
  --raw-dir /absolute/path/raw \
  --workbench-store data/nvda-workbench
```

兩個來源參數須一同指定，且使用實際存在的絕對路徑。瀏覽器開啟 `http://127.0.0.1:8510/nvda`；啟用來源時根路徑也直接顯示 NVDA。按「更新研究與股價」完成核對、重算、報價與保存。未配置來源時 `/nvda` 清楚顯示缺資料，舊示範與匯入研究介面保留相容性。

## 本次更新會做什麼

1. 以 read-only／immutable 連線讀取明確指定的 SQLite，拒絕 WAL、SHM 或 journal sidecar。
2. 沿用既有正式 forecast resolver，選取最新兩個連續季度；對齊 exact valuation、修正後 Regime 與同一模型／假設集合。
3. 以原有標準化程式重建已顯示的財務數字，核對快照數值、fact IDs、company 及研究截止時間。
4. 從明確 raw directory 依內容雜湊尋找原件，不追隨歷史 `raw_path`；逐份重算 SHA-256，保留發布／取得／歷史可用時間的差異。
5. 用原有 `DCFPolicyV1` 重算已保存的每個敏感度格及基準值。任何不一致均停止發布。
6. 獨立取得 NVDA 報價與估值日以後的供應商拆股紀錄。股價不進入財務預測、DCF 假設或 AI context。
7. 保存內容定址的本機研究快照，再原子替換目前快照指標。來源、計算或保存失敗時，舊指標與舊研究保留。

這條更新流程使用既有財務成果。自動下載新財報、重建新的正式預測／Regime、正式寫入及排程尚未啟用，不能把一次研究更新解讀為新財報全流程驗收。

## 股價與模型價值

- 股價為 Yahoo Finance chart feed 的最近常規交易成交價，使用供應商 `regularMarketTime`；不包含盤前、盤後或夜盤，不保證即時。
- 模型價值保留原研究季度與估值日。畫面同時顯示兩個日期，沒有把舊研究變成今日的新預測。
- 如估值日以後有拆股，差距比較使用供應商拆股事件換算後的每股基準，並標示換算。供應商紀錄尚未獨立核證。
- 比較公式為「模型每股價值 ÷ 股價 − 1」。這只是模型與市場報價的差距，不是預期報酬。
- 報價缺失、身分／時間／拆股格式不符時，不補零。超過五日的報價標示過期，不計算差距；報價失敗不使已核對財務與模型結果消失。

## AI 與決策界線

AI 區固定為研究補充。沒有對本研究版本與季度核准的輸出時，顯示待正式驗收。未核准候選不進入本頁估值，也不產生買賣建議。單季驗收準備與阻擋條件另見 [AI 工作線](AI_RESEARCH_SUPPLEMENT_2026_10_21.md)。

## 測試與資料保留

```sh
env -u QVE_TEST_POSTGRES_URL uv run pytest -q -rs
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run mypy src
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run check
npm run build
```

HTTP 與模擬 transport 測試需要執行環境允許本機 loopback。測試使用臨時 DB 與合成 provider，不代表真實模型驗收。原始研究資料庫、原件、工作台快照、AI 封包與含實際數值的驗收畫面均留在本機，不隨程式碼提交。
