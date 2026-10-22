# NVIDIA 單季執行範圍決策

狀態：2026-10-22 使用者已核准 StockOS 自有程序範圍，並於首次診斷失敗後核准追加 1 次安全啟動。W1 凍結協定與原執行紀錄均保留。

原執行工單要求「確認本機無殘留之背景模型程序」，W1 工具也不會自動豁免桌面、parent 或未知 provider 程序。這台電腦同時有其他 Codex／Claude 工作，因此完整主機排他與可用的日常工作環境有衝突。不能把所有被偵測到的程序當成殘留，也不能為了本次研究關閉其他工作。

## 已核准的明確範圍

只允許本輪 StockOS 控制器同時啟動一個 provider request。所有本輪診斷、方法 B 與方法 C 共用一個固定 state root 與 `global-active.lock`。控制器記錄啟動 PID／PGID、完整 request／response、退出及清理；未知狀態保留鎖並停止，不終止其他工作的程序。不宣稱整台主機只有一個 AI 程序。

這是對原主機排他規則的**明確調整**。可審查實作在 `src/valuation_engine/ai/quarter_runtime.py`，合成測試在 `tests/unit/test_quarter_runtime.py`。舊 V1 transport、W1 凍結 protocol、Guard、提示詞與正式資料庫均維持原樣；未有綁定本合約的使用者決策前，新控制器拒絕啟動。

## 原始 V2 上限與驗證範圍（保留原決策）

- 新版工具先做最多 **7 次非歷史資料的合成模型探測**，逐項確認網路、檔案、工具、連接器及 prompt injection 的封閉處理。任何失敗即停止。
- 通過後才執行既定 Q2 B/C，仍為 **22 次／方法、44 次／單對**。兩類合計最多 **51 次**；不增加研究 repeats，失敗／pending 也消耗額度，不以重建輸出資料夾重置帳目。
- 上限計算的是控制器啟動的 CLI requests。新版 CLI 拒絕覆寫內建 OpenAI provider 的 HTTP retry 設定；控制器維持零外層重試，但工具內部 HTTP 重連次數未獨立計量。不能把 51 次啟動上限宣稱為底層 HTTP 請求或計費次數上限，亦不切換到其他 provider 來繞過限制。
- 來源僅限原 Q2 固定封包，財務數字、估值與 Regime 不接受 AI 回寫。
- CLI 回報若沒有獨立 backend model snapshot，actual model 保持未知；B/C 比較保持 `UNVERIFIED_MODEL_SNAPSHOT_IDENTITY`，不宣稱同一模型快照的科學比較。
- 兩位真人盲評與必要裁決仍必須由真人完成。所有 AI 產物都是未核准的研究補充，不產生買賣建議或正式升格。

另一個選項是維持整台主機排他，另備沒有其他模型程序的乾淨環境；現有機器上的其他工作不會被本工具自動停止。

## 本輪唯一恢復核准：V2.1

使用者原文：「同意追加 1 次，通過安全測試後繼續單季分析」。本輪累計上限改為 8 次安全啟動、44 次研究啟動、52 次合計。只允許原帳本第 1 次的乾淨啟動失敗恢復；必須驗證原失敗帳本、結果及原始串流雜湊。任何其他失敗、pending 或清理未知仍停止。沒有新增研究 repeats 或外層重試。

V2.1 合約 hash：`a12cd7b8acd1731b9a0110a427f3ec20dff3a40909d123994cb702008571ac2b`。保留失敗帳本 SHA-256：`5afcc118fc3dc0111a067921a793f5fc02e90affe43967e5cd374183ee1302ed`。原 V2 核准檔保留，追加決策另存並綁定同一 shared state root；不藉新輸出資料夾重設額度。

完整 7 項安全診斷已通過，C1–C12 均 PASS。此結果僅適用已核准的 StockOS 自有程序與固定工具版本，不代表整台主機排他、獨立 backend model snapshot 已核實或 AI 語意品質合格。詳細原生紀錄見 [2026-10-22 診斷與研究結果](NVDA_AI_DIAGNOSTIC_2026_10_22.md)。
