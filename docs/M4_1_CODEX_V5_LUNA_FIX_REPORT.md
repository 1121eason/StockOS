# StockOS M4.1：Codex V5 Luna 修補交付報告

日期：2026-09-24  
執行 checkout：`/Users/eason/Documents/Coding/StockOS`  
範圍：M4.1 Codex V5 Recovery 工單 W1–W3；只做本機修補與 SQLite／替身測試。

## 結果摘要

- W1–W3 修補與新增回歸測試已完成。指定受影響測試為 **65 passed**；新增 recovery 測試獨立執行為 **43 passed**。
- 全套 SQLite 回歸為 **287 passed、2 failed、1 skipped**，因此「完整回歸仍未通過」。兩個失敗仍是工單列出的既有 Gemini 測試；本次沒有修改或略過它們。
- 全範圍 Ruff、mypy、`git diff --check` 均通過。
- 沒有呼叫真實模型、執行 PostgreSQL、啟動 Q2／季度 runner、寫入正式 DB、提交或推送。

## W1：終止不明時有限返回

### 修補前重現與根因

修補前測試以假 Popen 重現有限 `wait(2)`、`wait(5)` 後，Popen context manager 離開時仍呼叫無 timeout 的 `wait()`；測試因此明確失敗。另一個修補前案例重現 pilot FAIL 收據可被 PASS 覆寫。完整輸出見 `prepatch-w1-w2-reproduction.log`。

### 修補

`src/valuation_engine/ai/codex_pit.py` 改用明確的串流生命週期，不再呼叫 Popen context manager 的隱藏清理。程序清理最多等待 2 秒，超時後送出終止訊號，再最多等待 5 秒；所有已啟動程序的正常、timeout、monitor 例外與 journal 寫入失敗路徑均走有限清理。stdout／stderr 仍只留下 hash 與 allowlisted 錯誤類型。

若終止無法確認，結果標記 `termination_unconfirmed`，`exit_code` 保留 `null`，journal 標記 unknown 並保留 active lock。`call()` 不再移除或改成可寫未知程序可能仍使用的唯讀暫存工作目錄。服務遇到此狀態後不重試，也不進入後續 stage。啟動失敗記為 `process_launch_failure`，不寫 inference-started、PID、退出碼或程序開始時間。

| 驗收案例 | 回歸測試 | 結果 |
|---|---|---|
| 假 CLI 正常完成並記錄階段 | `test_normal_fake_cli_completes_and_journals_lifecycle` | 通過 |
| 啟動失敗不偽造程序資訊 | `test_process_launch_failure_has_no_inference_or_fabricated_process_fields` | 通過 |
| 真實本機假程序 timeout、有限返回且已回收 | `test_real_fake_process_timeout_is_bounded_and_reaped` | 通過；外層 12 秒 watchdog |
| kill／wait 不能確認，沒有無限 wait | `test_termination_unknown_never_calls_unbounded_wait`、`test_unknown_termination_supersedes_a_monitor_exception_with_explicit_status` | 通過；wait 僅為 2 秒、5 秒 |
| journal 寫入失敗後仍有限清理並保留 lock | `test_journal_write_failure_still_uses_bounded_process_cleanup` | 通過 |
| unknown 後不再啟動 subprocess、重試或後續 stage | `test_unknown_codex_termination_stops_retries_and_later_stages` | 通過；單次 extract、0 次 subprocess 啟動 |
| unknown 時保留唯讀 scratch | `test_call_retains_read_only_scratch_when_process_state_is_unknown` | 通過 |

## W2：完成收據完整發布且不可覆寫

`src/valuation_engine/ai/attempt_journal.py` 新增共用 `write_immutable_json()`：在目標目錄建立唯一暫存檔，使用完整寫入迴圈、`fsync` 與 mode `0600`，再以同檔案系統 hard-link 原子發布；目標已存在時由發布操作直接拒絕，沒有 exists／replace 競態。只清理本次建立的暫存檔。`AttemptJournal.write_once()`、pilot／validation／probe runner 的完成收據都走此函式。

validation 的 `quarter-progress.json` 改走獨立的 `write_json_atomic()`，仍可原子更新；`progress.jsonl` 保持 append-only，並採完整寫入迴圈。manifest、provider check、context、preservation、pilot、probe、repeatability、validation 均使用不可覆寫寫入。

| 驗收案例 | 回歸測試 | 結果 |
|---|---|---|
| 初次收據為完整 JSON、權限 `0600` | `test_attempt_manifest_is_complete_mode_0600_and_immutable` | 通過 |
| 第二次發布拒絕並保留原 bytes／hash | `test_immutable_json_rejects_second_publication_and_preserves_original_hash`、`test_pilot_save_refuses_to_overwrite_a_completed_receipt` | 通過 |
| 同路徑並行發布恰有一個成功 | `test_immutable_json_concurrent_publish_has_one_complete_winner` | 通過 |
| 短寫補齊；寫入例外不留下部分最終檔 | `test_immutable_json_writer_handles_short_writes_without_partial_final_file`、`test_immutable_json_write_failure_cleans_only_its_own_temporary` | 通過 |
| 發布失敗保留原收據與其他 writer 暫存檔 | `test_immutable_publish_failure_preserves_target_and_other_temporary` | 通過 |
| 多次季度進度更新 | `test_mutable_quarter_progress_remains_atomically_updatable` | 通過 |
| pilot／validation／probe 寫入路徑使用共用 writer | `test_v5_runners_route_completed_receipts_and_progress_to_distinct_writers` | 通過 |

## W3：lock 與隔離入口回歸

| 驗收案例 | 回歸測試 | 結果 |
|---|---|---|
| 併發 journal 只能一個取得 lock；pilot 第二入口在 provider 啟動前被拒 | `test_concurrent_attempt_journal_acquisition_has_exactly_one_winner`、`test_second_pilot_entry_is_blocked_before_provider_start` | 通過 |
| unknown、無法解析、不可讀 lock 不覆蓋 | `test_existing_unknown_or_unreadable_lock_is_never_replaced`（6 組參數） | 通過 |
| 完成／已確認失敗只解除自己的 lock | `test_finished_attempt_removes_only_its_own_lock` | 通過；不同 attempt lock 保留 |
| unknown finish 保留 lock 與既有 progress，拒絕下一次 attempt | `test_unknown_lock_finish_preserves_prior_progress_and_refuses_next_attempt`、`test_unknown_termination_keeps_legacy_style_lock_and_blocks_next_attempt` | 通過 |
| 僅接受精確 C1–C12、PASS、policy／model／設定一致且沒有歷史資料送入隔離實驗 | `test_exact_c1_c12_gate_passes`、`test_invalid_c1_c12_receipt_fails_closed`（11 組拒絕案例） | 通過 |
| CLI 版本不符或版本查詢逾時不進入歷史輸入推論 | `test_bad_or_timed_out_cli_version_never_enters_historical_inference`（2 組） | 通過 |
| stderr／例外中的秘密不進收據 | `test_sensitive_stderr_is_hashed_and_never_persisted`、`test_sensitive_version_exception_message_is_not_written_to_journal` | 通過；只存 hash／錯誤類型 |

本節證明入口在缺少有效證據時 fail-closed；不代表重新驗證真實 C1–C12 隔離有效。

## 正式 checkout 基線與保全

- 本次獨立基線：`data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/baseline-manifest.json`；HEAD `22e9b9ee944408cb67d5217ca66dd880498fb440`，branch `main`。基線收錄 35 個原有 dirty path 的狀態與檔案 hash，另保存 tracked patch。
- 相較本次基線，變更的是既有 dirty 檔案 `src/valuation_engine/ai/codex_pit.py`、`src/valuation_engine/ai/attempt_journal.py`、三支 V5 runner，以及 `tests/integration/test_ai_analyst.py`；新增 `tests/unit/test_codex_recovery.py` 和本報告。基線既有路徑沒有遺失。`service.py` 的既有修改保留；本工單的測試證明它已有 unknown 後停止 retry 的行為，因此沒有再改動該檔。
- Legacy `active.lock` 修補前與修補後 SHA-256 均為 `17837b7e39ada147db7c124bdecf2812c1e401b5252dc1741aef7b98f3a9772a`，mode `0600`；本次沒有讀取以外的操作，不曾解除或覆寫。
- `git status --porcelain -- sources` 為空；`sources/` 未修改。
- 以 SQLite read-only URI 檢查，最新 Codex run 仍是 run 13（FY2023-Q2、PromptSetV4、22 provider calls、1 snapshot），與工單建立前 P0 記錄一致。`data/qve.db` 檔案 mtime 早於本次基線；本次沒有呼叫會寫正式 DB 的 runner。單季歷史收據未被本次測試或腳本改寫。
- 基線與最終 tracked patch、狀態、hash 差異及唯讀 DB 查詢保存在本報告所列 review 目錄；該目錄位於 ignored `data/`，測試產物不加入 Git。

## 驗證命令與日誌

| 命令 | Exit code | 結果 | 完整日誌 |
|---|---:|---|---|
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra tests/unit/test_codex_pit.py tests/unit/test_cli_provider.py tests/unit/test_ai_guards.py tests/unit/test_pit_pilot.py tests/unit/test_quarter_package.py tests/unit/test_prompts.py tests/integration/test_ai_analyst.py` | 0 | 65 passed | `data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/affected-tests.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra tests/unit/test_codex_recovery.py` | 0 | 43 passed | `data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/new-recovery-tests.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra` | 1 | 287 passed、2 failed、1 skipped；完整回歸仍未通過 | `data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/full-sqlite-pytest.log` |
| `.venv/bin/ruff check src tests scripts` | 0 | All checks passed | `data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/ruff.log` |
| `.venv/bin/mypy src` | 0 | 71 source files，無錯誤 | `data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/mypy.log` |
| `git diff --check` | 0 | 通過 | `data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/diff-check.log` |

完整回歸兩項失敗：

- `tests/unit/test_gemini_provider.py::test_google_probe_and_isolation`
- `tests/unit/test_gemini_provider.py::test_service_ineligibility_is_not_login_failure`

此兩項與工單提供的既有失敗相同；沒有為清除它們而變更 Gemini 程式或測試。1 個 skip 是 `tests/integration/test_hardening.py` 中明確要求由獨立 PostgreSQL 驗證腳本執行的案例。

修補前的 W1／W2 重現日誌：`data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/prepatch-w1-w2-reproduction.log`。首次收集失敗（測試尚未載入 scripts namespace）的紀錄：`data/m41/codex/reviews/luna-fix-20260924T130328Z-c3d6253c/prepatch-w1-w2-tests.log`；測試載入方式已調整，正式重現日誌為前者。

## 執行邊界與剩餘驗收

沒有呼叫真實 Codex、Gemini 或其他模型；假 CLI／測試替身只使用合成輸入。沒有執行 PostgreSQL、Q2、七季、重跑比較、季度驗收或真實 probe，也沒有寫入 `data/qve.db`、改動歷史 run／snapshot／收據、解除 legacy lock、提交或推送。

本交付只表示 W1–W3 本機修補可供審查；完整 SQLite 仍有兩個已知 Gemini 失敗與一個 PostgreSQL 專用 skip。P1 真實合成呼叫、PostgreSQL、Q2、其餘季度、重跑比較與人工審查仍待各自驗收。

## 2026-09-25 追加：W1 啟動失敗跨層回歸修補

### 修補前證據與根因

新增的跨層測試以成功的假 CLI 版本檢查及 `Popen` 替身，分別拋出 `PermissionError`、`FileNotFoundError`。測試經由實際 `monitor()`、`call()`、`provider_request()`、`service.invoke()` 及 pytest 的臨時 SQLite 資料庫執行。修補前兩個案例均以 exit code 1 失敗：服務資料列的 `failure_kind` 是 `provider_unavailable`，而非 `process_launch_failure`。修補前重現命令與完整輸出保存在：

`/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/prepatch-cross-layer-launch-regression.log`

`monitor()` 的啟動失敗結果本來正確地不含 `started_at`，並保留 `launch_requested_at`、`exit_code: null`、空 stdout／stderr 的 hash 及 `launch_error_type`。回歸來自 `provider_request()` 在輸出日誌時直接索引 `result["started_at"]`；後續 execution metadata 又直接索引同一欄位，且欄位清單漏掉請求時間、stderr hash 和啟動錯誤類型。`service.invoke()` 捕捉到該 `KeyError` 後只剩空結果，將失敗設成通用的 `provider_unavailable`，並把服務呼叫時間填成 `started_at`。

### 修補與修補後證據

- `src/valuation_engine/ai/codex_pit.py`：程序日誌的 `started_at` 改以安全取值輸出；組裝 `execution_metadata` 時對所有 audit 欄位使用 `.get()`，保留 `launch_requested_at`、`stderr_hash`、`launch_error_type`，而未提供的 `started_at` 仍輸出為 `null`。啟動例外只保留 allowlisted 類型，不保存錯誤訊息。
- `src/valuation_engine/ai/service.py`：若 `failure_kind` 是 `process_launch_failure` 且 `started_at` 缺席，預設仍是 `None`；一般其他情況維持既有預設處理。`exit_code` 仍為未知的 `None`。沒有改動 `MAX_ATTEMPTS` 或 retry 分支。
- `tests/integration/test_ai_analyst.py`：新增 `test_codex_launch_failure_survives_provider_and_service_recording`，涵蓋 PermissionError 與 FileNotFoundError。每例驗證原有兩次呼叫上限、無 `inference_started`、AIProviderCall 保留失敗分類／錯誤類型／請求與完成時間／未知開始及退出時間，並精確比對空 stdout／stderr SHA-256。測試也確認合成敏感錯誤字串未進入資料列。這些呼叫使用臨時 SQLite 和替身，沒有啟動模型。

空 stdout 與 stderr 的預期 SHA-256 均為 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。修補後新增測試兩個參數案例皆通過；輸出日誌正常產生 `started_at: null`，錯誤未被 `KeyError` 路徑轉成通用分類。

### 本次驗證命令

| 命令 | Exit code | 結果 | 完整日誌 |
|---|---:|---|---|
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra tests/integration/test_ai_analyst.py -k codex_launch_failure_survives_provider_and_service_recording`（修補前） | 1 | 2 failed；兩種例外均證實被記為 `provider_unavailable` | `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/prepatch-cross-layer-launch-regression.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra tests/integration/test_ai_analyst.py -k codex_launch_failure_survives_provider_and_service_recording` | 0 | 2 passed、15 deselected（import 排序整理後重跑） | `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/regression-post-import-sort.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra tests/unit/test_codex_pit.py tests/unit/test_cli_provider.py tests/unit/test_ai_guards.py tests/unit/test_pit_pilot.py tests/unit/test_quarter_package.py tests/unit/test_prompts.py tests/integration/test_ai_analyst.py` | 0 | 67 passed | `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/affected-tests-final.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra` | 1 | 289 passed、2 failed、1 skipped；完整 SQLite 回歸仍未通過 | `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/full-sqlite-regression.log` |
| `.venv/bin/ruff check src tests scripts`（import 排序修正後） | 0 | All checks passed | `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/ruff-final.log` |
| `.venv/bin/mypy src` | 0 | 71 source files，無錯誤 | `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/mypy.log` |
| `git diff --check` | 0 | 通過 | `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/diff-check-final.log` |

完整回歸的兩個失敗仍是既有 Gemini 缺口：`tests/unit/test_gemini_provider.py::test_google_probe_and_isolation`、`tests/unit/test_gemini_provider.py::test_service_ineligibility_is_not_login_failure`；唯一 skip 是需獨立 PostgreSQL 驗證的 `tests/integration/test_hardening.py`。本次沒有修 Gemini，也不宣稱完整回歸全綠。Ruff 曾先因新增測試的 import 排序回傳 exit code 1；已調整排序，以上最終 Ruff 為通過結果。

### 保全與執行邊界

本次新基線及保全比對位於 `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/luna-launch-failure-20260924T142325Z-29e31fe4/`。工作樹在本次開始及結束時均為 37 個既有變更路徑，路徑集合一致；本次只在原已修改的 `codex_pit.py`、`service.py`、`test_ai_analyst.py` 加入這項修補與測試。保全結果見 `preservation-final.json`。

Legacy `data/m41/codex/attempts/active.lock` 前後 SHA-256 均為 `17837b7e39ada147db7c124bdecf2812c1e401b5252dc1741aef7b98f3a9772a`，mode `0600`；沒有解除或改寫。`git status --short -- sources/` 仍為空。上述 SQLite 測試明確取消 `QVE_TEST_POSTGRES_URL`，並使用 pytest `tmp_path` 的 `test.db`；沒有讀寫正式資料庫，也沒有執行 PostgreSQL、真實模型、probe、Q2 或其他季度，沒有提交或推送。既有報告、收據與日誌都保留，這次驗證寫入新的唯一 review 目錄。
