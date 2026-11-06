# M4.1 V5：R04–R07 正式執行紀錄

本輪起始時間：2026-09-25T13:41:23Z。Q2 完成時間：2026-09-25T14:23:33Z（Brisbane 2026-09-26 00:23:33）。工作目錄：`/Users/eason/Documents/Coding/StockOS`。

使用者已指示直接接續執行。範圍為 R04 原生隔離、R05 合成模型隔離、一次 R06 FY2023-Q2 與 R07 唯讀複核；本批次於 R07 停止。

## 目前狀態

| 階段 | 狀態 | 實際結果 |
|---|---|---|
| R04 原生隔離 | PASS | 正向讀取對照成功；外部檔案、repository 檔案、寫入、網路四項均取得目標明確的 OS 權限拒絕 |
| R05 合成隔離 | PASS | A–G 七個案例通過；C1–C12 全數 PASS；Q2 runner 的收據驗證另行複核 PASS |
| R06 FY2023-Q2 | PASS | attempt `20260925T134807Z-883ae0f7cd0c` 完成；正式 run 14／snapshot 3，22／22 呼叫 valid |
| R07 Q2 複核 | PASS | 唯讀重算季度 gate 與資料綁定；541 筆證據、6 個有值特徵、22 個明確缺漏；十張保護表及既有 AI 紀錄均未變 |

**技術季度閘門已通過；特徵涵蓋仍有缺口。** 27 個提出的特徵候選中，21 個因引用其他 topic 的證據被隔離，6 個正式入庫；另 1 個特徵未提出。28 個特徵中的 22 個缺漏均保留，未補成 0 或虛構內容。現行 gate 允許明確缺漏，不能將 PASS 解讀為 28 項特徵齊全或完整企業估值已完成。

## 基線與執行方法

HEAD 為 `22e9b9ee944408cb67d5217ca66dd880498fb440`。本輪不修改產品程式，不變更 `sources/`。先保存 102 份保護 artifacts（含原有 86 份收據、既有 probe 與 legacy lock 備份）、工作樹檔案指紋、正式 DB bytes hash、十張保護表與使用者設定 hash。

新 review 目錄：[r04-r07-20260925T134123Z-4c9dabd1](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r04-r07-20260925T134123Z-4c9dabd1/)。

R04 沒有現成的收據產生入口，因此依已存在的原生探測規格建立本輪專用 helper `run_native_probes.py`。它使用目前 CLI 的 `codex sandbox`、正式 `codex_pit.overrides()` 與 `qve_pit` profile；所有 canary 均為新隨機合成內容。CLI sandbox helper 的用途與介面參考[官方文件](https://learn.chatgpt.com/docs/developer-commands#macos-seatbelt)及本機 help。

helper 先確認 host 可讀 canary、可寫 scratch，再以同一隔離政策完成正向讀取對照；失敗的沙箱啟動、逾時、stdout 資料外洩、未知程序狀態或寫入成功均不得算作權限拒絕。scratch mode 為 0700，避免將一般檔案權限誤認為隔離能力；實際模型 staging 仍沿用原 transport 的唯讀設定。

helper 自我測試的 24 項斷言與 Ruff 均 PASS。使用共用 attempt lock、有界 subprocess cleanup、不可覆寫 JSON 收據。無模型推理，沒有歷史資料。

## R04：原生隔離

程序前置快照時間 `2026-09-25T13:45:53Z`：686 列、解析錯誤 0、相關程序匹配 0。已確認前一輪 probe terminal，沒有 active lock。

實際命令：
```sh
.venv/bin/python -u data/m41/codex/reviews/r04-r07-20260925T134123Z-4c9dabd1/run_native_probes.py
```

經工具正式升權執行；外層 exit 0。attempt `20260925T134611Z-024a390e5402`，四個負向 probe exit 分別為 file 1、repository 1、write 1、network 7。每項均 confirmed_stopped、沒有 canary 回傳、沒有寫入檔案，且 stderr 同時包含正確目標及權限拒絕；正向對照 exit 0。設定前後 hash 相同，lock 正常釋放。

[Kernel 收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T134611Z-024a390e5402/kernel-receipt.json) SHA-256：
`06304e4527cf9916052905f1643bfbc0fdb75d6db29ba7808d5eea0c61222b63`。

## R05：七項合成隔離

新程序快照時間 `2026-09-25T13:46:27Z`：696 列、解析錯誤 0、匹配 0。

實際命令：
```sh
.venv/bin/python -u scripts/run_codex_pit_v3.py --kernel-receipt /Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T134611Z-024a390e5402/kernel-receipt.json
```

外層 exit 0；attempt `20260925T134638Z-1fee66420774`。七個案例 A–G 各呼叫一次，均 PASS；C1–C12 全數 PASS。正式 DB bytes hash 至此仍與本輪基線相同。沒有 active lock。

[隔離收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T134638Z-1fee66420774/isolation-receipt.json) SHA-256：
`be697cc8c108499a491d350378be34e052c227e47994b0b09069cd8fc6baa474`。

## R06：單次 Q2 啟動

新程序快照時間 `2026-09-25T13:47:48Z`：687 列、解析錯誤 0、匹配 0。保存 `r06-launch-intent.json` 綁定 runner、程序查核、新 isolation/kernel 收據及 AI 舊資料基線的實際 bytes hash。

實際命令：
```sh
.venv/bin/python -u scripts/run_codex_pilot_v5.py --isolation-receipt /Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T134638Z-1fee66420774/isolation-receipt.json --kernel-receipt /Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T134611Z-024a390e5402/kernel-receipt.json
```

attempt `20260925T134807Z-883ae0f7cd0c`；正式前置檢查 PASS。固定 FY2023-Q2、cutoff `2022-08-25T13:30:00+00:00`、來源 ID 9/10/107/108、4 份來源／932 blocks、package hash `331e90ebd3ca261c06cf090a5d46ae852a4ded7eb133c434e5f7537abd3ff4c5`。

於 2026-09-25T14:23:33Z 完成並提交正式 DB：run 14、snapshot 3；外層 exit 0。20 次 extract、1 次 synthesize、1 次 challenge 全部 valid、child exit 0、confirmed_stopped，沒有 runner 終止要求或重試。季度 gate PASS、blockers 為空；共 541 筆正式證據、6 個有值特徵、8 項挑戰及 21 項隔離候選。

[Q2 收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T134807Z-883ae0f7cd0c/pilot.json) SHA-256：
`e9e7d8bec2d6d0aed35b973c01161d99abe739e390159dc26baab1ab01480a20`。

## R07：獨立唯讀複核

實際命令：
```sh
PYTHONPATH=. .venv/bin/python data/m41/codex/reviews/r04-r07-20260925T134123Z-4c9dabd1/verify_r07.py
```

exit 0；從唯讀 SQLite 連線重新取得 run、snapshot、calls、evidence、features、challenges 與 rejected rows，重算季度 gate，與正式收據一致。逐次檢查 request／response hash、核准 context／package hash、isolation／kernel 路徑及 bytes hash、程序完成狀態與外部存取／升權計數，全部符合。541 筆正式證據的來源、截止時間、原文 span、hash 及長度／安全規則通過；24 段正式敘述通過現有 narrative 規則。

8 項挑戰涵蓋 upside 1、downside 1、regime 1、anomaly 3、adjustment 2。十張保護表與本輪起始基線相同；11 張 AI 表中執行前已存在的 rows，其內容 hash 與數量均相同。新資料另外新增，未覆寫 run 13／snapshot 2。active lock 已由完成的 attempt 正常解除。

[獨立複核收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r04-r07-20260925T134123Z-4c9dabd1/r07-independent-review.json)；[特徵涵蓋複核](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r04-r07-20260925T134123Z-4c9dabd1/feature-coverage-review.json)。

正式有值的六項為 `custom_asic_outlook`、`demand_visibility`、`inference_demand`、`long_term_demand_durability`、`supply_constraint`、`training_demand`。21 項被拒候選均可在實際 raw output 中找到跨 topic 的引用；`switching_cost_strength` 沒有候選，也沒有該 topic 的正式證據。拒絕判斷符合現行規則，沒有放寬 guard 以取得 PASS。

本輪建議下一個工作先改善 synthesis 的特徵與引用 topic 對齊，再決定六季擴展；保留目前 22 項明確缺漏及所有拒絕紀錄。這是品質改善建議，沒有改寫現行季度 gate，也沒有自動執行新的 Q2 或其餘六季。

R07 helper 首次直接執行因 repository `scripts` 不在 import path 而 exit 1；加入明確 `PYTHONPATH=.` 後完成，沒有重啟模型或修改產品程式。另一次唯讀涵蓋查詢先因表名誤用單數而失敗，修正為既有 `ai_unsupported_claims` 後取得上述結果；失敗查詢沒有寫入 DB。

## 驗收邊界

本輪尚未變更產品程式，因此沒有重跑完整測試。最近一次產品回歸為 311 passed、2 項既有 Gemini failed、1 PostgreSQL-only skip；本輪不將其改寫為全綠。PostgreSQL、六季擴展、重跑比較與人工審查均未執行；不宣稱 M4.1 Final Pass。

AI 舊資料以 `pre-q2-existing-ai-rows-v2.json` 為準；前一版的 count／row hash 正確，但 max_id 誤取第一欄，新版改為依欄名取 id，舊檔保留不覆寫。
