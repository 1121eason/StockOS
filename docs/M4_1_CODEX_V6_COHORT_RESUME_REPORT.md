# M4.1 V6 六季接續執行報告

日期：2026-09-27（Brisbane）。使用者明確要求「請下一步繼續」，本輪執行一個新的六季批次：從 FY2023-Q3 開始，逐季驗收，首個 FAIL／UNKNOWN 即停止。本批次不含兩季重跑比較、真人判定、commit、push、部署或 M5。

**最終結果（2026-09-27 03:54 Brisbane）：新增 FY2023-Q3、FY2024-Q1 PASS，連同既有 Q2 為 3／7 PASS。FY2024-Q2 的第 12 批擷取連續兩次 180 秒逾時，批次 FAIL；後三季未執行。獨立保全複核 PASS，程序狀態已確認、active.lock 已正常解除，M4.1 尚未結案。**

Review：`data/m41/codex/reviews/v6-resume-20260926T160240Z-565eec65/`。

## 起始基線

- Q2 V6 run 15／snapshot 4 保持 PASS；上輪 Q3 run 16 因 CLI 用量上限 FAIL、無 snapshot，失敗收據與部分證據保留。
- HEAD、既有 M4.1 工作樹與 `sources/` 保持；本輪不修改產品程式。
- 新基線保護 396 份歷史檔案；正式 DB 已有 run 16／snapshot 4，後續新結果另外新增，不覆寫舊資料。
- 上輪完整 SQLite 為 349 passed／0 failed／1 PostgreSQL-only skipped；PostgreSQL 為 350 passed／0 failed／0 skipped。已重核交付檔案 hash，沒有產品程式變動，本輪不重複相同全套測試。
- 本輪 app 用量唯讀快照為每週剩餘 92%、一般使用可用。CLI 登入、版本與實際呼叫另行驗證，不用 app 快照代替。

## 啟動前核對

首次前置 helper 已確認全部舊執行 attempt 終結、無 active lock、396 份歷史 hash 與正式 DB bytes 相同；重新封存六季 plan 的 SHA-256 仍為 `d1c4ef1f001bbb8b5cfc36d823d51cf62b35841d98a62423ec6e94622e331abb`。CLI／登入／live isolation gate PASS。

完整程序清單 561 列、解析錯誤 0；12 個 Codex GUI／CLI／輔助程序未被初版 helper 分類，前置檢查停止，沒有建立模型 attempt、沒有正式 DB 寫入。保存 `process-preflight.json`、`launcher-error.json` 與 `launch.log`；另以精確 PID 唯讀查核執行檔及角色標記，不保存完整 argv，不以程序名稱直接判定舊模型仍在跑或已停止。

## 季度追蹤

| 順序 | 季度 | 本輪狀態 | Run／snapshot |
|---|---|---|---|
| 基線 | FY2023-Q2 | 既有 V6 PASS | 15／4 |
| 1 | FY2023-Q3 | PASS；15／15 valid，16 個有值特徵 | 17／5 |
| 2 | FY2024-Q1 | PASS；23／23 valid，16 個有值特徵 | 18／6 |
| 3 | FY2024-Q2 | FAIL；11 valid／2 timeout，無完整 snapshot | 19／— |
| 4 | FY2025-Q4 | NOT_RUN | — |
| 5 | FY2026-Q1 | NOT_RUN | — |
| 6 | FY2027-Q2 | NOT_RUN | — |

各季通過需有完整 snapshot、有效呼叫、固定 context／source／cutoff／package 與隔離收據綁定、正式引用及敘述檢查、必要 challenges、十張保護表一致。缺漏保留，不編造特徵。啟動、模型完成、季度 PASS、資料保全與 M4.1 Final Pass 分開判定。

後續精確 PID 查核已確認上述 12 個項目為 ChatGPT.app 的 Service／Renderer、帶前置旗標的 app-server 與 codex-code-mode-host，沒有 exec 角色。初版 helper 沒有辨認含空白的框架路徑與前置旗標，原攔截收據保留；第二版改用 comm 執行檔路徑及命令角色分類，重新取得完整快照後才可啟動。產品程式未改。


## 正式啟動

2026-09-26T16:24:19Z（Brisbane 2026-09-27 02:24）啟動唯一新模型 attempt `20260926T162419Z-e8111a42203b`，16:24:22Z 進入第一個 Q3 extract。有效執行 review 為本輪 `launch-03/`：新的完整快照 591 列、0 解析錯誤、0 未解決程序，CLI `codex-cli 0.155.0-alpha.9.2`、登入、live isolation、固定六季 plan 與收據 bytes 全 PASS。此時保護 425 份歷史檔案，含前兩次未啟動模型的檢查紀錄。

第二次前置快照曾看到額外 PID 37099；後續查核該 PID 已不存在，父程序 2859 為 app Computer Use 服務，歷史退出碼保持 null。第三次啟動前重新核對完整程序，不以父程序身分豁免未知 PID。三輪前置檢查只產生本節這一個模型 attempt。

監看 helper 初版誤查 AIAnalysisRun 不存在的 status 欄位，唯讀查詢失敗；以 PRAGMA 核對實際欄位後另存 `launch-03/monitor-live.py`，舊 helper 保留。此問題未改動 runner、正式 DB 或模型請求。


2026-09-26T16:45:39Z：Q3 的 13 批 extract 均正常結束，進入 synthesize，尚無 provider 失敗。正式季度結果仍待 challenge 與驗收，不把呼叫完成數當作季度 PASS。執行期間唯讀監看遇 SQLite writer lock，另存舊版監看 helper 並改讀 progress／receipt；未干預 writer，正式 DB 改於 terminal receipt 後獨立複核。

2026-09-26T16:50Z：Q3 gate PASS，run 17／snapshot 5，15／15 valid、406 evidence、16 個有值特徵、12 項明確缺漏，blockers 空。每季保全檢查通過；全批次獨立複核待 terminal 收據。FY2024-Q1 於 16:50:41Z 進入 extract，目前七季 2／7 PASS。

Q3 品質明細：9 個候選因 direction_unsupported 被隔離，未納入正式特徵；16 個有值特徵加 12 項明確缺漏符合既有季度規格。季度 PASS 不代表所有特徵都有足夠證據，也不替代真人語義審查。FY2024-Q1 共 21 批預定 extract，當時仍在執行。

2026-09-26T17:23:53Z：FY2024-Q1 的 21 批 extract 全部正常結束，進入 synthesize；截至 17:24:02Z 尚無 provider 失敗事件。季度 gate 仍待 challenge 與驗收。

2026-09-26T17:29Z：FY2024-Q1 gate PASS，run 18／snapshot 6，23／23 valid、612 evidence、16 個有值特徵、12 項明確缺漏。9 個 direction_unsupported 候選被隔離；五類 challenge 齊備、blockers 空、每季保全通過。FY2024-Q2 於 17:29:21Z 開始 22 批 extract；七季目前 3／7 PASS，全批次獨立複核仍待 terminal 收據。


## 最終結果與白話說明

本輪實際推進兩季，過去卡住的程序／隔離問題沒有再次阻止啟動。現在的阻礙是 FY2024-Q2 同一批資料兩次都未在 180 秒內完成，runner 依既定期限終止並保存失敗。確定的是逾時處理經過；模型為何回得慢仍未知，沒有 CLI 用量上限或其他首錯證據，也不倒填最早 R03 的 unknown 原因。

| 季度 | 有效／總呼叫 | 正式 evidence | 有值／28 特徵 | 明確缺漏 | Challenges | 驗收 |
|---|---:|---:|---:|---:|---:|---|
| FY2023-Q2（既有） | 22／22 | 540 | 27／28 | 1 | 8 | PASS，run 15／snapshot 4 |
| FY2023-Q3 | 15／15 | 406 | 16／28 | 12 | 8 | PASS，run 17／snapshot 5 |
| FY2024-Q1 | 23／23 | 612 | 16／28 | 12 | 7 | PASS，run 18／snapshot 6 |
| FY2024-Q2 | 11／13 | 361 | 未完成 | 無完整判定 | 0 | FAIL，run 19，無 snapshot |
| FY2025-Q4、FY2026-Q1、FY2027-Q2 | 未呼叫 | — | — | — | — | NOT_RUN |

Q3 與 FY2024-Q1 各有 9 個 direction_unsupported 候選被隔離，沒有混入正式特徵。FY2024-Q2 有 1 個 evidence_span_too_long 候選被隔離；它不是本次停止的首要原因。季度 PASS 依既有規格允許明確缺漏，不等於 28 項都有值或真人已認可分析。

## 逾時證據

- attempt `20260926T162419Z-e8111a42203b`：16:24:19Z 啟動、17:54:22Z 結束，約 90 分鐘；只有這一個真實模型批次，外層 exit 1，沒有外層重試。
- FY2024-Q2 call 224：17:48:18Z–17:51:18Z，180.079 秒；call 225：17:51:18Z–17:54:18Z，180.027 秒。
- 兩次 request hash 與 43 個 input blocks hash 相同，prompt JSON 為 34,359 字元。retry_count 分別為 0／1，遵守兩次上限。
- 兩次皆 `failure_kind=timeout`、runner SIGKILL 要求成功、有界 wait 完成、exit -9、`confirmed_stopped`。`first_failure=null`，沒有完成的 structured output。診斷保留 `causal_attribution=unknown`，沒有將時間相關性改寫為 OS 根因證明。
- 本輪 45 次成功 extract 的時間為 27.751–169.566 秒，中位數 96.619 秒。這些數據可供後續評估分批與時限政策，不能單憑兩次逾時斷言是內容過大、服務故障或模型掛住。
- 季度 blockers 包含呼叫生命週期失敗、缺 snapshot、缺 features／mandatory challenges、provider calls 未完成。這些後續缺漏源於分析中斷，不以空資料宣稱 PASS。

診斷：[timeout-diagnostic.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-resume-20260926T160240Z-565eec65/launch-03/timeout-diagnostic.json)。正式批次收據：[validation.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260926T162419Z-e8111a42203b/validation.json)。

## 獨立複核、保全與測試

以唯讀 SQLite 連線重讀 run 17–19，重算季度 gate、呼叫 hash、context／preflight／package／kernel／isolation 收據綁定、特徵與證據、challenge、執行順序。Q2 原 pilot 亦重核；cohort FAIL、integrity PASS，沒有繼續執行 FAIL 之後的季度。

425／425 歷史檔案與啟動引用 hash 相同；十張保護表與十二張 AI／建議表的舊 rows 相同。正式 DB 合法新增 3 runs、2 snapshots、51 calls（49 valid／2 failed）、1,379 evidence、32 features、15 challenges；沒有新增真人評審。`process_state_unknown=false`，active.lock 不存在。唯讀診斷前後 DB bytes hash 相同。

本輪沒有修改產品程式或測試，不重跑相同完整套件。最近已驗證結果仍為正式 SQLite 349 passed／0 failed／1 PostgreSQL-only skipped、專用 PostgreSQL 350 passed／0 failed／0 skipped，Ruff／mypy 71 files 通過。最後另執行 diff check 並封存交付 manifest；HEAD、`sources/`、既有程式修改保持，沒有 commit／push／部署。

獨立複核：[cohort-independent-review.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-resume-20260926T160240Z-565eec65/launch-03/cohort-independent-review.json)。交付保全與所有新檔案 hash 見同目錄的 `final-preservation.json`、`delivery-manifest-final.json`。

## 下一步執行計畫（尚未執行）

| 順序 | 項目 | 內容 | 完成是否 |
|---|---|---|---|
| T01 | 離線逾時分析 | 對照第 12 批 43 個 blocks、輸入長度與成功批次耗時，評估通用分批及有界時限方案；不直接歸因 | 本輪診斷已完成，方案待修訂 |
| T02 | 版本化修補與測試 | 在隔離副本驗證通用方案，保留兩次上限、unknown lock、PIT 隔離與嚴格季度判定；測試先於正式套用 | 未執行 |
| T03 | 恢復入口 | 明確定義同版本已 PASS 季度的收據／DB 重驗與剩餘 plan；若改 prompt／policy／package，重新處理跨版本可比性，不能偷偷跳季 | 未執行 |
| T04 | 新受控驗證 | 前述修補、版本與前置檢查通過後，另建 attempt；原 run 19 FAIL 及部分 evidence 保留 | 未執行；本輪不自動重試 |
| R09 | 兩季重跑比較 | 七季 PASS 後，FY2023-Q2／Q3 同版本各一次，記錄特徵／證據／缺漏差異 | 0／2 |
| R10／R13 | 審查卡與真人審查 | 35 張審查卡與 35 項真人判定；模型不代填真人結論 | 0／35 |
| Final | M4.1 結案 | 七季、重跑、真人、回歸、保全全部達標 | 否 |
