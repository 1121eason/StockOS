# StockOS M4.1 Codex：執行紀錄計畫（V5／V6）

建立日期：2026-09-25。最新狀態核對日期：2026-09-27（Brisbane）；各步實際 UTC 見收據，原建立基線保留於 E03。

正式專案：`/Users/eason/Documents/Coding/StockOS`。

**E17 終局：唯一重跑 attempt `20260927T081514Z-8a8c675a0951` 於 2026-09-27T09:18:04Z 正常完成。Q2／Q3 新 run 24–25／snapshot 11–12，37／37 呼叫有效、零重試，R09 比較 2／2 完成；R10 審查卡 35／35 已生成。獨立 DB 複核與保全 PASS，active.lock 正常解除。正式 SQLite 417 passed／1 PG-only skip，Ruff、mypy 通過。真人仍 0／35，語義穩定性待審，M4.1 尚未 Final Pass。** 見 [重跑與審查報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_REPEATABILITY_REVIEW_REPORT.md)。E16 七季 7／7 PASS 及下方 E15 失敗歷史均保留。

**E15 前輪結果：V6 attempt `20260926T162419Z-e8111a42203b` 已於 2026-09-26T17:54:22Z 結束。Q3 與 FY2024-Q1 PASS；FY2024-Q2 的第 12 批 extract 連續兩次 180 秒逾時，FAIL 並停止，後三季 NOT_RUN。當時七季 3／7 PASS，獨立保全 PASS，該 attempt 的 active.lock 已正常解除。** 詳見 [六季接續報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_COHORT_RESUME_REPORT.md)。

R02–R08、R11、R12 已 PASS；R09 可比條件與比較產物 2／2 完成，R10 已生成 35 張卡，R13 真人判定 0／35。Q2 重跑有值特徵由 27 降至 17，且競爭展望正負翻轉，不能將比較完成當成內容穩定。M4.1 Final Pass 未完成。前輪 Q3 run 16 的 CLI 用量上限 FAIL 保持原紀錄，見 [前輪六季報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_COHORT_EXECUTION_REPORT.md)。最早 R03 的 unknown 原因亦不倒填。

Q2 修補與保全見 [V6 引用對齊報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_TOPIC_ALIGNMENT_REPORT.md)；隔離驗證見 [R04–R07 報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_R04_R07_EXECUTION_REPORT.md)；schema 修正見 [介入修復報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_R03_INTERVENTION_REPORT.md)。E03–E14 保留當時結果。

## 1. 現在已確認的事實

| 項目 | 最新狀態 | 判讀 |
|---|---|---|
| 程式修補 | 本輪新增明確七季基線的重跑／審查卡入口及測試 | 重跑匹配 V1；extract 180 秒、其餘 600 秒、兩次上限；src/、prompt、分批、語義 guard 未改 |
| 受影響測試 | 隔離副本 206 passed；新增 33 項測試 | 正式新增兩檔 bytes 與測試副本一致 |
| 完整 SQLite | 本輪正式主機 417 passed、0 failed、1 skipped | PostgreSQL-only skip；原受限主機 Gemini 失敗紀錄保留 |
| PostgreSQL | 最近專用資料庫完整 350 passed、0 failed、0 skipped | 容器已清理；本輪未重新啟動 |
| 靜態檢查 | 本輪 Ruff、mypy 71 files、diff check 通過 | 最終文件與保全結果納入交付 manifest |
| 啟動前程序查詢 | 新完整清單 599 列、0 解析錯誤、0 未解決程序 | 初次 611 列有不明程序而未啟動；確認該 PID 已不存在後重查，本輪僅一個真實 attempt |
| 程序／鎖 | 新 attempt terminal completed，outer exit 0 | process_state_unknown=false，active.lock 不存在；legacy 備份保留 |
| 正式資料庫 | 新重跑 run 24–25／snapshot 11–12 PASS，37／37 valid、933 evidence | 唯讀獨立複核 PASS；既有 rows 不覆寫 |
| 七季及重跑 | 七季核准基線全部重核；兩季同條件比較完成 | 7／7 PASS、比較 2／2；真人 0／35，尚未結案 |
| 審查準備 | 原前五季核准基線 35 張卡；另附 14 個差異及 350 個引用 | 全部判定待真人填寫；共同方向一致率不能取代語義判斷 |
| 舊資料保全 | 989 份歷史 artifacts、十張保護表及十二張 AI／建議表舊 rows 未變 | 終止後唯讀獨立複核 integrity PASS；本輪合法 DB 新增分開列出 |


原始 R01 基線：[initial-state.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/execution-tracker-20260925T114659Z-f89c1e5c/initial-state.json)。

原始 R02 程序查詢：[process-check.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/process-recovery-check-20260925T113807Z-2d97b072/process-check.json)。

本輪 E17 基線：`data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/baseline.json`；啟動程序查核位於其 `launch-02/process-preflight.json`；最終複核與交付清單為根目錄 `independent-review.json`、`delivery-manifest-final.json`。E16 保留於 `data/m41/codex/reviews/v6-budget-resume-20260927T050441Z-6320e7f4/`；E15 保留於 `data/m41/codex/reviews/v6-resume-20260926T160240Z-565eec65/launch-03/`。

## 2. 執行順序與紀錄要求

狀態採 `NOT_RUN`、`RUNNING`、`PASS`、`FAIL`、`BLOCKED`、`UNKNOWN`。命令已執行與驗收通過分開記錄；exit code 0 本身不足以判定 PASS。

| 階段 | 計畫 | 項目 | 內容／必要紀錄 | 完成是否？ |
|---|---|---|---|---|
| P0 | 現況封存 | R01 狀態基線 | Git、lock hash、86 份舊收據、DB 最新 run／snapshot、既有程序證據；已保存 initial-state.json | 是，PASS |
| P0 | 舊鎖復原 | R02 核對並解除 legacy lock | 依第 3 節完成新的程序核對、鎖備份與復原決策；保存操作前後狀態 | 是，PASS；見 E04 |
| P1 | 真實啟動 | R03 合成 probe | 不含 NVIDIA 歷史資料；每次唯一 attempt；保存外層啟動、程序生命週期、hash、退出狀態及 probe.json | 是，最新修正驗證 PASS；見 E07；E05 歷史 FAIL 保留 |
| P2 | 系統隔離 | R04 新 native kernel probes | 實際驗證外部檔案、repository、寫入、網路受阻；保存命令、有效設定、拒絕結果、canary 結果與 hash | 是，PASS；含正向對照，見 E08 |
| P2 | 完整隔離 | R05 新 C1–C12 收據 | 使用 R04 的明確收據，執行 live discovery 與 A–G 合成案例；綁定 discovery／kernel 路徑、hash、版本及設定 | 是，PASS；見 E09 |
| P3 | 單季驗收 | R06 FY2023-Q2 版本化驗證 | 同一次 runner 先做收據與固定輸入檢查，再以 refresh=True 分析；保存 context、preflight、run、snapshot、pilot、保全與拒絕紀錄 | 是，V5 PASS 見 E10；最新 V6 run 15／snapshot 4 PASS 見 E12 |
| P3 | 單季驗收 | R07 Q2 結果複核 | 核對正式證據、特徵完整性、必要挑戰、十張保護表、實際呼叫數及季度判定；本批次無論 PASS／FAIL 都在此停止 | 是，V6 PASS；27 項有值、1 項明確缺漏，見 E12 |
| P4 | 六季擴展 | R08 其餘六季 | V6 固定 plan 依序執行；接續時重核連續 PASS 前綴、DB 與固定輸入；各季獨立收據，遇 FAIL 停止 | 是，6／6 PASS；連同 Q2 為 7／7 PASS，見 E16 |
| P4 | 重跑比較 | R09 Q2／Q3 重跑 | 七季通過後，同 provider、requested model、CLI、政策、prompt、schema、來源、context 與 V1 budget，各做一次新重跑並比較差異；actual model 未暴露 | 是，2／2 比較完成；語義穩定性待真人判斷，見 E17 |
| P4 | 審查準備 | R10 產生審查卡 | 明確綁定原核准前五季 × 七類的 35 張卡，附證據引用，人工欄位待填；重跑差異另附索引 | 是，35／35 生成；真人判定不是本步完成項 |
| P5 | 正式測試 | R11 Gemini／SQLite 補齊 | 原生 sandbox 需正式主機權限；本輪完整 SQLite 417 passed／1 PG skip | 是，PASS；未改 Gemini 程式、斷言或 skip |
| P5 | 資料庫驗收 | R12 PostgreSQL | E14 前輪唯一容器、專用 QVE_TEST_POSTGRES_URL、core／labels 分離、schema 清理 | 前輪 PASS，350 passed／0 failed／0 skipped；初次三項 FAIL 保留；本輪未重跑 |
| P5 | 真人驗收 | R13 完成人工審查 | 真人填寫 35 項判定、理由、證據、reviewer 及時間；AI 不代填為通過 | 否，0／35 |
| P5 | 最終交付 | R14 M4.1 結案 | 彙整 7／7 季、2／2 重跑比較、35／35 人工審查、正式測試與資料保全；全部符合門檻才可 Final Pass | 否，未達條件 |

本輪依使用者接續指示完成 R09 兩季重跑與 R10 審查卡，並完成 R11 本輪 SQLite 回歸。R12 保留前輪 PostgreSQL 350 passed 的版本範圍，本輪未重跑。下一項 R13 為真人實際判定及差異釐清；R14 需所有適用門檻及測試版本覆蓋經核對後才能結案。

## 3. R02 舊鎖復原程序（已於 E04 完成）

1. 核對正式 checkout 及原始 V5 任務 `01a0d1ad-8e32-7100-a23c-6e0133e244c0`。原始 cell 220、227 的取消紀錄仍保留；不得把 `Script terminated` 改寫成已取得子程序 exit code。
2. 在準備恢復執行時取得新的完整程序清單，保存 UTC、查詢 exit code、匹配規則、解析失敗數及必要的 PID／PPID／程序類型。確認沒有相關 runner／codex exec，並核對原始請求沒有仍待接續的啟動操作。不要只用舊快照推論現在狀態，也不要把一般 Codex app 程序直接認定為舊 V5。
3. 若查詢失敗、清單不完整或有相關執行，記錄 BLOCKED／UNKNOWN 及可採取的下一個動作，停止新模型啟動。不要反覆執行同一個沒有新資訊的查詢；不要要求補造歷史上沒有記錄的 PID 或退出碼。
4. 在新的唯一 review 目錄保存 lock 原文備份、SHA-256、mode 及原始任務證據參照。備份不是修改原鎖；避免把完整程序參數、設定內容或憑證放進日誌。
5. 結合「原始執行 cell 已取消」與「新的完整程序清單沒有相關執行」寫出具體復原依據；舊 PID 的歷史退出碼仍可保持 null。復原前再次確認目前 lock 仍是同一份 legacy lock；若內容、hash 或所有權已變，停止並重新核對。
6. 只有上述復原條件成立，才解除該份 legacy lock。不得刪除其他 attempt 的 lock，也不得讓另一個復原操作或模型任務與此步驟競爭。
7. 保存 recovery.json：證據路徑及 hash、判讀、lock 備份、操作前後狀態、實際時間與執行者。復原舊鎖不代表舊 V5 分析成功，不能補寫舊 PASS 收據。

R02 的完成條件是「復原依據可追溯，已保留原鎖，目標 legacy lock 已安全解除」。只完成程序查詢時，R02 仍不得標為 PASS。

## 4. 真實執行入口及範圍

下列是後續執行用的入口，本文件建立時沒有執行。所有指令的工作目錄固定為 `/Users/eason/Documents/Coding/StockOS`，使用該專案的 `.venv/bin/python`。外層若需權限，使用工具正式提供的審核機制；內層 PIT 限制維持原規格。

| 項目 | 現有入口 | 注意事項 |
|---|---|---|
| R03 | [probe_codex_pit_launch.py](/Users/eason/Documents/Coding/StockOS/scripts/probe_codex_pit_launch.py) | 外層只啟動一次；不在 unknown 或 FAIL 後自動再送一次 |
| R04 | [原生隔離實驗規格](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_CLI_PIT_EXPERIMENT_REPORT.md)及 [transport 實作](/Users/eason/Documents/Coding/StockOS/src/valuation_engine/ai/codex_pit.py) | 先核對真實原生探測的產生方式與目前 CLI；現有 isolation runner 會消費 kernel 收據，不會替代重新執行原生探測；不能只改寫舊收據 |
| R05 | [run_codex_pit_v3.py](/Users/eason/Documents/Coding/StockOS/scripts/run_codex_pit_v3.py) | 明確提供 `--kernel-receipt` 的新收據絕對路徑；使用正式共用 attempts 目錄，不改路徑繞過鎖 |
| R06 舊 V5 | [run_codex_pilot_v5.py](/Users/eason/Documents/Coding/StockOS/scripts/run_codex_pilot_v5.py) | 保留 V5 預設 pin；不是 V6 的直接入口 |
| R06 最新 V6 | [run_codex_pilot_v6.py](/Users/eason/Documents/Coding/StockOS/scripts/run_codex_pilot_v6.py) | 共用完整閘門並明確固定 PromptSetV6；必填 isolation／kernel 收據；preflight 後直接分析，不能當成純檢查重複呼叫 |
| R09／R10 | [run_codex_repeatability_v6.py](/Users/eason/Documents/Coding/StockOS/scripts/run_codex_repeatability_v6.py) | 必填七季完成收據；prepare-plan／export-review 使用唯讀 DB；執行需明確 plan bytes hash，固定 V1；產卡不等於真人審查 |

Q2 固定核准值：FY2023-Q2；cutoff `2022-08-25T13:30:00+00:00`；來源 ID `9, 10, 107, 108`；4 份來源、932 blocks；`PITQuarterPackageV1`；package hash `331e90ebd3ca261c06cf090a5d46ae852a4ded7eb133c434e5f7537abd3ff4c5`；`AIAnalystPolicyV3`／`FeatureSchemaV2`；requested model `gpt-6-astra`。原 V5 入口固定 `PromptSetV5`；最新 V6 入口明確固定 `PromptSetV6`，其他核准值不變。

保留 service 既有兩次嘗試上限，不增加 runner 外層無界重試。未知終止狀態必須保留鎖；已確認退出的成功或失敗，才由該 attempt 的所有權流程處理自身 lock。

## 5. 每一步要如何記錄

新執行產物使用 `/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/` 下的唯一 attempt 目錄；人工核對及復原證據使用 `/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/` 下的新唯一目錄。開始前記錄預定路徑，完成後核對實際存在的檔案及 hash。

| 欄位 | 紀錄要求 |
|---|---|
| 身份與範圍 | 記錄編號、R 項目、執行者／任務 ID、checkout、Git HEAD、相關工作樹 hash |
| 時間 | 請求、啟動、結束的 UTC；未知欄位保留 null，不把請求時間當作程序啟動時間 |
| 實際動作 | 實際命令、工作目錄、外層權限結果；只保存必要且不含敏感資訊的參數 |
| 前置依據 | 前置步驟 PASS 收據的絕對路徑與 SHA-256；CLI、政策、prompt、schema、model 及設定指紋 |
| 執行身份 | attempt ID、可取得的 PID／session；DB run／snapshot ID 由 DB 取得，不預設下一個編號 |
| 結果 | 程序退出碼、業務 gate、成功／失敗／未知分開記錄；測試 passed／failed／skipped 分列 |
| 產物 | manifest、progress、完成收據、stdout／stderr hash、輸入 context、拒絕原因與資料保全結果 |
| 停止與接續 | 具體 blocker、是否保留鎖、下一項工作、接續所需條件 |

完成收據不可覆寫。新的嘗試建立新的 attempt；追蹤表可更新狀態，但實際執行紀錄只追加，不刪除失敗或中斷歷史。Gemini 失敗、PostgreSQL 未執行、人工審查待填必須繼續列在最終缺口中。

## 6. 已發生的執行紀錄

| 紀錄 | 時間 | 項目 | 實際結果 | 證據／下一步 |
|---|---|---|---|---|
| E01 | 2026-09-25；本任務前次複查 | 本機修補與回歸 | 123 受影響測試通過；全套 302 passed／2 failed／1 skipped；靜態檢查通過 | [交付報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_Q2_EXECUTION_REPORT.md)與本任務前次獨立測試輸出；此次未重跑 |
| E02 | 2026-09-25T11:38:07Z，查詢結果封存時間 | 程序存在性查詢 | 查詢 exit 0；688 列完整解析；未匹配相關 runner／codex exec；沒有解除鎖 | [process-check.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/process-recovery-check-20260925T113807Z-2d97b072/process-check.json)；恢復時再次核對 |
| E03 | 2026-09-25T11:46:59Z | 本次狀態與保全核對 | lock 存在且 hash 不變；86 份收據相同；DB 仍 run 13／snapshot 2；沒有新 probe／Q2 attempt | [initial-state.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/execution-tracker-20260925T114659Z-f89c1e5c/initial-state.json)；下一項 R02 |

後續每完成或中止一個 R 項目，在上表追加 E04、E05 等紀錄。沒有實際執行時，時間、退出碼、PID、run／snapshot 及收據路徑不得填入推測值。

## 7. 每輪交付格式與停止條件

每輪結束回報：本輪完成的 R 編號、實際 PASS／FAIL／BLOCKED／UNKNOWN、證據連結、lock 狀態、正式 DB 是否新增資料，以及明確的下一步。程序查詢無法完成時，要寫出失敗原因與可採取的復原動作，不只回覆「繼續等待」。

本批次在 R07 結束：Q2 PASS 可以規劃後續六季；Q2 FAIL 則保存原因並停止季度排程。任何隔離失效、核准輸入漂移、未知程序狀態或十張保護表異動，都必須停止受影響的後續動作。不得把缺少完成收據當作重跑理由。

本計畫保持 `sources/` 唯讀，保留既有修改、歷史 run、snapshot 及收據；不包含 commit、push、部署、26 季擴展或 M5。

依據：[Recovery 工程計畫](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_RECOVERY_ENGINEERING_PLAN.md)、[七季規格](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_7_QUARTER_EXECUTION_PLAN.md)、[最新 Q2 修補報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_Q2_EXECUTION_REPORT.md)。

### E04（2026-09-25T12:11Z–12:13Z）：R02 舊鎖復原

- 初始基線：HEAD `22e9b9ee944408cb67d5217ca66dd880498fb440`；本輪 39 個既有狀態路徑均計入 hash，`sources/` 變更 0；追蹤差異 SHA-256 `acbdff3db06e133ff6e34036ae3023afc6e8c191cce8b892fcc88aeb044dea43`。基線見 `data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/baseline.json`。
- 普通沙箱呼叫 `/bin/ps -axo pid=,ppid=,etime=,ucomm=,args=` 被 `PermissionError: Operation not permitted` 阻擋，exit 1；未操作 lock。使用正式升權審核執行唯讀快照：`.venv/bin/python data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/collect_r02_process_snapshot.py`，內部命令 `/bin/ps -axo pid=,ppid=,etime=,ucomm=,args=`，exit 0。
- 快照時間 `2026-09-25T12:11:22.176075Z`；638 個程序列、解析錯誤 0、V5 runner／Codex exec／probe／isolation runner 匹配 0，相關祖先／子程序 0。原始 process 輸出 SHA-256 `91c0a8f7a1a3acfa049ba7d15ca16fd15badb9465f926a1b1d77d5f230c0aaae`；未保存原始 argv。完整已遮蔽程序清單及原始輸出 hash 見 `data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/r02-precondition.json`（SHA-256 `696a0696e0c429393678f7a31d5d01d9b981519d27f3d85bbee28da1d1b5f17f`）。
- 原始 rollout `~/.codex/sessions/2026/09/24/rollout-2026-09-24T14-30-07-01a0d1ad-8e32-7100-a23c-6e0133e244c0.jsonl` SHA-256 `d4dee0780e70543adef2524f8a30cbeffca9b4e5b1d2232a4311e25c0331ae0c`；cell 220／227 對應的兩筆 `Script terminated` 輸出在第 1643、1720 行，最新 task_complete 在第 1893 行。這些輸出沒有歷史 PID／exit code，兩欄仍為 null。Codex task 查詢的近期 turns 為 completed；OS 終止判斷另依新完整程序清單，未把 idle／缺少收據當作終止證據。詳見 `r02-original-task-adjudication.json`。
- 唯讀比較既有收據／日誌 86/86 均存在且 bytes hash 相同。legacy lock `/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/active.lock` 復原前仍為 532 bytes、mode `0600`、inode `101962365`、SHA-256 `17837b7e39ada147db7c124bdecf2812c1e401b5252dc1741aef7b98f3a9772a`，與本輪基線一致。先以 hard link 保存同一 inode 到 `data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/legacy-active.lock.original`，再解除 legacy lock 路徑；lock 路徑事後不存在，備份 hash 不變。恢復紀錄 `r02-recovery.json` SHA-256 `efba536686546648af76bdb757361487699f7eda71c000471bdadb26321b8a63`。
- 結果：R02 PASS；可進入 R03 一次合成 probe。此狀態不表示模型已啟動或 Q2 已執行。

### E05（2026-09-25T12:14:58Z–12:15:02Z）：R03 合成 probe，FAIL

- 先保存唯一啟動意圖 `data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/r03-launch-intent.json`（SHA-256 `7bb180b2b3d47aa8f59c799499f891bcd94170d627586fc3599884486f047f97`），再只呼叫一次：`.venv/bin/python -u scripts/probe_codex_pit_launch.py`；工具正式升權模式 `sandbox_permissions=require_escalated`，外層 runner exit 0。外層授權與退出紀錄見 `r03-outer-authorization.json`。
- Attempt ID `20260925T121458Z-595e4dd8de81`。CLI discovery `PIT_PROBES_REQUIRED`、版本 `codex-cli 0.155.0-alpha.9.2`；lifecycle 已記錄 `launch_requested`、`runner_started`、`inference_started`。合成 stage 子程序於 `2026-09-25T12:15:01.880350Z` 以 exit code `-9` 結束，`process_state=confirmed_stopped`；provider failure，未收到有效結構化輸出。probe 收據 gate **FAIL**，不是因外層 exit 0 而 PASS。
- CLI stdout SHA-256 `396adad4df4e88ea8ce7f587100f355004b09ac670fc0a239688bac69170f500`；stderr SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。收據 `data/m41/codex/attempts/20260925T121458Z-595e4dd8de81/probe.json` SHA-256 `fb00f8637c660bfc2989cd427e4c488d08272c39466738290e673bb2be3d2558`；lifecycle `progress.jsonl` SHA-256 `310bb56815dd8ea07951d31045d80d08c644debf87c224b98ed90392bb5a15c9`；provider check `provider-check.json` SHA-256 `1b6e76de5953c04405e59a6eded81319460d25cfdc0833b77e69f9e1f70b16e5`。彙總見 `data/m41/codex/reviews/r02-r07-20260925T120718Z-a47c9d31/r03-result.json`（SHA-256 `5c2273e4b0eecb60e9ec43f685ce687765c314d06f770b88b14dc0819a8c1afe`）。
- attempt 完成後 `active.lock` 不存在（由該 attempt 在確認 child stopped 後正常解除）；原 lock backup 仍保留於 review 目錄，hash 不變。86 份舊收據／日誌複核為 86/86 未變；本 probe 沒有呼叫 Q2 runner 或正式 DB。
- 停止條件：R03 FAIL，故 R04 native probes、R05 C1–C12、R06 Q2、R07 驗收均未執行。沒有新 isolation/kernel 收據，沒有新 run 或 snapshot。不得自動重試。接續前需先查明 Codex 子程序 3 秒後 exit `-9` 的終止來源；完成原因判定前不再啟動 Codex。

### E06（2026-09-25T12:35Z–13:07Z）：R03 診斷修補；D04 前置程序閘門未確認

- 唯一 review 目錄：`data/m41/codex/reviews/r03-diagnostic-20260925T123554Z-9b71c2f4/`。基線 SHA-256 `cfe6b416362f5d11f5b6c42c8466aaf2b016c6dd4b6abf5b956b248e0ddfc8f2`；保留工作樹既有修改，`sources/` 唯讀。
- D01 已查原 R03 attempt、progress、provider check、收據及當時程式路徑；另對 PID 46401、`12:14:30Z–12:15:30Z` 做限縮 unified-log 查詢，exit 0、199 事件，無直接終止原因證據。歷史失敗原因仍 unknown；原 R03 FAIL artifact 未改寫。見 `d01-system-diagnostics.json` 與 `d01-offline-history-review.json`。
- D02 修正 `src/valuation_engine/ai/codex_pit.py` 與 `scripts/probe_codex_pit_launch.py`，測試在 `tests/unit/test_codex_recovery.py`。診斷 sidecar 有界、去敏、不可覆寫並由 probe 收據 hash 綁定；runner 終止請求與有界 wait 分欄；launch failure 的開始時間及 exit 保持未知。CLI 只在收據 PASS 回傳 0。明確 launch intent 路徑與 bytes hash 已綁定至 attempt manifest／probe receipt。
- D03 最終受影響測試：`.venv/bin/pytest -q tests/unit/test_codex_recovery.py tests/unit/test_codex_pit.py` exit 0，75 passed。完整 SQLite：`env -u QVE_TEST_POSTGRES_URL .venv/bin/pytest -q -ra` exit 1，310 passed、兩項既有 Gemini 失敗、1 項 PostgreSQL-only skip；測試名稱及相同先前失敗原因見新診斷報告。Ruff、mypy、`git diff --check` 均 exit 0。
- D04 保全核對：86/86 舊收據、4/4 原 R03 artifacts、舊 lock 備份 hash、正式 DB bytes hash 均相同；正式 DB 未寫入。普通沙箱程序查詢受 `Operation not permitted` 阻擋。D03 後的受審核 fresh complete process check 未回傳結果，且輸出證據檔不存在；較早 12:56 的 676 列／0 匹配快照早於最後測試，不能當作新鮮啟動前檢查。舊 P0 目錄已核對為 recovery-baseline inventory，並非執行 attempt。
- 結果：D01–D03 完成，D04 **BLOCKED**；本輪真實 Codex/model 呼叫 0 次，沒有新 probe attempt／receipt，沒有 R04–R07 或正式 DB 寫入。`active.lock` 目前不存在；legacy lock 原備份保留。具體阻礙與下一個必要動作見 `docs/M4_1_CODEX_V5_R03_DIAGNOSTIC_REPORT.md` 及 `d04-process-check-blocker.json`。不得據此改寫 E05 或舊 R03 根因。

### E07（2026-09-25T13:22Z–13:35Z）：直接接手修正 schema；R03 PASS

- 新的診斷前完整程序查核取得 655 列、0 解析錯誤、0 相關匹配。attempt `20260925T132437Z-aa3ef0ad88a2` 收到 `invalid_json_schema`，明確指出 `properties.ok` 缺少 `type`；runner 隨後記錄 SIGKILL 要求，觀察 child -9、outer 1，FAIL 收據保留。
- 將 probe schema 的 `ok` 補上 `type=boolean`，保留 `const=true`。新增假 CLI 讀取實際 schema 檔案的回歸，修補前 1 failed、修補後 1 passed。受影響測試 76 passed；完整 SQLite 311 passed、2 項既有 Gemini failed、1 PostgreSQL-only skip；Ruff、mypy 71 files 及 diff check 通過。
- 修正驗證前取得另一份完整程序查核：2026-09-25T13:33:41Z，638 列、0 解析錯誤、0 相關匹配；所有執行 attempt 已終結，無 active lock。使用新的 verification launch intent，修正後 attempt `20260925T133432Z-943115f4f889` 於 13:34:38Z **PASS**：child 0、outer 0、confirmed_stopped、first_failure null、runner 終止要求為空。診斷與 intent 的 bytes hash 已複核。
- 本輪共 2 次真實合成 attempt（一次診斷、一次修正後驗證），沒有啟動自動重試。原始 12:14 R03 FAIL 與 unknown 原因不改寫。
- 86 份舊收據、原 R03 的 4 份 artifacts、legacy lock 備份與正式 DB hash 相符；AI run 仍 13、snapshot 2、provider calls 118。active lock 已由成功 attempt 正常解除；sources/、HEAD 及其他既有程式修改保留。
- **目前位置：R03 PASS，下一階段 R04；R04–R07 本輪未執行。** 完整說明見 [介入修復報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_R03_INTERVENTION_REPORT.md)，保全與收據複核見 [verification-result.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r03-intervention-20260925T132255Z-eedd08b4/verification-result.json)。


### E08（2026-09-25T13:46:11Z）：R04 原生隔離，PASS

- 新 review 基線為 `data/m41/codex/reviews/r04-r07-20260925T134123Z-4c9dabd1/baseline.json`。新鮮唯讀程序查核完整 686 列，解析錯誤 0、相關匹配 0，沒有 active lock。
- 本輪 helper 以目前 CLI `sandbox` 命令與正式 qve_pit overrides 執行；正向讀取對照成功，file／repository／write／network 四項都取得目標明確的權限拒絕。各 exit 分別 1／1／1／7；沒有把沙箱啟動失敗或逾時當作 PASS。
- attempt `20260925T134611Z-024a390e5402`；outer exit 0、gate PASS、設定 hash 未變、正常釋放 lock。真實模型呼叫 0。
- kernel bytes SHA-256 `06304e4527cf9916052905f1643bfbc0fdb75d6db29ba7808d5eea0c61222b63`。詳見 [R04–R07 報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V5_R04_R07_EXECUTION_REPORT.md)。

### E09（2026-09-25T13:46:38Z–13:47:23Z）：R05 C1–C12，PASS

- 新程序查核 696 列，解析錯誤及匹配均 0；使用明確 R04 kernel 收據啟動一次 isolation runner。
- attempt `20260925T134638Z-1fee66420774`；A–G 七次合成案例均 PASS，C1–C12 全 PASS，outer exit 0，沒有歷史資料或正式 DB 寫入。正式 DB bytes hash 至此仍與基線一致。
- Q2 runner 的 saved-isolation 驗證另行執行 PASS；新 isolation receipt 綁定 discovery 與 kernel 實際路徑及 hash。isolation bytes SHA-256 `be697cc8c108499a491d350378be34e052c227e47994b0b09069cd8fc6baa474`。

### E10（2026-09-25T13:48:07Z–14:23:33Z）：R06 FY2023-Q2 V5，PASS

- 13:47:48 UTC 新程序查核 687 列，解析錯誤及匹配均 0。保存唯一 `r06-launch-intent.json` 後啟動一次正式 runner；沒有外層重試。
- attempt `20260925T134807Z-883ae0f7cd0c`；固定來源／cutoff／package、有效設定、kernel 與 isolation bytes 綁定、核准 context hash 的 preflight 全 PASS。
- 正式新增 run 14／snapshot 3。20 extract + 1 synthesize + 1 challenge，共 22／22 valid；全部 child exit 0、confirmed_stopped、first_failure null、runner signal requests 空。outer exit 0，正式季度 gate PASS，blockers 空，active lock 正常釋放。
- 541 筆正式證據、6 個有值特徵、22 個缺漏、8 項挑戰、21 個隔離候選；十張保護表前後完全相同。新的 [pilot.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260925T134807Z-883ae0f7cd0c/pilot.json) SHA-256 `e9e7d8bec2d6d0aed35b973c01161d99abe739e390159dc26baab1ab01480a20`。

### E11（2026-09-25T14:23:58Z）：R07 獨立複核，PASS；本批次停止

- 以唯讀 SQLite 連線重讀正式資料，重算季度 gate 與收據一致；逐次 request／response hash、核准 context／package、收據路徑及 bytes 綁定、退出狀態與外部存取／升權計數均符合。
- 十張保護表與起始基線一致；11 張 AI 表的既有 rows 內容 hash 與數量一致。原 run 13／snapshot 2 未覆寫；本輪 102 份保護 artifacts（含原 86 份收據）保持 hash。541 筆證據與 24 段正式敘述通過引用、時間及既有安全規則。
- Q2 PASS 採用既有「允許明確缺漏」規格：6／28 特徵有值，21 個 synthesis 候選因跨 topic 引用被隔離，`switching_cost_strength` 沒有候選，故 22 項維持缺漏。建議下個工作先改善 synthesis 引用對齊與特徵涵蓋，不放寬 guard 或填造缺漏。
- [獨立複核收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/r04-r07-20260925T134123Z-4c9dabd1/r07-independent-review.json)為 PASS。本輪產品程式未變；最近完整 SQLite 仍為上輪 311 passed／2 failed／1 skipped。PostgreSQL、六季、重跑比較及 35 項人工審查未執行；M4.1 Final Pass 仍未達成。

### E12（2026-09-26T03:05:52Z–03:54:23Z）：V6 引用對齊修補、新 Q2 與獨立複核，PASS

- V5 未明確提示 supporting／contradicting 引用都要與 feature_name 同 topic，與既有 guard 不一致。新增 PromptSetV6，由本次正式 evidence 衍生 28 組可引用鍵；不重新分類、不刪除反向證據、不填造缺漏，也不放寬 guard。V6 runner 共用原收據／核准 context／保全閘門，明確固定 V6，其他 Q2 核准值不變。
- 先在隔離副本驗證：新增回歸修補前 4 failed／2 passed，修補後 6 passed；受影響 125 passed。不可覆寫 patch 經 `git apply --check` 後套用正式 checkout，受影響 125 passed；正式全套 SQLite 319 passed／兩項既有 Gemini failed／1 PostgreSQL-only skipped。Ruff、mypy 71 files、diff check 通過，未修改 Gemini 程式或測試。
- 啟動前完整程序名稱清單 656 列、0 解析錯誤，逐一核對五個 Codex／code-mode PID 均為 app-server 或輔助程序，沒有 exec／sandbox／Python runner。原生與合成隔離收據的 bytes、設定與 transport 政策重新核對 PASS；本輪不另送 probe 或隔離模型呼叫。
- 單次 V6 attempt `20260926T031853Z-2c991fd948e6` 於 03:18:53Z 啟動、03:54:10Z 完成。20 extract + 1 synthesize + 1 challenge 共 22／22 valid，無重試；全部 child exit 0、confirmed_stopped、first failure null、runner 終止要求空。outer exit 0；正式新增 run 15／snapshot 4，Q2 gate PASS、blockers 空，active lock 正常釋放。
- 540 筆正式證據，27／28 特徵有值、1 項缺漏，8 項挑戰，0 個拒絕。跨 topic 拒絕由 21 降為 0；唯一 `switching_cost_strength` 沒有同 topic 證據與候選，維持缺漏。重新擷取後的單季改善不替代同版本重複性或真人審查。
- 03:54:23Z 以唯讀 DB 獨立重算季度 gate、每次請求／回覆 hash、context／package／收據綁定、程序狀態及外部存取／升權計數，全部通過；實際 synthesis 索引與 evidence payload 相符。十張保護表、十二張 AI／建議表的既有 rows、156 份歷史 artifacts hash 相同。舊 run 14／snapshot 3 未覆寫。
- [V6 報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_TOPIC_ALIGNMENT_REPORT.md)、[Q2 收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260926T031853Z-2c991fd948e6/pilot.json)、[獨立複核](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/topic-alignment-20260926T030552Z-9ca5383d/v6-independent-review.json)。本輪到此停止；R08 六季 0／6、R09 重跑 0／2、R13 真人 0／35，PostgreSQL 未執行；不宣稱 M4.1 Final Pass。


### E13（2026-09-26T04:49Z 起；2026-09-27 Brisbane 複核）：V6 六季入口、R08 首季 FAIL、R11 PASS

- 新增 V6 cohort runner 與 28 項回歸測試；隔離副本受影響 138 passed，patch 經 git apply --check 套用。封存 plan 唯讀 session 關閉順序曾失敗，新增測試修正後 exit 0；兩次 plan 與失敗 log 均保留。固定六季完整 context／source／package／cutoff 與收據 bytes，分析不重新準備核准 context。
- R11：受限工具環境全套為 347 passed／2 Gemini failed／1 skipped；最小原生 sandbox-exec 亦 exit 71、Operation not permitted。正式主機同 Gemini 測試 9 passed；完整 SQLite 349 passed／0 failed／1 PostgreSQL-only skipped。未改 Gemini 程式、斷言或 skip。Ruff、mypy 71 files 通過。
- 05:03:02Z 啟動唯一六季 attempt `20260926T050302Z-7fd8997cdb80`，FY2023-Q3 preflight PASS。05:20:33Z、05:20:36Z 的 CLI 首錯均為用量上限；共 12 calls，10 valid／2 failed，307 evidence，未完成 extract、無 snapshot／features／challenges。兩次失敗皆有終止要求及有界 wait 完成，confirmed_stopped。05:20:46Z 批次 FAIL、outer exit 1，active.lock 正常解除；後五季未啟動，沒有外層自動重試。
- 2026-09-27 以唯讀 DB 重算：cohort FAIL、integrity PASS；338 份歷史 artifacts、十張保護表、十二張 AI／建議表既有 rows 未變。正式 DB 僅新增 run 16、12 calls、307 evidence、4 events；Q2 run 15／snapshot 4 仍 PASS。
- 目前 app 帳戶一般使用可用、每週剩餘 98%，不代表已核對 CLI 帳戶或重試通過。未兌換 reset credit 或購買額度。這次新診斷不倒填歷史 R03 -9 的 unknown 根因。
- 證據見 [V6 六季報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_COHORT_EXECUTION_REPORT.md)及 `data/m41/codex/reviews/v6-cohort-20260926T044941Z-32bd1394/`。目前七季 1／7 PASS、重跑 0／2、真人 0／35；M4.1 未結案。


### E14（2026-09-26T15:45:14Z；Brisbane 2026-09-27 01:45）：R12 PostgreSQL 完整回歸 PASS

- 使用本輪唯一 PostgreSQL 16 容器，空 core／labels 庫核對後 migration；QVE_TEST_POSTGRES_URL 只指向專用 core 庫。僅綁定 127.0.0.1，無主機目錄掛載，使用本機既有 image，沒有拉取新 image 或寫入正式資料庫。
- 首次全套 347 passed／3 failed／0 skipped。三項均為真實 archive 測試，空庫缺少所需歷史資料。保留初次 FAIL 收據；沒有修改測試、skip 或預期值。
- 59 份 manifest／原始離線 bytes hash 核對通過；正式 SQLite 僅 mode=ro 讀取 price bars。透過既有 ingestion 載入 55 份來源、713 financial facts、1,682 prices、兩次拆股與價格基準至專用 PG。沒有模型呼叫或來源網路下載。
- 再次完整回歸 **350 passed、0 failed、0 skipped，139.69 秒，exit 0**。public rows 在測試前後一致，labels 未受 replay／測試影響，無殘留 pytest schemas；正式 SQLite bytes 與原始 archive hashes 均未變。
- 收據：[postgres-archive-validation.json](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-cohort-20260926T044941Z-32bd1394/postgres-archive-validation.json)；[完整日誌](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-cohort-20260926T044941Z-32bd1394/postgres-archive-full-tests.log)。R11／R12 通過，R08 仍 FAIL，不合併宣稱 M4.1 Final Pass。


### E15（2026-09-26T16:24:19Z–17:54:22Z）：V6 接續新增兩季 PASS，第三季 timeout FAIL

- 新 review `v6-resume-20260926T160240Z-565eec65/`；最後啟動前置紀錄位於 `launch-03/`。前兩次僅作檢查、沒有模型呼叫，相關攔截與身分核對紀錄保留。
- 新完整程序查核 591 列、0 解析錯誤、0 未解決程序；目前 CLI／登入／隔離與固定 plan 全 PASS。保護 425 份歷史檔案，正式基線仍包含 run 16／snapshot 4；沒有覆寫原 Q3 FAIL。
- 新 attempt `20260926T162419Z-e8111a42203b` 只執行一輪，outer exit 1，沒有外層重試。Q3 run 17／snapshot 5 PASS：15／15 valid、406 evidence、16 有值／12 缺漏、8 challenges。FY2024-Q1 run 18／snapshot 6 PASS：23／23 valid、612 evidence、16 有值／12 缺漏、7 challenges。
- FY2024-Q2 run 19 的第 12 批 extract 兩次皆在約 180 秒 timeout，request／input blocks hash 相同。call 224、225 的 runner 終止要求及有界 wait 均完整，child -9、confirmed_stopped，無 structured output，first_failure null。模型回覆緩慢的原因仍 unknown；不當作 CLI 用量上限或回填原 R03 原因。
- FY2024-Q2 共 13 calls、11 valid、361 evidence，無 snapshot／features／challenges，季度與批次 FAIL；後三季沒有啟動。active.lock 正常解除，process_state_unknown=false。
- 唯讀獨立重算 gate／context／package／收據／call hashes 全部與結果相符，integrity PASS。425 份保護檔案、十張保護表及十二張 AI／建議表舊 rows 不變；本輪共新增 3 runs、2 snapshots、51 calls、1,379 evidence、32 features、15 challenges，無真人判定。
- 七季目前 3／7 PASS、重跑 0／2、真人 0／35。下一步先離線評估一般化分批／有界時限與恢復入口，隔離回歸後另行安排受控 attempt。本輪不再呼叫模型、不宣稱 M4.1 Final Pass；詳見 [六季接續報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_COHORT_RESUME_REPORT.md)。


### E16（2026-09-27T05:14:36Z–07:51:08Z）：有界時限 V2、四季接續與七季複核 PASS

- 隔離副本先驗證，新增機制及舊 cohort 63 passed、受影響 168 passed；patch check 通過後套用，四檔與測試版本 bytes 一致。第一份 patch 格式檢查失敗、未套用，紀錄保留。
- 正式完整 SQLite 384 passed／0 failed／1 PostgreSQL-only skipped；Ruff、mypy 71 files、diff check PASS。src/、Gemini 程式／測試、DB schema 未改，PostgreSQL 本輪未重跑。
- CodexStageBudgetV2 將 extract 上限設為固定 600 秒，其餘同為 600 秒，最多兩次；原 V1 預設保留。分批、prompt、model、policy、schema、PIT package 與隔離限制不變。
- 新 resume 入口重新核對完整原 plan、來源、收據與 DB，明確保留 Q3／FY2024-Q1 的既有 PASS 與 V1 執行設定；只從第一個 FAIL 的 FY2024-Q2 開始，後三季須逐季 PASS 才執行。
- 新鮮程序快照 631 列、0 解析錯誤、0 未解決程序；CLI／live isolation PASS，923 份保護 artifacts 與啟動前 DB hash 一致。唯一 attempt `20260927T051436Z-0ec2cf068d62` 已正常完成；無外層重試、無真人代判、無 commit／push／部署。

- 新四季全部 PASS：FY2024-Q2 run 20／snapshot 7（24／24 valid、630 evidence、17 有值／11 缺漏）；FY2025-Q4 run 21／snapshot 8（25／25、667、17／11）；FY2026-Q1 run 22／snapshot 9（25／25、692、25／3）；FY2027-Q2 run 23／snapshot 10（16／16、507、21／7）。
- 本輪共新增 4 runs、4 snapshots、90 valid calls、2,496 evidence、80 有值特徵、29 challenges；24 項 direction_unsupported 候選隔離保留。既有 Q2／Q3／FY2024-Q1 已重核，七季 7／7 PASS。
- DB call 286：FY2026-Q1 extract 217.454099 秒、valid、exit 0、confirmed_stopped，actual timeout 600；只有這次 extract 超過舊 180 秒。上輪失敗的相同 FY2024-Q2 request 本輪 call 237 在 175.752326 秒 valid；不能據此倒填舊慢回覆根因。
- terminal completed、outer exit 0、process_state_unknown=false、active.lock 不存在。獨立 review 的 cohort／integrity 均 PASS，923／923 歷史 artifacts、十張保護表、十二張 AI／建議表舊 rows 及 pinned refs 不變。既有 HEAD／工作樹／sources/ 保全，見本輪 final-preservation 與 delivery manifest。
- 下一步 R09 同條件重跑 0／2、R10 新結果審查卡待產生、R13 真人 0／35。V1 既有基線與 V2 接續 budget 明示，重跑須匹配或先定義可比基線；M4.1 尚未 Final Pass。

### E17（2026-09-27T08:15:14Z–09:18:04Z）：R09 比較 2／2 完成、R10 審查包交付

- 使用者於七季 PASS 後要求「ok 繼續」。先封存 989 份歷史檔案、既有工作樹及正式資料，新增重跑入口與 33 項回歸測試。隔離受影響 206 passed，唯讀 plan 演練 PASS、DB bytes 未變，patch check／apply 成功；正式完整 SQLite 417 passed／0 failed／1 PostgreSQL-only skip，Ruff、mypy 71 files、diff check 通過。未修改 src/、schema、Gemini 程式／測試；PostgreSQL 本輪未重跑。
- 第一次 preflight 611 列、0 解析錯誤，因未辨明 Codex PID 46062 而停止，沒有啟動 attempt 或模型。後續唯讀查詢確認該 PID 已不存在，再完整查得 599 列、0 未解決程序。保留原失敗查核，沒有依父程序豁免、沒有送終止訊號，也沒有將歷史 exit code 補成已知。
- 唯一真實 attempt `20260927T081514Z-8a8c675a0951` 使用與 Q2 run 15、Q3 run 17 相符的 `CodexStageBudgetV1`。11 項固定條件均相符，包含每個 extract request hash；內層 max_attempts=2，實際 retry_count 全為 0，無外層重試。Actual model 仍 unknown／requested_only。
- FY2023-Q2 新 run 24／snapshot 11：22／22 valid、531 evidence、17 有值＋11 明確缺漏、8 challenges、10 direction_unsupported 隔離候選。比較原 run 15：引用 Jaccard 83.30%，共同方向 16／17（94.12%）；10 項新增缺漏，competition_outlook -0.20 → +0.10。
- FY2023-Q3 新 run 25／snapshot 12：15／15 valid、402 evidence、15 有值＋13 明確缺漏、8 challenges、9 direction_unsupported 隔離候選。比較原 run 17：引用 Jaccard 82.78%，共同方向 14／14（100%）；pricing_power、working_capital_quality 變缺漏，competition_outlook 新增 +0.10。兩季 challenge 維度 Jaccard 均 100%；數字不構成真人語義 PASS。
- Terminal completed、outer exit 0、process_state_unknown=false，active.lock 正常解除。獨立唯讀 DB 複核及重算 PASS：989 份歷史檔案、十張保護表、十二張 AI／建議表既有 rows 不變。合法新增 2 runs、2 snapshots、37 valid calls、933 evidence、32 features、661 feature-evidence links、16 challenges、19 rejects、6 events、4 adjustment proposals；真人 reviews 新增 0。
- R10 明確選原七季核准集合的前五季 run 15、17、18、20、21／snapshot 4–8，生成 35 張待填卡與五季證據冊。沒有採最早／最新 snapshot 猜測，也沒有用重跑結果覆蓋原基線。附加 14 個差異的複核索引與 350 個引用，連結／hash 驗證通過，沒有自動給真人 verdict。
- 證據：[重跑與審查報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_REPEATABILITY_REVIEW_REPORT.md)、[重跑收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T081514Z-8a8c675a0951/repeatability.json)、[人工審查入口](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review/REVIEW_GUIDE.md)。基線、測試、launch-02、獨立複核及 delivery manifest 位於 `data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/`。
- 現在七季 7／7 PASS，R09 比較 2／2 完成，R10 35／35 卡已產生，R13 真人 0／35。下一步需真人核對原文、方向及缺漏差異並交付實際判定；R14 未結案。不宣稱內容穩定、M4.1 Final Pass，也沒有 commit、push、部署或 M5。
