# StockOS 本機 UI

在終端機執行（先將 `/path/to/StockOS-UI` 換成你的 checkout 路徑）：

```bash
cd /path/to/StockOS-UI
python3 scripts/serve_ui.py --port 8501
```

打開 **http://127.0.0.1:8501**。只需 Python 3.12 以上，不必安裝 npm 套件或設定 API key。

停止：回到啟動服務的終端機按 **Control + C**。重新啟動：再執行同一行命令。

本版使用虛構公司與合成財務資料，透過既有 DCF 引擎計算。尚未連接原始研究資料庫、即時報價或 AI 供應商。

詳細操作、停止背景服務、疑難排解與開發檢查請見 [繁體中文使用指南](docs/UI_GUIDE.zh-TW.md)。驗證紀錄與待補項目見 [UI 驗證紀錄](docs/UI_VALIDATION_20261016.md)。
