# StockOS M4.1：Codex V5 Recovery 修補技術工單

日期：2026-09-24  
執行者：Luna  
正式專案：`/Users/eason/Documents/Coding/StockOS`  
狀態：待實作；本文件不是修復完成或驗收通過的證明。

## 1. 任務與完成邊界

修正 Recovery 程式的無時限等待、收據覆寫及缺少回歸測試三項問題，完成正式 checkout 的本機驗證。使用現有工程計畫作為背景，**本工單只處理本機修補，不接續執行 P3–P5、真實模型 probe 或季度驗收**。

請直接完成本工單授權的修改與測試；舊模型程序狀態不明，不妨礙使用臨時目錄、測試替身與假 CLI 執行本機測試。

參考文件：

- [Recovery 工程計畫](M4_1_CODEX_V5_RECOVERY_ENGINEERING_PLAN.md)
- [前次執行報告](M4_1_CODEX_V5_RECOVERY_EXECUTION_REPORT.md)
- P0 基線：`data/m41/codex/attempts/20260924T091619Z-p0-d7ce3de8/manifest.json`

本工單完成僅代表本機程式修補可交付。P1 真實合成呼叫、PostgreSQL、Q2、七季、重跑比較與人工審查仍需各自驗收。

## 2. 已確認的審查證據

以下為本工單建立前的實際檢查結果，Luna 完成修補後須產生自己的新日誌：

| 項目 | 審查結果 |
|---|---|
| 受影響測試 | 64 passed |
| 完整 SQLite 回歸 | 243 passed、2 failed、1 skipped |
| 既有失敗 | `test_google_probe_and_isolation`、`test_service_ineligibility_is_not_login_failure` |
| Ruff | 4 errors：3 個 I001 import 排序、1 個 B904 例外鏈 |
| mypy | 71 source files，通過 |
| `git diff --check` | 通過 |
| P0 封存 | tracked diff 與 31 檔清單的 hash 均符合 manifest；沒有基線檔案遺失 |
| 最新 committed Codex run | run 13，PromptSetV4，22 provider calls，1 snapshot |
| V5 run | SQLite 唯讀查詢為 0；未找到 V5 完成收據 |
| 程序狀態 | `pgrep` exit 3，`Cannot get process list`；不能推論沒有舊程序 |

相較 P0 基線，當時僅四個既有檔案的內容改變：兩支 V5 runner、`codex_pit.py`、`service.py`；另新增 journal、probe 與執行報告。原測試檔 hash 未變，因此現有測試通過不代表新增保護已獲覆蓋。

## 3. 固定約束

1. 保留所有既有 M4.1 修改。禁止 `reset`、`restore`、`clean`、整檔還原或以 HEAD 取代目前內容。
2. `sources/` 唯讀；不修改、移動、重新命名或刪除同步參考檔。
3. 不刪除、改寫或解除 `data/m41/codex/attempts/active.lock`；不終止既有程序。鎖測試全部使用臨時目錄。
4. 不執行真正的 Codex／Gemini／其他模型呼叫，包括 `probe_codex_pit_launch.py` 的真實 main、任何 pilot 與 validation runner。測試可以匯入模組，但必須以替身阻止模型與正式 DB 存取。
5. 不寫入 `data/qve.db`，不修改舊 run、snapshot、收據、保護表或 C1–C12 歷史結果。
6. 保持 `AIAnalystPolicyV3`、`PromptSetV5`、`FeatureSchemaV2`、來源准入、數字 guard、80 words 引文限制及 `qve_pit` 隔離政策不變。
7. extraction 保持 180 秒，synthesis／challenge 保持至少 600 秒；不得靠增加 timeout、增加重試或放寬驗收來消除問題。
8. 本次不修兩個既有 Gemini 失敗、不配置 PostgreSQL、不提交、不推送、不部署。
9. 不保存憑證、完整環境變數、原始敏感 stderr 或不必要的歷史來源全文。

## 4. 修改範圍

| 檔案 | 允許修改的目的 |
|---|---|
| `src/valuation_engine/ai/codex_pit.py` | 有上限的程序生命週期、終止不明處理、對應 Ruff 修正 |
| `src/valuation_engine/ai/attempt_journal.py` | 完整且不可覆寫的收據發布、鎖與 journal 必要修補 |
| `src/valuation_engine/ai/service.py` | 僅在測試證明必要時，修正終止不明後停止 retry／stage 的行為 |
| `scripts/run_codex_pilot_v5.py` | 收據寫入策略及 import 排序 |
| `scripts/run_codex_validation_v5.py` | 收據寫入策略、保留可更新的進度檔及 import 排序 |
| `scripts/probe_codex_pit_launch.py` | 收據寫入策略 |
| 相關 `tests/` | 新功能與實際失敗行為的回歸測試；可新增專用測試檔 |
| 新修補報告與新日誌目錄 | 保存本次差異、命令與結果 |

不得直接對整個工作樹執行大範圍自動修正。其他檔案若有真正的相依問題，先列出原因與最小必要修改；不把無關整理混入本工單。

## 5. W1：移除終止不明後的無時限等待（P1）

### 問題與重現

`codex_pit.monitor()` 在 `with process as p:` 內執行有 timeout 的等待，但 Python 的 `Popen.__exit__()` 會在退出時再呼叫無 timeout 的 `wait()`。

審查使用本機假程序，將有 timeout 的等待模擬成 `TimeoutExpired`、將 kill 模擬成未成功終止，觀察到 `wait()` 的 timeout 參數依序為 `[2, 5, None]`。程式雖記錄 `termination_unconfirmed`，仍會等待子程序自行結束；若它不結束，runner 就無法返回。

### 實作要求

- 使用明確的程序與串流生命週期管理，避免 `Popen` context manager 在離開時加入隱藏的無限等待。
- 程序啟動後，各種正常、逾時、例外、日誌寫入失敗路徑都必須有有限的清理預算。保留既有 2 秒及追加 5 秒等待預算；不得另加無上限的 `wait()`、`communicate()`、join 或 busy loop。
- 啟動失敗記錄為 `process_launch_failure`，不偽造 PID、exit code 或推論開始。
- stage timeout 且終止已確認，記錄 timeout 與實際退出狀態。
- 終止仍不明時，回傳或拋出可辨識的終止不明結果，保留真實的未知 exit code，標記 journal／provider 狀態，保留鎖；後續 retry 與 stage 不得再啟動程序。
- 關閉外層持有的串流，不能透過隱藏的清理路徑重新無限等待。檢查 `call()` 的暫存封裝清理與此改動的相容性；子程序狀態未知時不得宣稱已安全終止或擴大內層權限。
- 保留 stdout／stderr hash 與 allowlisted 錯誤類型，不新增原始敏感輸出。

### 必要驗收

| 案例 | 必須觀察到的行為 |
|---|---|
| 正常假 CLI 完成 | 結構化結果與階段紀錄正確，已結束的程序可完成 attempt |
| 啟動失敗 | 沒有 inference_started；failure kind、未知 exit code 合理 |
| 假 CLI 逾時且 kill 成功 | 有限時間內返回 timeout，程序確實結束 |
| kill／wait 無法確認終止 | 有限時間內返回 unknown；保留 lock；沒有 `wait(timeout=None)` |
| 程序啟動後 journal 寫入失敗 | 仍走有上限的清理；終止不明就保留鎖 |
| unknown 後服務嘗試下一次呼叫 | 新的 subprocess 啟動次數不增加；不進入後續 stage |

未知終止案例使用測試替身；另至少有一個真正的本機假子程序 timeout 測試。測試本身要有外層 watchdog／有上限的等待，失敗時不得卡死 pytest，且必須清理自己建立的子程序。

## 6. W2：完成收據完整發布且拒絕覆寫（P2）

### 問題與重現

三支 runner 的 `save()` 都使用固定 `.tmp` 加 `replace()`。審查對同一個臨時 `pilot.json` 先寫 FAIL、再寫 PASS，第二次成功覆蓋，違反工程計畫的完成收據不可覆寫要求。

不能只把所有 `save()` 改成目前的 `AttemptJournal.write_once()`：它直接在最終路徑建立檔案並只呼叫一次 `os.write()`；失敗或短寫可能留下不完整 JSON。必須同時處理完整發布與禁止覆寫。

### 實作要求

- 共用一個明確的 immutable JSON writer，避免三支 runner 各維護一份略有差異的實作。
- 在同一目錄以唯一暫存檔完整寫入、flush／fsync，成功後才以**原子且不取代既有目標**的方式發布。可用同檔案系統的原子 hard-link 發布；採其他方式也須證明同等行為。
- 目標已存在時，明確失敗，保持既有 bytes 與 hash 不變；相同內容也不靜默覆寫。
- 不得使用 `exists()` 檢查後 `replace()` 的競態做法。處理短寫、寫入例外與發布失敗；不能將部分 JSON 當成最終收據。
- 檔案權限維持 `0600`；僅清理本次建立且尚未發布的暫存檔，不刪除其他 attempt 的產物。
- `manifest.json`、`provider-check.json`、每季 `context.json`、`preservation.json`、`pilot.json`、`probe.json`、`repeatability.json`、`validation.json` 使用完成後不可覆寫的寫入方式。
- `quarter-progress.json` 是會反覆更新的狀態檔，保留原子更新能力；不能把第二季更新誤判成覆寫完成收據。`progress.jsonl` 保持 append-only，兩者語意要分清楚。
- 不修改任何既有完成收據來遷移格式。

### 必要驗收

| 案例 | 必須觀察到的行為 |
|---|---|
| 第一次發布 | 最終檔為完整合法 JSON，權限符合要求 |
| 同一路徑第二次發布 | 拋出明確錯誤；原 FAIL 收據 bytes／hash 不變 |
| 兩個 writer 同時發布同一路徑 | 恰有一個成功；最終檔等於一份完整輸入，沒有混寫 |
| 短寫／寫入例外 | 完成全部寫入或明確失敗；不留下部分內容的最終收據 |
| 發布失敗 | 原收據不變；不刪除其他 writer 的暫存檔 |
| 多季進度更新 | `quarter-progress.json` 可更新，最終收據仍不可覆寫 |
| runner 串接 | 以替身執行相關寫入路徑，證明 runner 確實使用新 writer |

## 7. W3：補齊鎖與隔離入口的回歸測試（P2）

測試只操作 `tmp_path`／獨立測試 DB。至少覆蓋：

- 同一 attempts 目錄同時只有一個 journal 可取得 lock；第二個不得啟動 provider。
- 已存在的 unknown、內容無法解析或無法讀取的 lock 均不可自行覆蓋或解除。
- 成功／已確認終止的失敗只可解除自己的 lock；不得解除不同 attempt 的 lock。
- unknown 狀態完成記錄後仍保留 lock，下一次 attempt 被拒；原進度紀錄不可覆寫。
- C1–C12 完整且全部 PASS、policy/model/configuration 綁定正確時才可通過入口。
- gate 空集合、缺一項、多一項、任一非 PASS、policy/model 不符、設定 hash 前後不同，以及歷史資料曾送入隔離實驗，都拒絕。
- CLI 版本不符或版本查詢逾時，不得進入歷史輸入推論；以假 CLI／mock 驗證。
- 模擬敏感 stderr／例外訊息；收據只保留允許的分類與 hash，不包含測試的秘密字串。

以上測試不會重新證明真實 C1–C12 隔離有效；它們驗證的是入口程式在證據不足時會拒絕執行。

修正四個已知 Ruff 錯誤：兩支 V5 runner 與 `attempt_journal.py` 的 import 排序，以及 `codex_pit.py` 的 `raise ... from exc`／`from None` 例外鏈。不得改弱 lint 規則。

## 8. 執行順序與驗證命令

1. 讀取目前工作樹、上述計畫與程式，再於新的獨立目錄保存本次基線。不要覆寫 P0 原始基線；不要使用或解除實際 `active.lock`。
2. 先加入可重現 W1／W2 的針對性測試，保存修補前失敗證據；有 watchdog 的測試才可執行無限等待重現。
3. 完成最小修補，執行新測試及下列受影響測試。
4. 通過後執行一次完整 SQLite 回歸、Ruff、mypy、diff check。新的修改或失敗需要處理時，才再跑相應範圍。
5. 保存命令、退出碼、日誌及最終差異，交付報告；不要接著啟動真實 probe 或 Q2。

工作目錄固定為正式專案。以下命令刻意只選 SQLite；不要印出或自動沿用任何 PostgreSQL URL：

```sh
env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra tests/unit/test_codex_pit.py tests/unit/test_cli_provider.py tests/unit/test_ai_guards.py tests/unit/test_pit_pilot.py tests/unit/test_quarter_package.py tests/unit/test_prompts.py tests/integration/test_ai_analyst.py
env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src
git diff --check
```

第一條命令之外，另明確執行本次新增的測試檔；完整 pytest 也必須收集到它們。保存工具本身的 exit code，不可只取 `tee` 的成功碼。

## 9. 交付與通過標準

新增 `docs/M4_1_CODEX_V5_LUNA_FIX_REPORT.md`，至少包含：

- W1／W2 的修補前重現、根因、修補位置及修補後證據。
- W1–W3 各驗收案例對應的測試名稱與實跑結果。
- 本次基線與最終差異位置；區分既有 M4.1 修改與本工單新增修改。
- 所有測試命令、退出碼、passed／failed／skipped 數量與完整日誌位置。
- 實際 legacy lock 的修補前後 hash 比對，確認未改動；`sources/` 未修改的檢查結果。
- 明確列出本次沒有執行真實模型、PostgreSQL 或任何季度驗收。

測試日誌與新基線可放在 `data/m41/codex/reviews/luna-fix-<UTC時間>-<唯一ID>/`；不要使用正式 attempts 的共用鎖。測試產物不加入 Git 提交。

**本機修補可交付的必要條件：**

- W1–W3 新增與受影響測試全部通過。
- Ruff、mypy、diff check 全部通過。
- 完整 SQLite 無新增失敗或無理由新增 skip；若仍為前述兩項 Gemini 失敗，逐項保留並標示「完整回歸仍未通過」，不能寫成全綠。
- immutable 收據測試證明覆寫被拒，unknown 終止測試證明可有界返回且不再啟動程序。
- 既有資料、來源、legacy lock 與歷史收據維持原狀。

遇到新的無關失敗或並行修改衝突，保留證據並說明受影響範圍；不要擴大修正或偽造 PASS。若環境阻止某項本機測試，記錄確切錯誤，其餘不受影響工作繼續完成。

## 10. 給 Luna 的直接指令

> 請依這份工單在正式 StockOS checkout 完成 W1–W3 的程式修補、回歸測試與交付報告。保留既有 M4.1 修改，不解除 legacy lock，不呼叫真實模型，不執行 Q2 或其他季度，不改正式 DB，不提交或推送。請根據實際程式、測試與檔案證據工作，不採信舊報告為驗收結果。完成後提供修補檔案、新增測試、實跑結果、日誌位置與剩餘缺口；不要在交付前停下來等待舊模型程序狀態，因為本工單只要求可獨立進行的本機工作。
