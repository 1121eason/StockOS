# 內部政策來源：檢查與執行指南

此分支擴充離線研究匯入格式，讓固定 WACC／終值成長率的內部政策紀錄有明確類型。它沿用原本的 DCF 計算，不修改財務假設、交易規則或正式核准條件。

## 這次可以檢查什麼

- `src/valuation_engine/research/workspace.py`：嚴格驗證來源、時點、雜湊與政策參數，計算估值並保存不可變結果。
- `tests/unit/test_internal_policy_workspace.py`：新格式、拒絕錯誤資料與舊格式相容性測試。
- `ui/research.*`：唯讀研究頁與 DOM 測試。經濟資料日期和目前重建截止時間分開顯示。
- [完整資料契約與相容性](INTERNAL_POLICY_RECONSTRUCTION.md)。

原始研究輸入、逐筆回測紀錄、來源資料庫及私人驗收附件留在私人儲存區，沒有放入公開 Git。公開測試使用合成資料；新 clone 不會自動帶入私人研究結果。

## 在自己的環境執行

先依專案說明安裝 Python 相依套件。以自己準備且符合契約的 JSON 檔案匯入，資料庫路徑必須明確指定：

```sh
python scripts/import_research_workspace.py --db /your/private/research.sqlite import /your/private/bundle.json
python scripts/import_research_workspace.py --db /your/private/research.sqlite list
python scripts/serve_ui.py --port 8501 --research-store /your/private/research.sqlite
```

開啟 `http://127.0.0.1:8501/research`。瀏覽器只能讀取結果，沒有寫入或交易功能。沒有資料時維持空白狀態，不以合成估值冒充真實資料。

```sh
python -m pytest tests/unit/test_internal_policy_workspace.py -q
npm ci
npm test
npm run check
npm run build
```

## 必須保留的限制

- 這是目前重建的研究資料流，不證明模型或完整訊號曾在歷史時點存在。
- 內部政策的建立、生效、目前觀察時間，不能當成外部發布時間；不存在的發布／歷史可用時間仍為 null。
- 來源與時間仍為提供者聲明，尚未獨立驗證；歷史樣本外與來源／模型／價格版本驗證旗標保持 false。
- 此流程重播既有研究數值，沒有呼叫新 AI 模型；正式研究判斷維持 withheld。
- SQLite 結構版本仍為 1。新版可讀舊格式，舊程式會拒絕新格式結果；需要保留舊程式時，請使用獨立研究資料庫，不直接混用。

## 驗證紀錄

本次為重新建立的修補，已使用本次程式碼重新執行測試，沒有沿用先前遺失工作區的測試結論。

- 研究儲存區測試：397 通過（307 新增、90 既有）。
- UI：20 個測試通過，語法檢查與建置通過。
- 修改的 Python 檔案：Ruff、格式檢查與 mypy 通過。
- 完整 Python 測試：1303 通過、5 跳過、6 失敗。6 項均為既有 Gemini provider 測試，在 Linux 缺少 macOS sandbox-exec 時失敗；沒有放寬隔離條件或隱藏失敗。
- 私人 13 季資料：canonical DCF、不可變儲存、真實唯讀 API、重複匯入一致性與歷史截止拒絕案例通過。正式 JavaScript 的 DOM 檢查涵蓋全部 13 筆結果與 465 張來源卡片。這不是瀏覽器截圖／視覺版面驗收。

本分支供檢查，未合併 main 或部署。GitHub CI 狀態須以該次發布 commit 的實際結果為準，不以本機測試代替。
