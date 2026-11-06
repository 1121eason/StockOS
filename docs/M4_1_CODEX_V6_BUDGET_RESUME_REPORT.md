# M4.1 V6 有界時限修補與接續驗證

日期：2026-09-27（Brisbane）。使用者於上一輪逾時報告後要求「ok 下一步開始」。本輪先在隔離副本測試，再套用正式 checkout，最後只啟動一個接續批次；首個非 PASS 停止，沒有外層自動重試、重跑比較、真人判定、commit、push 或部署。

**終局：修補、正式回歸、四季接續及獨立 DB 複核均 PASS。七季已達 7／7 PASS；本輪新增 run 20–23／snapshot 7–10，90／90 呼叫有效。唯一批次於 2026-09-27T07:51:08Z 正常結束，outer exit 0、process_state_unknown=false、active.lock 不存在。R09 重跑 0／2、真人審查 0／35；M4.1 尚未 Final Pass。**

Review：`data/m41/codex/reviews/v6-budget-resume-20260927T050441Z-6320e7f4/`。

## 問題與修補

上輪 FY2024-Q2 同一批 43 個 blocks、相同 request hash 兩次在 180 秒逾時；沒有有效 structured output，模型回覆緩慢的原因仍 unknown。這次只改執行時限與接續方式，不將未知原因歸咎於內容長度或服務故障。

唯讀離線比較確認，前 12 批預定 request hash 與上輪實際呼叫全部相同。失敗的第 12 批為 17,866 個正文文字字元、34,359 個完整 prompt JSON 字元；整季最大請求為 55,828 字元，因此第 12 批不是最大輸入。這是保留現有分批、先測試有界時限方案的依據，不構成回覆緩慢的根因證明。明細見本輪 `batch-input-analysis.json`；分析本身沒有模型呼叫。

- 新增明確的 `CodexStageBudgetV2`：extract、synthesize、challenge 都固定最多 600 秒；每次呼叫仍最多兩次嘗試。舊預設 V1 保留 extract 180 秒、其餘 600 秒。
- 沿用每批 18,000 文字字元的完整段落分批，沒有刪除、截斷或重新安排 blocks。model、CLI、PromptSetV6、AIAnalystPolicyV3、FeatureSchemaV2、PITQuarterPackageV1、PIT 隔離設定均保持。
- budget 寫入 preflight、provider settings、正式 call metadata、quarter result 及 plan；新結果會驗證實際 stage timeout、retry 次數與 profile，不能只宣告版本而沒有使用。
- 新入口 `scripts/resume_codex_validation_v6.py` 接受明確、已終結的原 V6 批次收據。重新讀取正式 DB、每季結果／context／preflight／terminal progress、完整原 plan 與現有來源；只有連續 PASS 前綴可保留，從第一個 FAIL 季度重新執行。
- 接續 plan 明確列出已通過結果及其原 V1 時限版本，新四季採 V2。這是執行時限差異，不是新的語義提示版本；後續重跑比較仍須明示並統一執行設定，不能把既有 snapshot 算成新的模型重跑。
- 目前接續入口限定原始完整 V6 批次，不接受未驗證的遞迴接續鏈。所有季度與 M4.1 最終驗收條件維持。

## 測試與套用

| 階段 | 結果 | 證據 |
|---|---|---|
| 隔離副本新測試修補前 | 6 failed | `isolation-red.log`，缺少新 profile／核對機制 |
| 新機制及舊 cohort 測試 | 63 passed | 含實際 monitor 接收 600 秒的替身 CLI 測試 |
| 隔離受影響回歸 | 168 passed | `isolation-affected.log`／`.json` |
| 正式 DB 唯讀 plan 演練 | PASS | `isolation-resume-plan.json`，未啟動 CLI／模型 |
| Patch 檢查與套用 | PASS | 最終 `git apply --check`／apply exit 0，四檔 bytes 與測試副本相同 |
| 正式完整 SQLite | 384 passed、0 failed、1 skipped | `formal-full-sqlite.log`／`.json`；PostgreSQL-only skip |
| Ruff／mypy／diff check | 全部 exit 0 | mypy 71 source files；`formal-*.json` |

第一份 patch 缺少新增檔案格式標記，`git apply --check` exit 1、未套用。保留原 patch／log 後另存 v2 patch，再 check 與套用成功；不是工作樹衝突，也沒有重設或覆寫既有修改。

本輪修改兩個既有檔案（V6 cohort runner、其測試），新增 resume runner 與測試；未改 `src/`、資料庫 schema 或 Gemini 程式／測試。PostgreSQL 本輪沒有重跑，最近專用庫完整結果仍為上一輪 350 passed；不將舊結果記為本輪測試。

## 真實啟動與季度表

新的完整程序查詢 631 列、0 解析錯誤、0 未解決程序；CLI、登入、目前設定與 isolation 收據綁定 PASS。923 份歷史 artifacts 與正式 DB bytes 在啟動前均與新基線相同。正式 plan 的 SHA-256 與隔離演練相同：`7f832e5f796a5cb8d8a6f4d046f7108f81c807b7e494edc2dcdb0d4360d9c2a9`。

唯一新 attempt：`20260927T051436Z-0ec2cf068d62`，05:14:36Z 啟動，05:14:42Z 進入 FY2024-Q2 第一個 extract，07:51:08Z 正常完成（Brisbane 15:14–17:51，約 2 小時 37 分鐘）。外層 launcher PID 99031。執行期間只讀 journal／receipt 監看；terminal 後使用 SQLite `mode=ro` 獨立重算並核對，沒有外層重試。

| 季度 | 狀態 | Run／snapshot | 有效 calls | 特徵有值／明確缺漏 |
|---|---|---|---|---|
| FY2023-Q2 | 既有 V6 PASS，已重核 | 15／4 | 22／22 | 27／1 |
| FY2023-Q3 | 既有 V6 PASS，已重核 | 17／5 | 15／15 | 16／12 |
| FY2024-Q1 | 既有 V6 PASS，已重核 | 18／6 | 23／23 | 16／12 |
| FY2024-Q2 | 本輪 PASS，獨立複核 PASS | 20／7 | 24／24 | 17／11 |
| FY2025-Q4 | 本輪 PASS，獨立複核 PASS | 21／8 | 25／25 | 17／11 |
| FY2026-Q1 | 本輪 PASS，獨立複核 PASS | 22／9 | 25／25 | 25／3 |
| FY2027-Q2 | 本輪 PASS，獨立複核 PASS | 23／10 | 16／16 | 21／7 |

程序啟動、單次呼叫完成、季度 PASS、批次 PASS 與 M4.1 Final Pass 分開記錄。35 項真人審查與兩季重跑比較目前仍為 0／35、0／2。

以下保留執行當時的即時紀錄；最終狀態以開頭結論及後面的獨立複核為準。

05:48:05Z：FY2024-Q2 已完成 22 批 extract，進入 synthesize，沒有 provider 失敗事件。第 12 個擷取回覆本次約 176 秒正常結束；真實 request hash 與有效性將於 terminal 後從正式 DB 獨立核對。此時仍不宣稱季度 PASS 或延長時限已證明是成功的唯一原因。

05:54Z：FY2024-Q2 gate PASS，24／24 valid、630 evidence、17 個有值特徵、11 項明確缺漏，blockers 空、季度保全 PASS。FY2025-Q4 於 05:54:05Z 進入 extract；七季 4／7 PASS。

06:36Z：FY2025-Q4 gate PASS，25／25 valid、667 evidence、17 個有值特徵、11 項明確缺漏；10 項不支持方向的候選保留在隔離拒絕紀錄，blockers 空、季度保全 PASS。FY2026-Q1 於 06:36:26Z 進入 extract；七季 5／7 PASS。

07:13Z：FY2026-Q1 的 23 批 extract 全部完成，進入 synthesize。第 12 批在 06:54:47.205231Z 啟動，06:58:24.656057Z 正常完成，journal 記錄 exit 0、confirmed_stopped，約 217.45 秒，超過舊 180 秒而低於新 600 秒上限。這是 V2 容納較長呼叫的實測紀錄；正式 call 有效性與精確執行時間待整批 terminal 後從 DB 複核，不以此倒推前輪逾時根因。

07:18Z：FY2026-Q1 gate PASS，25／25 valid、692 evidence、25 個有值特徵、3 項明確缺漏；1 項 direction_unsupported 候選保留於拒絕紀錄，blockers 空、季度保全 PASS。FY2027-Q2 於 07:18:25Z 進入最後一季的 14 批 extract；七季 6／7 PASS。

07:45:53Z：FY2027-Q2 完成 14 批 extract，進入 synthesize。本批次尚無 provider failure；最後一季與整批判定仍待完成收據及 terminal 後 DB 複核。

07:51:08Z：FY2027-Q2 gate PASS，16／16 valid、507 evidence、21 個有值特徵、7 項明確缺漏；5 項 direction_unsupported 候選保留於拒絕紀錄。整批 terminal completed、cohort PASS、completed_quarters=7，正常解除自身 lock。隨後唯讀獨立重算為 integrity PASS、blockers 空。

## 獨立結果與實測時限

| 本輪季度 | 正式 evidence | 隔離拒絕 | Challenges | 最長 extract 秒數 |
|---|---:|---:|---:|---:|
| FY2024-Q2 | 630 | 8 | 5 | 175.75 |
| FY2025-Q4 | 667 | 10 | 8 | 175.55 |
| FY2026-Q1 | 692 | 1 | 8 | 217.45 |
| FY2027-Q2 | 507 | 5 | 8 | 173.53 |
| 合計 | 2,496 | 24 | 29 | — |

四季共新增 80 個有值特徵、32 項明確缺漏、1,720 筆 feature-evidence 關聯及 10 筆 adjustment proposals；沒有人工審查資料新增。24 項拒絕均為已知 `direction_unsupported` 類型，保留於隔離 ledger，未被當作正式支持。所有季度的 input/context、preflight bytes、package、isolation／kernel 綁定、正式 call 有效性、snapshot、必要 challenge 與實際執行 budget 均重核相符。

唯一超過舊 extract 180 秒上限的呼叫是 FY2026-Q1 call 286，實際 217.454099 秒、status=valid、exit 0、confirmed_stopped、沒有終止要求，stage_timeout_seconds=600。V2 確實容納了一次舊時限無法完整等待的有效回覆；82 次 extract 與 8 次後續分析全部有效，沒有服務內重試或外層重試。

上輪失敗的 FY2024-Q2 request hash `bb3bced79a17b9181f72df909a856a3d9962d44b41c7e56521b22bb0d8c2f1f6` 本輪為 call 237，輸入相同，175.752326 秒後 valid、exit 0。它本次低於 180 秒，因此不能把這個特定成功完全歸因於提高時限；上輪模型回覆緩慢的根因仍 unknown，歷史 FAIL 未覆寫。requested model 仍是 `gpt-6-astra`，CLI 未暴露可獨立確認的 actual model 身分，維持 requested_only。

## 保全、交付與下一步

- `independent-review.json`：cohort PASS 與 integrity PASS 分開記錄；重新核對原始連續 PASS 前綴、完整 plan、現有來源、四季正式 DB 資料及所有收據，blockers 空。
- 923／923 歷史 artifacts 與所有 launch-pinned references hash 不變；十張保護表及十二張 AI／建議表的既有 rows 全部相同。正式 DB 的預期新增為 4 runs、4 snapshots、90 calls、2,496 evidence 等上述資料，沒有把合法新增誤寫為 DB bytes 不變。
- `outer-completion.json`：exit 0、no_outer_retry=true；terminal status=completed、process_state_unknown=false；active.lock 不存在。既有 legacy lock 備份與歷史 unknown 原因不變。
- 工作樹既有修改、HEAD 與 `sources/` 保留；沒有 commit、push、部署或 PostgreSQL 啟動。最終文件、測試／程序日誌、patch 與 attempt artifacts 由 `final-preservation.json` 及 `delivery-manifest-final.json` 封存。

| 階段 | 目前結果 | 下一個必要動作 |
|---|---|---|
| R08 七季資料驗證 | 7／7 PASS，完成 | 保留七季正式 snapshot 與明確執行 profile |
| R09 同條件重跑比較 | 0／2，未執行 | 為 Q2、Q3 明確匹配既有 V1 執行 budget 與其他固定條件，再作兩次全新分析及差異比較；若改用 V2，先定義可比基線，不能默認相同條件 |
| R10 審查卡 | 尚未依本次最終七季結果產生 | 產生前五季 × 七類的 35 張證據卡，判定保持待填 |
| R11 SQLite | 本輪 384 passed、0 failed、1 PG-only skip | 本輪程式回歸已完成 |
| R12 PostgreSQL | 前輪 350 passed；本輪未重跑 | 保留歷史專用庫結果與版本範圍，不冒稱本輪 385 項全通過 |
| R13 真人審查 | 0／35，未完成 | 真人填寫判定、理由、證據、身分與時間 |
| R14 M4.1 Final Pass | 未達條件 | 重跑比較、真人審查等完整條件成立後才可結案 |

白話說，原本會在擷取途中被三分鐘上限中止的執行流程，現在有經測試、可核對的十分鐘上限與接續入口。這次已把剩下四季全部跑完，資料驗證達七季全數通過。下一階段是檢查重跑結果是否穩定，以及讓真人審查 AI 的解讀；七季通過仍不等於估值判斷已獲真人認可。
