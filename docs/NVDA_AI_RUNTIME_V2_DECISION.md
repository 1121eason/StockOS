# NVIDIA 單季執行範圍決策

狀態：待使用者決策；不是既有 W1 協定或執行紀錄的改寫。

原執行工單要求「確認本機無殘留之背景模型程序」，W1 工具也不會自動豁免桌面、parent 或未知 provider 程序。這台電腦同時有其他 Codex／Claude 工作，因此完整主機排他與可用的日常工作環境有衝突。不能把所有被偵測到的程序當成殘留，也不能為了本次研究關閉其他工作。

## 建議的明確範圍

只允許本輪 StockOS 控制器同時啟動一個 provider request。所有本輪診斷、方法 B 與方法 C 共用一個固定 state root 與 `global-active.lock`。控制器記錄啟動 PID／PGID、完整 request／response、退出及清理；未知狀態保留鎖並停止，不終止其他工作的程序。不宣稱整台主機只有一個 AI 程序。

這是對原主機排他規則的**明確調整**。可審查實作在 `src/valuation_engine/ai/quarter_runtime.py`，合成測試在 `tests/unit/test_quarter_runtime.py`。舊 V1 transport、W1 凍結 protocol、Guard、提示詞與正式資料庫均維持原樣；未有綁定本合約的使用者決策前，新控制器拒絕啟動。

## 執行上限與驗證範圍

- 新版工具先做最多 **7 次非歷史資料的合成模型探測**，逐項確認網路、檔案、工具、連接器及 prompt injection 的封閉處理。任何失敗即停止。
- 通過後才執行既定 Q2 B/C，仍為 **22 次／方法、44 次／單對**。兩類合計最多 **51 次**；不增加研究 repeats，失敗／pending 也消耗額度，不以重建輸出資料夾重置帳目。
- 上限計算的是控制器啟動的 CLI requests。新版 CLI 拒絕覆寫內建 OpenAI provider 的 HTTP retry 設定；控制器維持零外層重試，但工具內部 HTTP 重連次數未獨立計量。不能把 51 次啟動上限宣稱為底層 HTTP 請求或計費次數上限，亦不切換到其他 provider 來繞過限制。
- 來源僅限原 Q2 固定封包，財務數字、估值與 Regime 不接受 AI 回寫。
- CLI 回報若沒有獨立 backend model snapshot，actual model 保持未知；B/C 比較保持 `UNVERIFIED_MODEL_SNAPSHOT_IDENTITY`，不宣稱同一模型快照的科學比較。
- 兩位真人盲評與必要裁決仍必須由真人完成。所有 AI 產物都是未核准的研究補充，不產生買賣建議或正式升格。

另一個選項是維持整台主機排他，另備沒有其他模型程序的乾淨環境；現有機器上的其他工作不會被本工具自動停止。
