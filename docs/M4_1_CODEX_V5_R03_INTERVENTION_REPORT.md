# M4.1 V5 R03：直接接手修復與驗證

日期：2026-09-25。正式工作目錄：`/Users/eason/Documents/Coding/StockOS`。

**R03 修正後的真實合成 probe 已 PASS。** 新收據為 attempt `20260925T133432Z-943115f4f889`；CLI 與外層 runner 均 exit 0，程序確認停止，沒有 runner 終止要求，`active.lock` 已由該 attempt 正常解除。下一階段是 R04 原生隔離驗證；本輪沒有執行 R04–R07、Q2、PostgreSQL 或正式 DB 寫入。

## 1. 找到並修正的問題

原 probe 的 response schema 為 `"ok": {"const": true}`，缺少欄位型別。直接接手後的診斷 attempt `20260925T132437Z-aa3ef0ad88a2` 收到服務錯誤 `invalid_json_schema`，明確指出 `properties.ok` 必須有 `type`。隨後 runner 記錄 SIGKILL 要求與 syscall success，再觀察到 child exit -9；這是先有請求格式錯誤、再有程序清理的時間順序，不能把 -9 本身當成外部 OS 故障證據。

修正 [probe_codex_pit_launch.py](/Users/eason/Documents/Coding/StockOS/scripts/probe_codex_pit_launch.py:127)：將欄位改為 `"ok": {"type": "boolean", "const": true}`。其餘模型、CLI、transport policy、隔離設定、timeout、重試及 Q2 分析輸入均未變。[OpenAI Structured Outputs 文件](https://developers.openai.com/api/docs/guides/structured-outputs)列有 boolean 型別及具明確型別的欄位範例；本次實際拒絕原因另有真實 CLI 診斷支持。

新增 [schema CLI 回歸測試](/Users/eason/Documents/Coding/StockOS/tests/unit/test_codex_recovery.py:363)：假 CLI 讀取實際 `--output-schema` 檔案，對缺少 type 的欄位模擬 `invalid_json_schema`；走真實 monitor、call、probe、診斷與收據路徑。修補前 1 failed，修補後 1 passed。過去只回傳固定成功事件的替身未檢查輸出 schema，因此沒有攔住這個問題。

歷史 attempt `20260925T121458Z-595e4dd8de81` 的原始 FAIL 及 unknown 終止來源維持不變；新的診斷不能倒填歷史事件。

## 2. 實際執行與結果

本輪依使用者「直接介入把它修好」的要求，完成一次診斷，以及修正與本機回歸後的一次驗證；共兩次真實合成 attempt，各自有不同且不可覆寫的 launch intent。沒有新增程式自動重試或歷史資料輸入。

| 步驟 | 結果 | 證據 |
|---|---|---|
| 接手前保全 | Luna 34 份 manifest 項目 hash 相符；92 份保護檔建立基線 | `baseline.json` |
| 診斷前完整程序查詢 | 655 列，解析錯誤 0，相關程序 0；所有執行 attempt 終結，無 active lock | `process-preflight.json` |
| 診斷 probe | FAIL；`invalid_json_schema`，child -9，outer 1，confirmed_stopped | `diagnostic-result.json`；attempt `20260925T132437Z-aa3ef0ad88a2` |
| schema 修正與回歸 | 修補前重現失敗，修補後通過；受影響測試及靜態檢查通過 | `validation-final.json` |
| 驗證前完整程序查詢 | 638 列，解析錯誤 0，相關程序 0；只排除本次內嵌查詢 PID 與父程序，避免查詢字串自匹配；無 active/unknown attempt | `process-verification-preflight.json` |
| 修正後 probe | **PASS**；child 0、outer 0、confirmed_stopped、first_failure null、runner 終止要求為空 | `verification-result.json`；attempt `20260925T133432Z-943115f4f889` |

兩次 probe 的入口均為 `.venv/bin/python -u scripts/probe_codex_pit_launch.py --launch-intent <該次 intent 的絕對路徑>`，透過正式 `require_escalated` 機制執行。分別使用本 review 目錄的 `launch-intent.json`、`verification-launch-intent.json`。核對了診斷 sidecar 與 launch intent 的實際 bytes SHA-256，而非只查看 PASS 字樣。

一次檔案式程序查詢及可選的本機環境 SQLite 測試未取得工具回覆；相關工具 cell 已取消，沒有將取消訊息當作 OS exit code，也沒有宣稱額外測試通過。之後改以受審核、內嵌且有 15 秒上限的唯讀查詢取得完整程序證據，再進入修正後 probe。原始 argv 僅在記憶體比對及計算 hash，沒有保存或輸出。

## 3. 測試與剩餘限制

| 命令／檢查 | 結果 |
|---|---|
| 新 schema 回歸，修補前 | 1 failed，exit 1；`schema-regression-before.log` |
| 新 schema 回歸，修補後 | 1 passed，exit 0；`schema-regression-after.log` |
| `.venv/bin/pytest -q tests/unit/test_codex_recovery.py tests/unit/test_codex_pit.py` | **76 passed，exit 0** |
| 移除測試環境的 `QVE_TEST_POSTGRES_URL` 後，`.venv/bin/pytest -q -ra` | **311 passed、2 failed、1 skipped，exit 1** |
| `.venv/bin/ruff check src tests scripts` | exit 0 |
| `.venv/bin/mypy src` | 71 source files，exit 0 |
| `git diff --check` | exit 0 |

兩個完整 SQLite 失敗仍為 `test_google_probe_and_isolation`、`test_service_ineligibility_is_not_login_failure`，斷言與接手前記錄一致；本輪沒有修改 Gemini 程式或測試，也沒有確定其失敗原因。唯一 skip 是 PostgreSQL 專用案例。完整回歸仍未全綠，不能因 R03 PASS 而宣稱正式測試或 M4.1 通過。

## 4. 保全與現在的位置

- 86 份舊收據、歷史 R03 的 4 份 artifacts、legacy lock 備份及正式 SQLite DB，共 92 份保護檔 hash 相符；本輪新診斷 FAIL 也保留原始收據。
- legacy lock 備份仍為 inode `101962365`，SHA-256 `17837b7e39ada147db7c124bdecf2812c1e401b5252dc1741aef7b98f3a9772a`；active lock 不存在。
- 正式 AI run 仍為 13、snapshot 仍為 2、provider calls 仍為 118；沒有新增正式 AI 紀錄。
- HEAD 與既有其他程式修改保留，`sources/` 未變；沒有 commit／push。
- R03 已有新的 PASS。R04 尚未執行，R05–R07 仍需新的 native kernel／隔離收據及既有輸入閘門；本輪不啟動後續流程。

交付證據目錄：[r03-intervention-20260925T132255Z-eedd08b4](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-intervention-20260925T132255Z-eedd08b4)。

成功收據：[probe.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T133432Z-943115f4f889/probe.json)。
