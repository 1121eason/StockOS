# M4.1 Codex V5 R03 診斷修補交付報告

日期：2026-09-25。工作目錄：`/Users/eason/Documents/Coding/StockOS`。

最新接續狀態（2026-09-25T13:35Z）：直接接手後取得新程序查詢，診斷出 probe schema 缺少 boolean type；修正及回歸後的新真實 probe 已 PASS。見 [介入修復與驗證報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_R03_INTERVENTION_REPORT.md)。以下保留 Luna 原 D01–D05 交付時的結果，沒有改寫歷史 FAIL 或 unknown 原因。

## 原 D01–D05 結果摘要（截至 13:11Z）

- D01 診斷查核完成；歷史 R03 的 `-9` 終止來源仍是 **unknown**，原始 R03 **FAIL** 收據與日誌未修改。
- D02 診斷修補完成。首次 CLI 失敗、runner 終止要求、有界 wait、觀察到的退出碼及 hash 分欄保存；錯誤摘要有界並去敏。probe 的程序退出碼現在依不可覆寫收據 gate 決定。
- D03 受影響測試 75 passed；Ruff、mypy、`git diff --check` 通過。完整 SQLite 為 310 passed、2 項既有 Gemini 測試 failed、1 項 PostgreSQL 專用 skip；不宣稱全綠。
- D04 **BLOCKED，未啟動真實 Codex probe**。D03 後需要的新鮮完整程序查詢沒有回傳結果，不能證明啟動前程序閘門成立。沒有真實模型呼叫、沒有新 probe attempt、沒有正式 DB 寫入，也沒有執行 R04–R07。
- D05 完成本報告、執行 tracker 與 Q2 報告補記。未宣稱 probe PASS、Q2 PASS 或 M4.1 Final Pass。

本輪唯一 review 目錄為 [r03-diagnostic-20260925T123554Z-9b71c2f4](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4)。本輪開始基線 [baseline.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4/baseline.json)，SHA-256 `cfe6b416362f5d11f5b6c42c8466aaf2b016c6dd4b6abf5b956b248e0ddfc8f2`。

## D01：歷史失敗查核

歷史 attempt `20260925T121458Z-595e4dd8de81` 保持 FAIL。原有 lifecycle 顯示 CLI 子程序 PID 46401 在 `2026-09-25T12:15:01.880350Z` 以 `-9` 結束，程序當時已確認停止；這些欄位不能證明是誰或何種原因送出終止訊號。

唯讀系統日誌查詢只限 PID 46401、`12:14:30Z–12:15:30Z`，exit code 0、199 筆事件。保存的 [d01-system-diagnostics.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4/d01-system-diagnostics.json)，SHA-256 `e4b9a4abaf257be2a86058a21eab8c8c3808c3a88afda491f4f76c540afe0927`，沒有直接 SIGKILL、signal 9、crash、watchdog、OOM 或 sandbox-denial 關鍵字匹配。原始 unified log 未保存；只保存限定範圍的去敏摘要與 hash。

既有本機假 CLI 重現 [offline-reproduction.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-independent-review-20260925T122323Z-ab02795c/offline-reproduction.json)（SHA-256 `32dfab801291a00f7e738ddbaab6a3cccf829188bc563e51065bc7fb7d1a4136`）證明：`error`、`turn.failed` 後 runner 清理可導致 `-9`；子程序自行 SIGKILL 也會得到 `-9`，但 runner 沒送訊號；正常完成為 0。這些替身案例不能回推歷史 R03 根因，因此歷史原因繼續標為 unknown。

## D02：診斷修補

變更檔案：

- [codex_pit.py](/Users/eason/Documents/Coding/StockOS/src/valuation_engine/ai/codex_pit.py)：保存前 32 筆有界事件、事件總數與截斷標記；首次失敗另存事件種類、序號、接收時間、event hash、允許的錯誤碼／HTTP status 與最多 240 字去敏摘要。常見 bearer、API token、URL 與使用者 home 路徑先遮蔽。程序清理記錄送訊號前狀態、PID／PGID、SIGKILL、觸發原因、syscall 結果與因果歸屬 unknown；2 秒及 5 秒 wait 各自記錄結果。觀察到的 `-9` 不會自行產生 runner signal 紀錄。
- [probe_codex_pit_launch.py](/Users/eason/Documents/Coding/StockOS/scripts/probe_codex_pit_launch.py)：將診斷寫入不可覆寫 `diagnostics.json`，再把 sidecar 路徑與 bytes SHA-256 寫入 `probe.json`。只 gate PASS 回傳 0；FAIL、UNKNOWN 與診斷／probe 收據寫入錯誤回傳非零，並先執行 journal `finally` 清理。launch failure 的 `started_at`、觀察退出碼保持 null，請求時間另存 `launch_requested_at`。新增明確 `--launch-intent` 引用，AttemptJournal manifest 與 probe 收據均綁定其正規化路徑及 bytes hash。
- [test_codex_recovery.py](/Users/eason/Documents/Coding/StockOS/tests/unit/test_codex_recovery.py)：新增真實 monitor／call／probe 收據路徑的假 CLI 回歸與明確 launch-intent 綁定測試。

沒有改變 timeout／重試政策、隔離政策、模型、CLI 版本、prompt 或估值流程。沒有保存完整 prompt、環境、argv、原始 stdout／stderr 或未去敏錯誤訊息；stdout／stderr 只留 hash。

## D03：驗證

| 實際命令 | Exit code | 結果 | 日誌 |
|---|---:|---|---|
| `.venv/bin/pytest -q tests/unit/test_codex_recovery.py tests/unit/test_codex_pit.py` | 0 | 75 passed；含 error／turn.failed、child 自行 SIGKILL、正常成功、launch failure、timeout、unknown／保留鎖、去敏與截斷、診斷寫入失敗及 launch-intent 綁定 | `d03-affected-tests-post-intent-rerun1.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra` | 1 | 310 passed、2 failed、1 skipped | `d03-full-sqlite-post-intent.log` |
| `.venv/bin/ruff check src tests scripts` | 0 | All checks passed | `d03-ruff-post-intent.log` |
| `.venv/bin/mypy src` | 0 | 71 source files，無錯誤 | `d03-mypy-post-intent.log` |
| `git diff --check` | 0 | 通過 | `d03-diff-check-post-intent.log` |

完整 SQLite 的兩個失敗與先前完整回歸一致，且不是本輪修改的 Gemini 路徑：

- `tests/unit/test_gemini_provider.py::test_google_probe_and_isolation`：`_legacy_probe()["ready"]` 為 false；先前相同斷言結果見 `data/m41/codex/reviews/kernel-context-gates-20260925T004237Z-1268a18c/full-sqlite-pytest-final.log`。
- `tests/unit/test_gemini_provider.py::test_service_ineligibility_is_not_login_failure`：預期 `UNSUPPORTED_CLIENT`、實際為 `GOOGLE_LOGIN_PROBE_REQUIRED`；先前有相同結果。
- 唯一 skip 是 PostgreSQL 專用 `tests/integration/test_hardening.py` 案例；本輪沒有設定 PostgreSQL。

新增的 probe 跨層回歸名稱：

- `test_probe_persists_first_cli_error_and_runner_cleanup_without_secrets`（參數案例 `error`、`turn.failed`）
- `test_probe_success_returns_zero_and_binds_immutable_diagnostic_receipt`
- `test_probe_manifest_binds_explicit_launch_intent_bytes`
- `test_probe_launch_failure_returns_nonzero_without_invented_process_times`
- `test_probe_unknown_termination_returns_nonzero_and_keeps_lock`
- `test_probe_diagnostic_write_failure_returns_nonzero_after_journal_cleanup`
- `test_child_self_sigkill_has_no_fabricated_runner_signal`

並重跑既有 `test_normal_fake_cli_completes_and_journals_lifecycle`、`test_process_launch_failure_has_no_inference_or_fabricated_process_fields`、unknown-lock、bounded-timeout 與 `tests/unit/test_codex_pit.py` cases。回歸只使用 fake CLI 與臨時目錄；probe 測試的 AttemptJournal 與診斷收據寫入路徑是真實程式碼。

最終 D03 測試摘要 [d03-gate-summary.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4/d03-gate-summary.json)，SHA-256 `79417b812fe54abe45bf516b8c5bb8531c5c92b761e59086cbd3713eaef4d98b`。修補中的失敗測試、Ruff import-order 及 mypy 型別檢查迭代也都保留在 review 目錄的不同日誌，未覆寫。

## D04：真實 probe 閘門

D03 後未執行模型。一般沙箱的唯讀程序查詢回傳 `Operation not permitted`。在程式及測試全部完成後，透過正式 `require_escalated` 呼叫執行 fresh complete process check；該呼叫等待多次仍未回傳結果，且預期證據檔不存在。沒有把此狀態解讀為「沒有程序」，也沒有啟動 probe。較早的成功快照含 676 筆程序、0 匹配，但時間在 D03 最後一輪測試之前，不能替代所需的新鮮查詢。

阻礙證據 [d04-process-check-blocker.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4/d04-process-check-blocker.json)，SHA-256 `b276cc2f065684d71faa95131fd68ef26202b61b55e6360be54460ca9862fffb`。舊 P0 目錄經 [d04-p0-reconciliation.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4/d04-p0-reconciliation.json) 證實是 recovery baseline inventory、建立時無 V5 檔案，並非 Codex 執行 attempt；歷史 R03 progress 最後事件為 `finished/failed`。

**D04 BLOCKED。** D03 後程序狀態仍未由完整查詢確認。下一個具體動作是重新執行唯讀、受審核的完整 process inventory；只有查詢完整且無相關 runner／Codex exec／祖先或子程序、attempt 狀態已確認且 lock 條件符合時，才可建立新的不可覆寫 launch intent 並考慮唯一一次合成 probe。若查詢有匹配、缺漏或 UNKNOWN，停止，不啟動模型。

## 保全與執行邊界

執行前保全比對 [d04-prelaunch-preservation.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4/d04-prelaunch-preservation.json)，SHA-256 `257b2cbda94cd73162290c5da471aa470d28b01041189129b234a881985be3a0`：86/86 舊收據／日誌及 4/4 歷史 R03 artifact hash 相同；legacy `active.lock` 路徑不存在（依先前 R02）；其原備份仍是 inode `101962365`、mode `0600`、SHA-256 `17837b7e39ada147db7c124bdecf2812c1e401b5252dc1741aef7b98f3a9772a`。原始 R03 收據、日誌及 FAIL 分類均未改寫。

正式 SQLite DB 在本輪讀取 hash 仍為 `26da58b51178d3751758ad7637c52b71ba2209abf0b52298f13ef9b3f7780848`，與基線相同；本輪沒有正式 DB 寫入，沒有新增 run 或 snapshot。`sources/` 基線變更數為 0 且保持唯讀；保留 37 個未觸及的既有修改 hash。沒有執行 probe、R04、R05、R06、R07、PostgreSQL、commit 或 push。

本報告與兩份既有報告的補記追加於本輪後建立；歷史 E05/R03 FAIL 保留。新收據與日誌只位於上述唯一 review 目錄；此輪沒有新模型 probe 收據。
