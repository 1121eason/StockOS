# StockOS UI v0.1：本機啟動與使用指南

## 版本與目錄

| 項目 | 內容 |
| --- | --- |
| 本機目錄 | 自行選擇的獨立 checkout 路徑；以下以 `/path/to/StockOS-UI` 代稱 |
| UI 分支 | `codex/stockos-ui-20261016` |
| 已核對後端基線 | `cbb78db1ea0fe8fef8565d855605c7696cb13f3c` |
| 基線來源 | `1121eason/StockOS` 的 `codex/stockos-offline-source-20261015` |
| 本機網址 | `http://127.0.0.1:8501`（也可用 `http://localhost:8501`） |
| 技術 | Python 標準函式庫 HTTP server、原生 HTML/CSS/JavaScript ES modules |
| 執行需求 | Python 3.12 以上、現代桌面瀏覽器；實測 Python 3.14.6 |

這是獨立 Git clone，不共用原目錄的 index 或工作樹。原本研究目錄的 main、未提交修改、`.env`、研究資料庫與 `sources/` 沒有被本次實作改寫。公開範圍僅限專用 UI 分支；不合併 main、不部署，也不更新後端或來源同步分支。實際機器路徑另存於不追蹤的本機使用筆記。

## 啟動、停止與重新啟動

打開 Mac「終端機」，將 `/path/to/StockOS-UI` 換成你的 checkout 路徑後執行：

```bash
cd /path/to/StockOS-UI
python3 scripts/serve_ui.py --port 8501
```

看見 `StockOS 示範工作區：http://127.0.0.1:8501` 後，在瀏覽器開啟該網址。保持終端機開著。使用本機 UI 不必安裝專案所有 Python 相依套件，不必建立 `.env`，不需 OpenAI 或其他模型帳號；伺服器只載入既有 DCF 計算模組及其純 Python 數值工具。

停止時，回到啟動服務的終端機按 **Control + C**。重新啟動時再執行相同命令。這不是背景常駐系統服務；不會新增開機啟動項目或改變 Mac 設定。

如果預覽由 Codex 啟動，沒有可直接按 Control + C 的終端機，可先查詢：

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN
```

確認顯示的是 StockOS 的 Python 程序，再以 `kill <PID>` 停止該程序；`<PID>` 換成剛查到的數字。不要直接停止所有 Python 程序。再依上述命令啟動即可。

若 8501 已被占用，可改用：

```bash
python3 scripts/serve_ui.py --port 8502
```

網址也要改為 `http://127.0.0.1:8502`。服務固定綁定 `127.0.0.1`，不會透過區域網路對外提供；手機版面可在 Mac 瀏覽器縮窄視窗檢查，不必對外公開伺服器。

## 三分鐘操作導覽

1. **選擇研究公司**：右上公司按鈕可依中文名稱、英文名稱或代碼搜尋。AUR「雲曜運算」展示一般估值；ATL「衡川半導體」展示負股權估值；NEW「尚未建立研究」展示缺值。三者都是示範對象，不是真實證券。
2. **估值總覽**：看 DCF 每股基準值、折現率敏感度範圍、五年現金流與研究限制。敏感度端點是 WACC 加減 **1 個百分點**，不是機率、信賴區間、目標價或預期報酬。
3. **假設沙盒**：修改 WACC、終端成長率、額外年成長率、現金、負債、流通股數，按「計算情境」。輸入全部必填，現金與負債可明確填 0，股數必須大於 0，WACC 必須高於終端成長率。結果只保留在此瀏覽分頁的記憶體；切換頁面後仍可看到已套用結果，重新整理或關閉分頁則還原。未套用就離開時會出現保留／捨棄提示。
4. **模型與證據**：查看來源、資料時點與缺少／過期／未驗證／隔離／不可用狀態。可以選擇 `FY2027` 或 `FY2027-Q3` 示範明確財年格式；沒有正式同目標比較資料時，判斷仍暫緩。選擇會在本次分頁工作階段內保留。
5. **資料與驗證**：區分合成快照時點與真正的 API 回應時間，檢查本機服務與整合邊界。「重新檢查」只呼叫本機健康端點，不會同步資料或執行研究流程。

桌面左下「使用指南」提供簡短導覽；窄螢幕也可從「資料與驗證」開啟。使用 Tab / Shift + Tab 移動焦點、Enter 啟動連結或按鈕、Escape 關閉對話框。原生公司對話框提供焦點範圍限制與關閉後焦點返回；圖表有文字替代及對應數值，表格可水平捲動。實際瀏覽器鍵盤與窄螢幕驗收狀態另見驗證紀錄。

## 哪些是真的，哪些是示範

| 項目 | 本版實際行為 |
| --- | --- |
| DCF 計算 | 呼叫基線的 `valuation_engine.research.dcf.DCFModel`，以 Decimal 計算；不是前端寫死的估值 |
| 公司、現金流、現金、負債、股數 | `ui/fixtures/demo.json` 的合成資料；不是真實公司資料 |
| 資料時點 | fixture 的歷史合成日期；刻意展示時點過期狀態 |
| API 回應時間 | 本機伺服器實際回應時間；不能當作財務資料更新時間 |
| 市場價格、價格差距與報酬 | 無法取得，不顯示虛構報價或報酬 |
| 正式 Regime | 沒有 company / run / checkpoint 綁定；不顯示正式狀態或信心分數 |
| AI | 未載入模型輸出；未綁定內容維持隔離，不調整估值 |
| Forecast Revision | 須明確財年目標；本版沒有正式比較資料，維持暫緩 |
| 研究判斷 | 暫緩是資料與治理狀態，不是買進、持有或賣出建議 |
| 原始研究資料庫／付費 API | 不讀取、不寫入、不呼叫；沒有資料庫連線或匯入入口 |

計算使用五年合成 FCFF 路徑；「額外年成長率」令第 n 年 FCFF 乘上 `(1+r)^n`。原始路徑本身已包含各年的合成數值，r 是額外調整，不是正式預測引擎產生的成長率。現金、負債與企業價值單位為百萬 USD，股數單位為百萬股，輸出為 USD／股。

DCF 零值和負值原樣保留，不會截斷為 0。負股權估值不是可成交負股價或賣空建議。未調整 CFO − capex 不會被標為 FCFF；正式現金流仍需依原後端研究流程調節。若敏感度端點的 WACC 不符合模型限制，該端點會顯示不可用；不會補上假數字。

## 常見問題

| 狀況 | 處理方式 |
| --- | --- |
| `python3: command not found` 或版本太舊 | 先檢查 `python3 --version`，需要 3.12 以上。本版曾以 3.14.6 驗證；啟動 UI 不需額外套件 |
| `Address already in use` | 已有服務在該埠執行；先開網址檢查，或改用 `--port 8502` |
| 瀏覽器無法連線 | 確認終端機仍在執行、網址埠號一致，使用 `127.0.0.1`，不是 `file://` |
| 只看到載入或頁面未更新 | 重新整理；本版不含熱更新。確認瀏覽器允許 JavaScript，且 `ui/` 檔案沒有被移動 |
| 「工作區暫時無法載入」 | 檢查服務與網址中的公司代碼，按「重新載入」；未知公司可按「返回預設示範」 |
| 計算失敗 | 依欄位訊息修正；服務中斷時輸入仍保留，可啟動服務後重試 |
| 某些欄位顯示「—」或「暫緩」 | 這是刻意保留的缺值／限制狀態，並非待隱藏的錯誤；見上方資料邊界 |
| npm VM Modules 實驗性警告 | 僅為可選開發測試使用 Node VM 載入實際前端模組的提示，不影響 Python 啟動或 UI |

## 可選開發檢查

使用 UI 不需要 Node。要重跑前端互動測試，需 Node 18 以上（實測 22.14.0），安裝已宣告並鎖定的 dev dependency：

```bash
npm ci --ignore-scripts --registry=https://registry.npmjs.org
npm run check
npm test
python3 scripts/build_ui.py
```

建置只核對與封裝原生資產到 `dist/stockos-ui/`；不是獨立靜態部署包，仍需 Python API。DOM 測試會自行啟動暫時、僅限 localhost 的合成 API 並於結束時停止，不接觸目前預覽服務或原始資料庫。`jsdom` 對話框介面在測試中有基本替身；這不等同原生瀏覽器焦點圈與版面驗收。

Python 的 lint、type 與相關單元測試請使用依 `pyproject.toml` 與 `uv.lock` 建立的專案 dev environment。以下假設已在目前 checkout 建立 `.venv`；執行 UI 本身不需要這個環境：

```bash
.venv/bin/ruff check --no-cache scripts/serve_ui.py scripts/build_ui.py tests/unit/test_ui_workspace.py
.venv/bin/mypy --cache-dir=.mypy_cache --follow-imports=silent scripts/serve_ui.py scripts/build_ui.py
.venv/bin/python -m pytest -q tests/unit/test_ui_workspace.py tests/unit/test_dcf_research.py tests/unit/test_cadence_revision_context.py tests/unit/test_cadence_formal_regime.py
```

## 後續整合邊界

真實資料唯讀快照尚未接上。本版沒有要求你提供資料庫或 API key，也不接受任意檔案路徑。下一版需要另行設計明確選擇的唯讀快照契約、完整來源時間與 company / run / checkpoint 驗證，並透過既有正式驗證器核對後，才可呈現正式研究結果。不要只替換 demo fixture 就將畫面視為正式分析。

發布時先檢查後端分支是否前進，再協調 cherry-pick UI commit；本次沒有覆寫後端檔案。不要將原始資料庫、`.env`、`node_modules/` 或預覽伺服器日誌加入版本控制。
