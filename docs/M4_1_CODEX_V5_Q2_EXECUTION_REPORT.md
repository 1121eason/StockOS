# StockOS M4.1 Codex V5：FY2023-Q2 執行報告

日期：2026-09-25

Checkout：`/Users/eason/Documents/Coding/StockOS`

最新進展（2026-09-27T09:18:04Z；Brisbane 19:18:04）：**R09 同條件比較 2／2 完成、R10 待填卡 35／35 已生成，獨立 DB 複核 PASS；真人 0／35，M4.1 未結案。** 唯一 attempt `20260927T081514Z-8a8c675a0951` 正常結束，Q2 新 run 24／snapshot 11（22／22 valid）、Q3 新 run 25／snapshot 12（15／15 valid）；兩季共 933 evidence、32 有值特徵、16 challenges、19 direction_unsupported 隔離候選。兩季均匹配原 V1 budget、固定 context 與 extract request hashes，37 次呼叫零重試；actual model 未由 CLI 暴露，仍為 requested_only。989 份歷史檔案、十張保護表及十二張 AI／建議表既有 rows 不變，active.lock 正常解除，process_state_unknown=false。

比較完成不代表語義穩定：Q2 有值特徵由 27 降至 17，新增 10 項缺漏；competition_outlook -0.20 → +0.10。Q3 有值特徵 16 → 15，新增兩項缺漏及一項有值。共同方向一致率分別 16／17（94.12%）與 14／14（100%），引用 Jaccard 83.30%／82.78%，都不能代替真人判定。已提供 14 個差異與 350 個原文引用的複核索引；35 張卡仍綁定原核准前五季、所有人工欄位待填。

本輪新增重跑／產卡入口及 33 項測試，隔離受影響 206 passed；正式 SQLite 417 passed、0 failed、1 PostgreSQL-only skipped，Ruff、mypy 71 files、diff check 通過。未修改 src/、schema、Gemini 程式／測試，PostgreSQL 本輪未重跑，前輪 350 passed 保留版本範圍。詳見 [重跑與審查報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_REPEATABILITY_REVIEW_REPORT.md)及 [人工審查入口](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review/REVIEW_GUIDE.md)。下一步 R13 真人核對內容及差異，R14 尚未結案。

前輪接續（2026-09-27T07:51:08Z）：**七季 7／7 PASS，四季接續及獨立 DB 複核均 PASS。** 唯一新 attempt `20260927T051436Z-0ec2cf068d62` 於 07:51:08Z 正常完成，新 FY2024-Q2、FY2025-Q4、FY2026-Q1、FY2027-Q2 對應 run 20–23／snapshot 7–10，90／90 valid calls、2,496 evidence、80 有值特徵、29 challenges；24 項不支持方向的候選隔離保留。原 Q2 run 15／snapshot 4、Q3 run 17／snapshot 5、FY2024-Q1 run 18／snapshot 6 已重核保留。923 份歷史 artifacts、十張保護表及十二張 AI／建議表既有 rows 不變，active.lock 已正常解除、process_state_unknown=false。

本輪一般化 V2 執行 budget 與明確接續入口先經隔離測試再正式套用；SQLite 384 passed／0 failed／1 PostgreSQL-only skipped，Ruff、mypy 71 files、diff check 通過。PostgreSQL 本輪未重跑，前輪 350 passed 收據保留。新四季的 extract 上限明確為 600 秒、兩次嘗試上限不變；call 286 在 217.45 秒有效完成。PromptSetV6、model 要求、分批、schema、來源及 PIT 限制未改；舊 Q2／Q3／FY2024-Q1 保留 V1 執行 profile。R09 重跑比較 0／2、真人 0／35，M4.1 尚未結案。詳見 [V6 時限修補與接續報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_BUDGET_RESUME_REPORT.md)。前輪 FY2024-Q2 run 19 兩次 180 秒逾時、Q3 run 16 用量上限 FAIL 及以下所有歷史結果保持原紀錄，舊 R03 unknown 根因沒有倒填。

前輪 Q2 結果（2026-09-26T03:54:23Z；Brisbane 2026-09-26 13:54:23）：**PromptSetV6 引用對齊修補及新 Q2／獨立複核 PASS。正式新增 run 15／snapshot 4，22／22 呼叫有效，有值特徵由 6／28 提升至 27／28，跨 topic 拒絕由 21 降為 0。** 唯一缺漏為無同主題證據的 `switching_cost_strength`。十張保護表、十二張 AI／建議表的既有 rows、156 份歷史 artifacts 均未變，目前無 active lock。受影響測試 125 passed；完整 SQLite 319 passed、兩項既有 Gemini failed、1 skipped；PostgreSQL 未執行。詳見 [V6 修補及驗證報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_TOPIC_ALIGNMENT_REPORT.md)。其餘六季與重跑比較尚未執行，未宣稱 M4.1 Final Pass。前輪 [R04–R07 執行報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_R04_R07_EXECUTION_REPORT.md)及以下各輪歷史結果保留，不改寫原始 R03 FAIL 或 unknown 原因。

## 前次本機修補摘要（本輪前）

- 修正 Q2 runner，要求呼叫者明確提供 isolation 與 native kernel 收據路徑；記錄每份收據的 SHA-256，並在推論前重新驗證檔案未變。
- 新增核准輸入閘門，精確比較 FY2023-Q2、cutoff、來源 ID、package version/count/hash、policy、prompt、schema 與 model。任何不符都保存 expected／actual 並在模型請求前停止。
- 隔離 runner 改用共用 `active.lock`、唯一 AttemptJournal 目錄及不可覆寫收據；不再寫入固定的 `experiment-v3.json` 或 `kernel-shell-v4.json`。
- 本輪補修加入 kernel receipt bytes/path 綁定及已核准 context 實際傳入 service 的回歸。受影響測試 **123 passed**；完整 SQLite 回歸 **302 passed、2 項既有 Gemini 測試失敗、1 skipped**。Ruff、mypy、`git diff --check` 均通過。
- **未執行** Codex discovery、真實合成 probe、隔離重測或正式 Q2。舊 V5 請求是否仍在執行無法確認；`active.lock` 保留。
- 舊 isolation receipt 的 C1–C12 欄位雖記為 PASS，native kernel probes 也有具體拒絕結果，但 receipt 沒有綁定 discovery receipt；此外目前設定檔 hash 與舊 isolation 時的 hash 不同。現有證據不符合本輪的 live C1–C12 放行條件。
- Q2 狀態為 **BLOCKED**；沒有新 run／snapshot。唯讀檢查仍顯示最新 Codex Q2 為 run 13、snapshot 2。沒有宣稱 M4.1 Final Pass。

## 1. 舊執行狀態與 legacy lock

### 已保存的基線

初始封存位於：

`data/m41/codex/reviews/q2-next-20260924T223918Z-839c6d66/initial-state.json`

基線記錄 HEAD `22e9b9ee944408cb67d5217ca66dd880498fb440`、branch `main`、既有 Git 狀態、86 個既有收據／日誌的路徑與 hash、SQLite 最新 run 摘要，以及 legacy lock 的基線 hash `17837b7e39ada147db7c124bdecf2812c1e401b5252dc1741aef7b98f3a9772a`。

前版報告錯把審查任務 `01a0d2e9-7830-7ad1-b50d-f7a0f33d7010` 當作舊 V5 執行任務。本輪已依原始 rollout 更正：舊 V5 執行任務是 `01a0d1ad-8e32-7100-a23c-6e0133e244c0`，完整對帳見本報告第 8 節及 `original-v5-process-audit.json`。兩個 Codex 執行 cell 被取消，不構成 OS 子程序已退出的證據。

### 程序與部分產物核對

- 一般唯讀程序查詢遭 `PermissionError`，完整清單未取得。
- 受審核唯讀完整清單回傳 exit code 0，共 674 列；其中有一列 `codex`：PID 24707、PPID 24682、狀態 `S`、elapsed `10-13:29:44`。為避免保存完整命令列，僅保存 command SHA-256 `8eb8c47db53fc12f7160283383db3bbd199338a3030793d1280681c50df21b50`。這列無法與舊 V5 請求建立關聯；後續父子樹查詢未返回結果，我取消的是自己的唯讀查詢，沒有送出任何程序訊號。
- `data/m41/codex/attempts/` 中除 `active.lock` 外，只有既有 P0 manifest、tracked diff 與 untracked-files 清單；未發現本輪新增 attempt。清單及 hash 見 `attempts-partial-inventory.json`。沒有收據或 DB 新 run 不是程序終止證據。
- SQLite 唯讀快照在初始與最終檢查均為最新 run 13：FY2023-Q2、PromptSetV4、20 筆 extract、1 筆 synthesize、1 筆 challenge，snapshot 2。此結果不排除仍有未完成的外部程序。

### Lock 決策

`data/m41/codex/attempts/active.lock` 仍存在，大小 532 bytes、mode `0600`，大小與 mode 與基線相同。本輪只計算 hash，沒有輸出或解析 lock 內容，也沒有解除、改寫或試跑；沒有建立復原紀錄或保存 lock 內容副本。由於未取得舊請求明確終止證據，依停止條件保留 lock，並停止所有 Codex 啟動。

程序摘要證據：`data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/process-status-evidence.json`

Lock 外的 attempts 清單：`data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/attempts-partial-inventory.json`

## 2. 本輪程式差異與本機驗證

### 程式差異

- `scripts/run_codex_pilot_v5.py`
  - 新增必填 `--isolation-receipt` 與 `--kernel-receipt`，不再以固定檔名或最新檔案猜測收據。
  - 封存明確路徑與 bytes SHA-256；檢查 C1–C12、A–G 合成案例、原生檔案／repository／write／network probes、CLI／policy 指紋與隔離暫存目錄證據。
  - Q2 呼叫前重算 PIT package，核對下列核准值。來源 ID 以數字排序，避免把 9 排在 10、107、108 之後造成假漂移。
  - 核准輸入、已保存 discovery、目前 CLI discovery、有效 feature flags、設定檔 hash 及收據 bytes hash 必須全部通過，才會執行 `analyze(..., refresh=True)`。
  - mismatch 收據保存 expected／actual；沒有自動更新核准值。
- `scripts/run_codex_pit_v3.py`
  - 必須明確提供 `--kernel-receipt`；透過共用 attempts 目錄互斥。
  - discovery、每一個合成案例及最後 isolation receipt 寫入唯一 AttemptJournal 目錄；完成收據採不可覆寫發布，並把 discovery receipt 的路徑與 hash 綁進 isolation receipt。
  - 不再覆寫歷史 `experiment-v3.json`、`kernel-shell-v4.json` 或固定的 discovery 檔。
- `tests/unit/test_codex_recovery.py`
  - 新增漂移拒絕、失效 isolation 證據拒絕、明確收據參數，以及 isolation runner 共用鎖的測試；更新既有「第二入口先被 lock 阻擋」測試。

已保存的 FY2023-Q2 context fixture 經新輸入檢查，全部符合核准值：

| 欄位 | 實際值 |
|---|---|
| Quarter／cutoff | `FY2023-Q2`／`2022-08-25T13:30:00+00:00` |
| Source IDs／source count | `9, 10, 107, 108`／4 |
| Package／blocks／hash | `PITQuarterPackageV1`／932／`331e90ebd3ca261c06cf090a5d46ae852a4ded7eb133c434e5f7537abd3ff4c5` |
| Policy／prompt／schema | `AIAnalystPolicyV3`／`PromptSetV5`／`FeatureSchemaV2` |
| Requested model | `gpt-6-astra` |

核准值 fixture 檢查為純本機資料驗證，未呼叫模型或寫入 DB。日誌：`data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/approved-input-check.log`。

### 測試與靜態檢查

| 命令 | Exit code | 結果 | 日誌 |
|---|---:|---|---|
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra tests/unit/test_codex_pit.py tests/unit/test_cli_provider.py tests/unit/test_ai_guards.py tests/unit/test_pit_pilot.py tests/unit/test_quarter_package.py tests/unit/test_prompts.py tests/unit/test_codex_recovery.py tests/integration/test_ai_analyst.py` | 0 | 114 passed | `data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/affected-tests-last.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra` | 0 | 295 passed、1 skipped、0 failed | `data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/full-sqlite-pytest-last.log` |
| `.venv/bin/ruff check src tests scripts` | 0 | All checks passed | `data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/ruff-last.log` |
| `.venv/bin/mypy src` | 0 | 71 source files，無錯誤 | `data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/mypy-last.log` |
| `git diff --check` | 0 | 通過 | `data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/diff-check-final-report.log` |

新增案例名稱：

- `test_q2_input_drift_is_reported_and_stops_before_model_callback`
- `test_invalid_isolation_evidence_stops_before_model_callback`
- `test_q2_runner_requires_explicit_isolation_and_kernel_receipts`
- `test_isolation_runner_uses_explicit_kernel_and_shared_active_lock`
- `test_second_pilot_entry_is_blocked_before_provider_start`

完整測試有一個預期 PostgreSQL 專用 skip：`tests/integration/test_hardening.py` 由獨立 PostgreSQL 驗證腳本執行；本輪依界線未設定 PostgreSQL。先前記錄的兩項 Gemini 失敗本次沒有重現；本輪沒有修改 Gemini 程式、測試或 skip。

## 3. 真實合成 probe

**BLOCKED／未執行。** 沒有呼叫真實 Codex CLI，沒有啟動 `scripts/probe_codex_pit_launch.py`，沒有 probe attempt、`probe.json`、完整生命週期或外層執行權限收據。本輪不把本機替身測試當作真實 probe PASS。阻擋原因是舊程序狀態未明且 legacy lock 仍在。

## 4. C1–C12 有效性與收據綁定

既有歷史收據 hash：

- `experiment-v3.json`: `01f37c7ddbd3a8407938c9440698f8ef3e3badb6d117ede39b7de04aad935fae`
- `kernel-shell-v4.json`: `d5cf35fb23af6c40484a9c6071004fbb57407fe2f1ccdb825ce243ed00393a26`
- 分開保存的 `discovery-final-v3.json`: `b5a559487e4f7da67f299f3c68579cc7940df45f9632292db396a4b1fb1c377d`

前兩份歷史收據顯示 C1–C12 與 native probe 均為 PASS；四項 kernel probe 有 denial class、非零 exit code、marker／寫入結果及 stdout／stderr hash。舊 discovery 收據另記錄 ChatGPT 登入、CLI `codex-cli 0.155.0-alpha.9.2`、required flags、feature flags 與 `PIT_PROBES_REQUIRED`。但 isolation receipt 未以路徑與 hash 綁定這份 discovery 收據，所以新版 runner 對舊 isolation 證據回報 FAIL：`isolation_discovery_receipt_missing_or_hash_mismatch`、`saved_discovery_receipt_invalid`。不從目錄中自行挑選或補接舊 discovery 檔。

目前 `~/.codex/config.toml` 的 bytes hash 為 `d8e45fca9654a06f0d8edb14903b4d6d42ddc455f4f5688515bb34c4a99d449e`；舊 isolation 收據記錄的前後 hash 為 `469762b4369ea88fab3ed4ee299886e5dec8999081d891f5b847088da7fe1b29`。兩者不同，必須產生新的合成 isolation 收據。此 hash 比對不讀取或輸出設定檔內容。由於程序狀態仍不明，本輪沒有執行 live CLI discovery／feature list，也沒有重新探測 C1–C12。

| Gate | 舊收據中的證據 | 本輪有效狀態 |
|---|---|---|
| C1 | 舊 discovery 記錄 `authenticated=true` | BLOCKED；未做 live discovery，且舊 discovery 未由 isolation receipt 綁定 |
| C2 | 舊 A–G cases 記錄 turn completion | BLOCKED；未重跑真實合成 cases |
| C3 | 舊案例有 `{"answer":"unavailable"}` | BLOCKED；未重跑真實合成 cases |
| C4 | native file／write probe 有拒絕、marker／寫入結果與 hash | BLOCKED；證據屬舊設定，未建立新收據 |
| C5 | native network probe 拒絕，舊合成案例通過 | BLOCKED；未建立新收據 |
| C6 | 舊 discovery 的 browser flags 為 false | BLOCKED；目前有效 flags 未做 live 核對 |
| C7 | 舊 discovery 的 apps／MCP／plugins flags 為 false | BLOCKED；目前有效 flags 未做 live 核對 |
| C8 | native file／repository probe 記錄拒絕 | BLOCKED；未建立新收據 |
| C9 | 舊 cases escalation counters 為 0 | BLOCKED；未重跑新 cases |
| C10 | 舊 isolation gate 記為 PASS，A–G 有 hash 與 completion | BLOCKED；不能以歷史 gate 代替新收據 |
| C11 | 舊 isolation gate 記為 PASS，未送入歷史資料 | BLOCKED；不能以歷史 gate 代替新收據 |
| C12 | 舊 isolation 執行期間 config 前後 hash 相同 | BLOCKED；目前 config hash 不同 |

舊 discovery 記錄中的 `unified_exec` 值為 `true`；既有 `discovery()` 契約將它排除於必須 false 的 feature 檢查之外。其他列出的隔離 flags 在舊收據中為預期值。本輪未改寫此歷史值，也未作 live 驗證。

完整歷史證據檢查：`data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/historical-evidence-evaluation.json`。

## 5. FY2023-Q2 正式驗收

**BLOCKED；沒有開始。** 沒有建立新的正式 attempt，沒有執行 `refresh=True`，沒有新增 `AIAnalysisRun`、provider calls、snapshot、拒絕分類或季度判定。

| 欄位 | 本輪結果 |
|---|---|
| 新 run ID | 無；DB 產生的 run ID 未建立 |
| 新 snapshot ID | 無 |
| 最新既有 run／snapshot | run 13／snapshot 2，PromptSetV4 |
| 阻擋 | 舊 V5 程序終止未確認；lock 保留；舊 isolation 收據缺少已綁定 discovery receipt；目前 config hash 與舊值不同 |
| 十張保護表前後比對 | 未執行，因 Q2 未開始；沒有以未執行的比對宣稱資料保全 PASS |

最終唯讀 DB、lock、receipt inventory、Git 與 `sources/` 狀態保存於 `data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/postflight-last.json`。86 個基線既有收據／日誌均仍存在且 hash 未變；`sources/` Git 狀態為空。最新 DB 摘要仍為 run 13／snapshot 2。

## 6. 新收據與日誌

本輪 review 目錄：

`data/m41/codex/reviews/q2-execution-20260924T225425Z-3a7dbb86/`

含初始／最終狀態、程序狀態與 attempts 清單、核准輸入檢查、歷史 isolation 評估，以及 affected tests、完整 SQLite、Ruff、mypy、`git diff --check` 日誌。所有 review 證據使用新檔名；86 份基線收據與歷史 log 未覆寫。

## 7. 尚未完成的驗收

1. 取得可明確關聯舊 V5 請求的程序／子程序終止證據。確認前保留 `active.lock`，不可啟動下一階段。
2. 取得終止證據後，依既有 recovery 流程保存 lock 原文與 hash，再由 lock 所有權流程解除；本輪沒有做這些動作。
3. 以新的唯一 attempt 執行真實合成 Codex probe，保存外層權限、程序生命週期、退出狀態、stdout／stderr hash 與 `probe.json`；FAIL 或 unknown 即停止並保留 lock。
4. Probe PASS 後，重跑／核對 C1–C12，使用有 discovery receipt hash 的新 isolation 收據，並核對 live CLI、transport policy、有效設定及 config hash。
5. 全部 gate 通過後，只執行一次 FY2023-Q2，保存 DB 產生的 run ID、snapshot、呼叫／拒絕／季度判定與十張保護表前後 hash。無論 PASS 或 FAIL 都停止本輪。
6. 其他六季、重跑比較、人工審查與 M4.1 Final Pass 均未執行。

本輪沒有設定 PostgreSQL、呼叫模型、執行 Q2／其他季度、寫入正式 DB、修改 `sources/`、提交、推送或部署。

## 8. 2026-09-25 kernel/context 閘門補修與原始程序對帳

本節更新第 2 節的程式與測試結果。固定的 Q2 核准值未變；本輪只使用替身和臨時 SQLite，沒有執行 Codex、probe、Q2 或正式 DB 寫入。

### 修補內容

- `scripts/run_codex_pilot_v5.py` 現在要求 isolation receipt 宣告 `kernel_receipt`。驗證會比對宣告路徑與本次 `--kernel-receipt` 正規化後的絕對路徑、宣告 hash 與明確收據 hash，並重新讀取該路徑的 bytes 計算 SHA-256。缺漏、格式錯誤、路徑不符、hash 不符、收據讀取失敗或讀取後 bytes 改變，都會寫入 `isolation-check.json` 的具體 blocker，並在建立 provider 前停止。
- `scripts/run_codex_pit_v3.py` 產生的 isolation receipt 綁定明確 kernel receipt 的路徑與 SHA-256；新增替身測試確認輸出收據保留該 reference。另修正成功輸出時把 `flush=True` 傳給 `json.dumps()` 的錯誤，讓完成的替身執行可正常結束。
- `src/valuation_engine/ai/service.py` 的 `analyze()` 可接收 `prepared_context` 與其 SHA-256。傳入時 service 驗證實際 context hash 後直接使用該 context，不再呼叫 `prepare()`；未傳入時維持舊呼叫方式。context hash 不符會在建立分析 run 或呼叫 provider 前拒絕。
- V5 runner 記錄核准 context hash，並透過 `analyze_approved_context()` 把相同 context 和 hash 傳給 service。保存的 `context.json`、`AIAnalysisRun.context_json` 及替身 provider 收到的 package context 在回歸中逐一比對。
- `tests/unit/test_codex_recovery.py` 與 `tests/integration/test_ai_analyst.py` 增加本輪回歸；測試中的 Codex provider、隔離呼叫及 SQLite 均為替身／臨時資料。

固定 Q2 要求仍為 FY2023-Q2、`2022-08-25T13:30:00+00:00`、來源 ID `9, 10, 107, 108`、`PITQuarterPackageV1`、4 個來源、932 blocks、package hash `331e90ebd3ca261c06cf090a5d46ae852a4ded7eb133c434e5f7537abd3ff4c5`、`AIAnalystPolicyV3`／`PromptSetV5`／`FeatureSchemaV2`、`gpt-6-astra`。本輪沒有更新核准值。

### 修補前重現

| 缺口 | 修補前證據 | 結果 |
|---|---|---|
| isolation 未宣告 kernel receipt | `prepatch-kernel-reproduction-valid.log` 呼叫舊 `verify_saved_isolation()` | `PASS`，無 blocker |
| isolation 改宣告另一份 kernel receipt | 同上 | `PASS`，無 blocker |
| runner 核准後資料重備 | `prepatch-context-reproduction.log` 使用臨時 SQLite 與假 provider | runner 核准 package hash `737edb70…414276`；service 再 prepare 後 package hash `892912a2…140e4`，假 provider 與保存 context 都收到漂移後 package；建立了合成 snapshot |

### 本輪測試與靜態檢查

| 命令 | Exit code | 結果 | 日誌 |
|---|---:|---|---|
| `.venv/bin/pytest -q tests/unit/test_codex_recovery.py -k 'saved_isolation_accepts_normalized_matching_kernel_receipt or kernel_receipt_binding_failure or isolation_runner_records_the_explicit_kernel_receipt'` | 0 | 7 passed；含缺漏、格式錯誤、路徑不符、hash 不符、bytes 變動；所有失敗路徑 provider 啟動／模型呼叫數為 0 | `kernel-binding-targeted-delivery.log` |
| `.venv/bin/pytest -q tests/integration/test_ai_analyst.py -k 'approved_runner_context_is_the_only_context_sent_to_provider or mutated_approved_package_is_rejected_before_provider_call'` | 0 | 2 passed；來源新增後只送出核准 context；核准後 package 變更在 provider 前拒絕 | `context-binding-targeted-delivery.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra tests/unit/test_codex_pit.py tests/unit/test_cli_provider.py tests/unit/test_ai_guards.py tests/unit/test_pit_pilot.py tests/unit/test_quarter_package.py tests/unit/test_prompts.py tests/unit/test_codex_recovery.py tests/integration/test_ai_analyst.py` | 0 | 123 passed | `affected-tests-delivery.log` |
| `env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra` | 1 | 302 passed、2 failed、1 skipped。失敗是既有 Gemini 測試 `test_google_probe_and_isolation` 與 `test_service_ineligibility_is_not_login_failure`；未修改 Gemini 程式／測試，也未新增 skip／xfail。唯一 skip 是 PostgreSQL 專用 `tests/integration/test_hardening.py` 案例 | `full-sqlite-delivery.log` |
| `.venv/bin/ruff check src tests scripts` | 0 | All checks passed | `ruff-delivery.log` |
| `.venv/bin/mypy src` | 0 | 71 source files，無錯誤 | `mypy-delivery.log` |
| `git diff --check` | 0 | 通過 | `diff-check-delivery-final-final.log` |

失敗詳情：`test_google_probe_and_isolation` 的 `_legacy_probe()["ready"]` 實際為 false；`test_service_ineligibility_is_not_login_failure` 預期 `UNSUPPORTED_CLIENT`，實際為 `GOOGLE_LOGIN_PROBE_REQUIRED`。完整輸出保留在 `full-sqlite-delivery.log`。因此完整 SQLite 回歸不是全綠。

新增測試名稱：

- `test_saved_isolation_accepts_normalized_matching_kernel_receipt`
- `test_kernel_receipt_binding_failure_stops_before_model_callback`（5 種損壞情況）
- `test_isolation_runner_records_the_explicit_kernel_receipt`
- `test_approved_runner_context_is_the_only_context_sent_to_provider`
- `test_mutated_approved_package_is_rejected_before_provider_call`

### 原始 V5 程序對帳更正

原始 rollout：`/Users/eason/.codex/sessions/2026/09/24/rollout-2026-09-24T14-30-07-01a0d1ad-8e32-7100-a23c-6e0133e244c0.jsonl`，SHA-256 `d4dee0780e70543adef2524f8a30cbeffca9b4e5b1d2232a4311e25c0331ae0c`。

- cell 220 在 ordinal 1524 呼叫 `.venv/bin/python scripts/run_codex_pilot_v5.py`，並要求 `require_escalated`。之後 rollout 多次回報 `Script running with cell ID 220`；ordinal 1640 對 wait cell 傳入 `terminate=true`，ordinal 1642 回報 `Script terminated`。
- cell 227 在 ordinal 1662 再次呼叫同一命令並要求 `require_escalated`。ordinal 1717 對 wait cell 傳入 `terminate=true`，ordinal 1719 回報 `Script terminated`。
- 這些取消記錄結束的是 Codex 執行 cell，沒有提供 shell 子程序退出碼或 OS 終止證據。cell 220 附近的 shell session `38174` 在第一次 V5 launch tool call 前已被輪詢，無證據可把它連到該次 V5 執行。兩個 launch 都沒有可核實的子程序 PID／session 關聯與退出狀態。
- 舊檢查留下的 PID 24707（`codex`，PPID 24682）仍未能連結到原始 V5 請求。idle、取消等待、缺少收據與 DB 未增加 run 都沒有被當成終止證據。本輪沒有重跑相同程序查詢、沒有送終止訊號，也沒有解除 lock。
- 對帳狀態保留 **unknown**。仍缺原始 V5 子程序 PID 到 task 的關聯、該 PID 的退出／wait 結果，以及可對應到該命令的子程序樹證據。細節見 `original-v5-process-audit.json`。

### 保全與停止狀態

- `active.lock` 前後 SHA-256 均為 `17837b7e39ada147db7c124bdecf2812c1e401b5252dc1741aef7b98f3a9772a`；532 bytes、mode `0600`。本輪只計算 hash，沒有輸出或解析 lock 內容，也沒有改寫、刪除或解除。
- 本輪開始時列入的 86 份既有收據／日誌，結束時路徑、bytes 與 SHA-256 全部一致；`sources/` Git 狀態仍為空。比對見 `preservation-final.json`。
- 修改檔案：`scripts/run_codex_pilot_v5.py`、`scripts/run_codex_pit_v3.py`、`src/valuation_engine/ai/service.py`、`tests/unit/test_codex_recovery.py`、`tests/integration/test_ai_analyst.py` 及本報告。其他既有修改保留。
- 新 review 目錄：`data/m41/codex/reviews/kernel-context-gates-20260925T004237Z-1268a18c/`。基線差異、受影響檔案 hash、修補前重現、測試日誌、程序對帳與保全比對均以新檔名保存；沒有覆寫歷史收據或舊 review 日誌。
- 該目錄的交付檔案、bytes 與 SHA-256 清單見 `delivery-manifest-final.json`。
- 本輪狀態仍是舊程序對帳 **unknown**，所以沒有啟動模型／probe／季度流程，也不宣稱 M4.1 Final Pass。

## 2026-09-25 本輪執行補記（R02）

### R02 舊執行核對與 legacy lock 復原

本輪基線保存於 [baseline.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/baseline.json)。HEAD 為 `22e9b9ee944408cb67d5217ca66dd880498fb440`；保留既有工作樹，`sources/` 沒有變更。追蹤差異 SHA-256 為 `acbdff3db06e133ff6e34036ae3023afc6e8c191cce8b892fcc88aeb044dea43`。

首次在一般沙箱執行唯讀 `ps` 查詢遭 `PermissionError: Operation not permitted`，沒有取得程序清單也沒有碰 lock。隨後使用工具正式升權審核執行 `.venv/bin/python data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/collect_r02_process_snapshot.py`（exit 0；內部執行 `/bin/ps -axo pid=,ppid=,etime=,ucomm=,args=`）。快照記錄 638 個程序，解析錯誤 0，未匹配 V5 runner、`codex exec`、probe 或 isolation runner，也沒有相關祖先／子程序。原始 process bytes 的 SHA-256 為 `91c0a8f7a1a3acfa049ba7d15ca16fd15badb9465f926a1b1d77d5f230c0aaae`；原始 argv 未保存。

原始 rollout 檔 SHA-256 為 `d4dee0780e70543adef2524f8a30cbeffca9b4e5b1d2232a4311e25c0331ae0c`。cell 220、227 的兩筆取消輸出位於第 1643、1720 行；後續 task_complete 位於第 1893 行。`Script terminated` 本身沒有提供 PID 或 OS exit code，兩個歷史欄位繼續為 null。此次復原依據同時包含新的完整程序快照與原始 task 紀錄；未以 idle、缺少收據或 DB 沒有新 run 作終止證據。

復原前重新核對 `data/m41/codex/attempts/active.lock`：532 bytes、mode `0600`、inode `101962365`、SHA-256 `17837b7e39ada147db7c124bdecf2812c1e401b5252dc1741aef7b98f3a9772a`，均符合基線。86 份既有收據／日誌在 R02 前核對為 86/86 相同。解除前將原 lock 以 hard link 保存至 `data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/legacy-active.lock.original`；備份仍是原 inode 且 hash 相同。之後才解除 `active.lock`，解除後原路徑不存在。復原決策與事後狀態見 [r02-recovery.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/r02-recovery.json)。

**R02 PASS。** 本補記未啟動模型、probe 或 Q2，也未寫正式資料庫。下一步是 R03 的唯一合成 Codex probe；尚未宣告 probe、隔離或 Q2 通過。

## 本輪後續執行補記（R03，2026-09-25）

### R03 真實合成 probe：FAIL

R02 已依新完整程序快照及原始任務紀錄通過，legacy lock 原文以同一 inode 的 hard link 保存後才解除。其復原資料見前一補記。

R03 只執行一次 `.venv/bin/python -u scripts/probe_codex_pit_launch.py`，並透過工具正式升權審核（`sandbox_permissions=require_escalated`）啟動；輸入明確標為 synthetic，`historical_input=false`。外層 runner exit code 為 0，但 `probe.json` 的 gate 為 **FAIL**：CLI discovery 通過，Codex CLI 合成 inference stage 已啟動，卻在約 3.16 秒後以 exit code `-9` 結束，分類為 `provider_failure`，沒有有效 JSON 輸出。`process_state=confirmed_stopped`，AttemptJournal 完成 `finished/failed` 並解除該 attempt 的 active lock。exit `-9` 的 OS 來源目前未知；沒有推定是 timeout、模型服務或權限拒絕。

- Attempt：`20260925T121458Z-595e4dd8de81`；生命週期、provider check 與 probe 收據位於 [attempt 目錄](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T121458Z-595e4dd8de81)。
- 外層命令：`.venv/bin/python -u scripts/probe_codex_pit_launch.py`；exit code 0。內層 stage exit code `-9`。
- CLI stdout SHA-256：`396adad4df4e88ea8ce7f587100f355004b09ac670fc0a239688bac69170f500`。CLI stderr SHA-256：`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。
- 收據：[probe.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T121458Z-595e4dd8de81/probe.json)，SHA-256 `fb00f8637c660bfc2989cd427e4c488d08272c39466738290e673bb2be3d2558`。Lifecycle `progress.jsonl` SHA-256 `310bb56815dd8ea07951d31045d80d08c644debf87c224b98ed90392bb5a15c9`。整理紀錄：[r03-result.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/r03-result.json)。

**停止：R04–R07 均未執行。** 因 R03 FAIL，沒有執行新的原生 kernel 探測、C1–C12、正式 FY2023-Q2 或結果複核；沒有新 isolation／kernel 收據、DB run 或 snapshot。既有 86 份收據／日誌仍為 86/86 相同，sources/ 未變，legacy lock 的原始備份仍保留；正式 Q2 資料庫未由本輪流程寫入。

下一個具體動作是查明該 Codex CLI 子程序為何在約 3 秒後以 `-9` 結束，並取得可追溯的終止原因；在原因確認前不重試 probe、不啟動 R04–R07。這不是 probe PASS、Q2 PASS 或 M4.1 Final Pass。

## 2026-09-25 R03 診斷補修輪（E06）

本節是新的補記，保留上方歷史 R03 FAIL 內容不變。新增的 D01–D05 診斷、修補與停止判定見 [R03 診斷修補交付報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_R03_DIAGNOSTIC_REPORT.md)。唯一 review 目錄為 [r03-diagnostic-20260925T123554Z-9b71c2f4](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4)。

D01 對 PID 46401 及原 R03 時段的限縮系統日誌查詢沒有找到可直接歸因 `-9` 的證據。歷史 R03 原因仍為 **unknown**；未把既有替身重現當成歷史根因。D02 已修正 Codex monitor 診斷、不可覆寫 sidecar/hash 綁定與 probe exit code 契約，launch failure 的 `started_at` 及退出碼保持未知。明確 launch intent 的 bytes hash 綁定已加入 attempt manifest 與 probe 收據。

D03 最終受影響測試 75 passed；Ruff、mypy、`git diff --check` 通過。完整 SQLite 為 310 passed、兩項既有 Gemini 測試失敗、1 項 PostgreSQL-only skip，沒有修改 Gemini 程式或測試。86/86 舊收據與日誌、4/4 歷史 R03 artifacts、legacy lock 原備份及正式 SQLite DB hash 均符合基線；正式 DB 未寫入。

**D04 BLOCKED，尚未啟動真實合成 probe。** 普通沙箱程序查詢受 `Operation not permitted` 阻擋；D03 後透過正式升權審核提出的新鮮完整程序查詢沒有回傳結果，預期的結果檔不存在。較早 12:56 的 676 列、0 匹配查詢發生在 D03 最後測試之前，未拿來替代啟動前查核。沒有建立本輪 probe attempt／收據，真實 Codex/model 呼叫 0 次；R04–R07 全部未執行，沒有 run／snapshot 或正式 DB 寫入。legacy `active.lock` 路徑目前不存在；原始 lock 備份保留且 hash 相同。

本補記後接續前的具體動作是取得 D03 後的新鮮、完整、受審核程序查詢。查詢完整且相關程序／attempt 狀態已確認後，才可保存綁定新 attempt 的 launch intent，並考慮最多一次新的合成 probe；若查詢不完整、匹配相關程序或狀態 UNKNOWN，停止且不啟動模型。此狀態不是 probe PASS、Q2 PASS 或 M4.1 Final Pass。

### E07（2026-09-25T13:22Z–13:35Z）：直接接手修正 schema；R03 PASS

- 新的診斷前完整程序查核取得 655 列、0 解析錯誤、0 相關匹配。attempt `20260925T132437Z-aa3ef0ad88a2` 收到 `invalid_json_schema`，明確指出 `properties.ok` 缺少 `type`；runner 隨後記錄 SIGKILL 要求，觀察 child -9、outer 1，FAIL 收據保留。
- 將 probe schema 的 `ok` 補上 `type=boolean`，保留 `const=true`。新增假 CLI 讀取實際 schema 檔案的回歸，修補前 1 failed、修補後 1 passed。受影響測試 76 passed；完整 SQLite 311 passed、2 項既有 Gemini failed、1 PostgreSQL-only skip；Ruff、mypy 71 files 及 diff check 通過。
- 修正驗證前取得另一份完整程序查核：2026-09-25T13:33:41Z，638 列、0 解析錯誤、0 相關匹配；所有執行 attempt 已終結，無 active lock。使用新的 verification launch intent，修正後 attempt `20260925T133432Z-943115f4f889` 於 13:34:38Z **PASS**：child 0、outer 0、confirmed_stopped、first_failure null、runner 終止要求為空。診斷與 intent 的 bytes hash 已複核。
- 本輪共 2 次真實合成 attempt（一次診斷、一次修正後驗證），沒有啟動自動重試。原始 12:14 R03 FAIL 與 unknown 原因不改寫。
- 86 份舊收據、原 R03 的 4 份 artifacts、legacy lock 備份與正式 DB hash 相符；AI run 仍 13、snapshot 2、provider calls 118。active lock 已由成功 attempt 正常解除；sources/、HEAD 及其他既有程式修改保留。
- **目前位置：R03 PASS，下一階段 R04；R04–R07 本輪未執行。** 完整說明見 [介入修復報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_R03_INTERVENTION_REPORT.md)，保全與收據複核見 [verification-result.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-intervention-20260925T132255Z-eedd08b4/verification-result.json)。
