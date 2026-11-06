# M4.1 V5：R03 失敗診斷工單

狀態：待 Luna 執行。這份工單的建立不代表已修補程式或已授權本審查任務重新呼叫模型。使用者將本工單交給 Luna 執行時，執行範圍依下列限制。

## 1. 目標與本次審查結論

R02 已完成舊鎖恢復。R03 attempt `20260925T121458Z-595e4dd8de81` 的結果仍為 **FAIL**，R04–R07 未執行。接下來要區分「CLI 先報什麼錯」與「誰要求終止程序」，取得可用的失敗診斷。

獨立審查已驗證：

- `codex_pit.monitor()` 收到 `error` 或 `turn.failed` 會先設定 `provider_failure`，在 `finally` 呼叫 SIGKILL 清理程序群組。因此 `exit_code=-9` 可能是 runner 清理的結果，不能直接推論 OOM、OS 封鎖、權限、帳戶或模型故障。
- 本機替身分別重現 `error → runner SIGKILL → -9`、`turn.failed → runner SIGKILL → -9`，以及「子程序自行 SIGKILL、runner 沒有送信號 → -9」。三者都被現有程式分類為 `provider_failure`；正常完成對照案例 exit 0。這四例沒有呼叫 Codex 或模型。
- monitor 在記憶體內保存事件種類與 hash，但 probe 收據只保存整體 hash、退出碼及概括分類，沒有留下足以區分上述情況的資料。hash 無法還原原始錯誤。歷史 attempt 的原因必須維持 unknown，除非找到可與該 PID／時間／attempt 對應的既存證據。
- `inference_started` 目前緊接 Popen 成功寫入，僅能證明 CLI 子程序啟動，不能單獨證明遠端已接受推論。
- 86 份舊收據 hash 全部相同，R03 四份 artifact 的實際 hash 與交付紀錄相符；原 lock 備份 SHA-256 及 inode 相符，`active.lock` 不存在；正式 DB 最新 AI run 13、snapshot 2。相對 Luna 本輪基線，只有 tracker 和 Q2 報告的內容變更。

證據：[獨立替身重現與保全核對](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-independent-review-20260925T122323Z-ab02795c/offline-reproduction.json)。

## 2. 範圍與不可改動項目

- 工作目錄固定 `/Users/eason/Documents/Coding/StockOS`。先讀 `AGENTS.md`、tracker、Q2 執行報告、本工單和 R03 原始收據。
- 保留所有既有未提交修改，`sources/` 唯讀，不 reset、clean、覆寫歷史收據，不 commit／push。
- 新建唯一 review 目錄，保存 HEAD、狀態路徑及檔案 hash、86 份舊收據、R03 收據／日誌、legacy lock 備份及正式 DB 基線。先核對現況；若出現新的 active/unknown attempt，不得解除其鎖或啟動模型。
- 主要修改限於 `src/valuation_engine/ai/codex_pit.py`、`scripts/probe_codex_pit_launch.py`、相關 recovery/PIT 測試及必要的診斷欄位傳遞。不要藉此改估值方法、prompt、model、CLI 版本、隔離政策或重試政策。
- 不執行 R04 native probes、R05 隔離驗證、R06 Q2、R07 結果驗收、其他季度或 PostgreSQL，不寫正式 DB。

## 3. D01：先做唯讀診斷

1. 核對歷史 probe、progress、discovery 與執行時程式 hash，追查 monitor 到 probe 收據的欄位流向。
2. 若有既存 CLI／系統診斷，只查 R03 時間區間及 PID 46401 能明確關聯的紀錄。不得把同名 Codex 程序、其他任務錯誤或一般 OOM 記錄當作本案根因；不得輸出憑證或完整 argv。
3. 沒有可用歷史證據時，記錄「無法追溯」，繼續 D02；不要在「必須先找回不存在的原始錯誤，才能補診斷」上停住。D04 是新的診斷 attempt，不是重寫舊 attempt 的原因。

## 4. D02：補齊診斷，保留安全終止行為

在維持有界 wait、原本隔離限制與 unknown 保留鎖的前提下：

1. **原始失敗與清理結果分開記錄。** 保存首次失敗的事件種類／序號／時間、允許的錯誤碼或 HTTP status、必要的去敏摘要及 event hash；清理失敗不得覆蓋首次原因。最終 `failure_kind` 仍可依安全需要為 `termination_unconfirmed`。
2. **記錄 runner 的終止要求。** 保存送信號前的程序狀態、目標 PID／PGID、信號種類、觸發原因、時間、呼叫結果及有界 wait 結果。「嘗試送信號」「系統呼叫成功」「確定由該信號造成退出」是不同證據，不可混為一談；無法判定因果時保留 unknown。
3. **把診斷實際寫入收據。** probe 保存有界的事件摘要、首個錯誤、終止要求、observed exit code 和相關 hash，或綁定不可覆寫的診斷 sidecar 路徑及 bytes SHA-256。不能只算 `digest(result)` 後丟棄 result。限制數量／長度並標明截斷；不要持久化完整 prompt、token、環境、argv 或未去敏的 stdout/stderr。
4. **保持程序狀態可信。** launch failure 的未知時間／PID／exit code 不得補值；程序終止仍未確認時保留 lock、禁止重試。不能為了讀完錯誤而移除既有 timeout 或改成無限 wait。
5. **修正 probe 命令退出碼契約。** 只有收據 gate PASS 才 exit 0；FAIL／UNKNOWN／診斷收據寫入失敗均為非零。先完成必要的收據與 finally 清理，再退出；不要讓 `SystemExit` 造成錯誤的鎖釋放或誤判。
6. 報告明確說明現有 `inference_started` 的意義；若沒有 provider 接受／完成的證據，不宣稱遠端模型已開始或完成推論。

## 5. D03：先完成本機替身回歸

使用本機假 CLI、真實 monitor 與 probe 寫入路徑，不呼叫模型。至少驗證：

- `error`、`turn.failed` 後 runner 清理：首個錯誤與終止要求同時保留。
- 子程序自行 SIGKILL：exit -9，但沒有憑空產生 runner 送信號紀錄；不推測外部來源。
- 正常成功、launch failure、timeout、unknown termination 及診斷寫入失敗：退出碼、鎖和原有安全行為正確。
- 去敏、事件／訊息大小限制、敏感測試字串不落盤，以及首次錯誤不被清理結果覆蓋。
- CLI 層整合：PASS 為 exit 0；FAIL／UNKNOWN 非零；收據不可覆寫。

執行既有受影響測試、Ruff、mypy、`git diff --check`，並跑完整 SQLite 回歸，保存命令、退出碼、log 及結果。相關測試和靜態檢查必須通過才可進 D04；完整回歸若出現新失敗或無法歸因的失敗則停止。已知 Gemini 失敗必須核對名稱與原因，照實揭露，不能直接假設它們無關或宣稱全綠。

## 6. D04：最多一次有診斷紀錄的合成 probe

本工單允許在 D01–D03 完成、保全核對通過、沒有 active/unknown attempt 且以新的完整程序查詢確認沒有相關執行後，**額外執行最多一次真實合成 probe**。這次的目的是取得原先缺少的診斷，不要求先猜出歷史根因。

- 執行前保存唯一 launch intent，綁定新程式 hash、模型／CLI／政策、測試證據與新 attempt。只有無歷史資料的合成輸入。
- 必要的升權透過正式工具審核；不改用裸 `codex exec`、替代模型、較寬鬆 sandbox 或其他 transport 繞過原設定。
- 設定外層執行時間，容納既有內層 timeout 與有界清理；記錄外層狀態，不因工具畫面沒有更新而中途取消或重啟。
- 若無法確認終止，保留鎖並停止；若是已確認停止的 FAIL，保留失敗收據。沒有第二次真實模型呼叫，不增加外層自動重試。
- 無論 PASS／FAIL／UNKNOWN，本輪都在此停止。新 PASS 只代表合成 probe 通過；不能推論舊失敗根因，也不能進入 R04–R07。

## 7. D05：交付與後續判定

新增診斷報告，更新 tracker 與 Q2 報告時保留原 R03 FAIL，另列新的 attempt。回報：

1. 查到的事實、歷史仍未知的欄位，以及新診斷能證明什麼。
2. 修改檔案、測試命令／結果／退出碼、真實模型呼叫次數。
3. 首個 provider/CLI 錯誤、runner 清理要求、observed exit、程序／lock 狀態，各自列明。
4. 86 份舊收據、R03 歷史 artifacts、legacy lock 備份與正式 DB 的保全比對。
5. 新 probe PASS：下一批再安排 R04；FAIL：按新的具體錯誤提出最小修正，不自行再試；UNKNOWN：提供可執行的程序確認步驟。

不得宣稱 Q2 PASS 或 M4.1 Final Pass。
