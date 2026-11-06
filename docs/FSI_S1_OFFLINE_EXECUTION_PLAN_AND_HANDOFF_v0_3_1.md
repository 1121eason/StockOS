# StockOS / QVE × Anthropic FSI — S1 完整執行計畫與 Session 交接

## v0.3.1 — 已授權 S1／實作待開始；整合重跑規則與 Confidence 稽核修正

| 欄位 | 內容 |
|---|---|
| 文件 ID | `STOCKOS-FSI-S1-HANDOFF-003-1` |
| 版本 | `0.3.1 — S1 authorized / Implementation not started` |
| 文件日期 | 2026-09-28，Australia/Brisbane |
| 目標 repository | `1121eason/StockOS` |
| 承接文件 | 整合 v0.3 工單全文、v0.3 審查修正及本次實際基線；本檔可獨立交接，不需先讀舊對話 |
| 本輪基線依據 | 本對話的本地程式／唯讀 DB 查核、封存收據，以及本次交接前保全核對；時間與精確 IDs 見 H 節 |
| 工作基線 | `PromptSetV6 / FeatureSchemaV2 / AIAnalystPolicyV3`；實際 branch、commit、dirty manifest 及收據須在開始時綁定 |
| 工作類型 | **限候選環境的程式修改、離線測試、明確 ID 讀取、歷史輸出離線重驗、人工審查輔助資料** |
| 授權狀態 | **使用者已明確同意按本計畫進行，並要求完整 MD 以切換 session。已授權限縮的 S1；S2 live 與正式升格仍未授權。** |
| 不在本輪範圍 | S2 真實模型比較、正式資料修補／升格、M4.1 Final Pass、M5、merge／deploy |
| 已執行狀態 | 已完成唯讀審查、基線／案例定位與本交接檔；S1 候選程式修改、34 項新驗收、A* 重驗仍 NOT STARTED／NOT RUN |

> **本輪不再做廣泛的 FSI 概念審查。先修候選 guard 的證據完整性，再建立可以安全比較 B／C 的入口。**
>
> **核心不變量：一個已接受且分數非零的 feature，在所有證據整理及保存完成後，仍必須保有符合既有准入條件的支持證據。**
>
> Guard 修補的效果，不算作 FSI 方法的效果。S1 的工程驗收，也不算作模型語意品質已改善。

---


## H. 新 Session 先讀：授權、進度與已綁定基線

### H.1 使用者授權與本次交付

使用者在原對話明確表示：

> ok 按照這個計劃進行  
> 給我這個計劃完整md檔案 我要換session

因此，使用者已接受 v0.3 加上本輪審查的兩項修正：**多階段重跑的固定條件／動態輸入分離**、**Guard G 前後 confidence 變動稽核**。本輪依其換 session 要求先交付完整 MD；沒有開始長時間實作。

新 session 的目的：在隔離環境執行 W1–W6，交付可審查 diff、離線測試與 impact audit。不用重做 FSI 廣泛概念研究，也不用重新詢問同一 S1 範圍是否獲准。這份授權不含 S2 live、正式 promotion、commit／push／PR／merge／deploy。

### H.2 交接當下的完成狀態

| 項目 | 狀態 | 說明 |
|---|---|---|
| v0.1／v0.2／v0.3 審查與規格收斂 | 已完成 | 以本整合檔接續 |
| 交接前唯讀基線／案例核對 | 已完成 | 這是接手參考，W1 仍需於新 session 建立新 manifest |
| W1 正式 S1 基線與隔離副本 | NOT STARTED | 尚未建立 S1 候選工作區或新 audit 目錄 |
| W2 Guard G 實作 | NOT STARTED | 正式 guard 與歷史結果保留 |
| W3 Candidate profile | NOT STARTED | 沒有新候選入口 |
| W4 Storage／reader | NOT STARTED | 沒有 candidate DB |
| W5 Comparator | NOT STARTED | 尚未實作或測試 |
| W6 A* audit／review companion | NOT STARTED | 已定位 16／10 案例，尚未跑新 G |
| 本工單 34 項驗收 | NOT RUN | 不沿用舊 pytest 數字當新工單結果 |
| S1／本輪股票分析 pipeline live calls | 0 | 不得執行 auth、discovery 或 smoke 模型探測 |
| 原 M4.1 真人 review | 0／35 | 待真人判定 |
| S2 live | 未授權／NOT RUN | 只可準備待批准計畫 |

### H.3 交接基線：不是遠端 HEAD 的乾淨版本

本次唯讀核對時間：`2026-09-27T15:56:26.117934+00:00`。這是觀察快照，接手時重新驗證便宜且重要的狀態；不要把過去收據當成當下 provider readiness。

| 項目 | 交接核對值 |
|---|---|
| 正式 checkout | `/Users/eason/Documents/Coding/StockOS` |
| Repository | `1121eason/StockOS` |
| Branch | `main` |
| HEAD | `22e9b9ee944408cb67d5217ca66dd880498fb440` |
| 工作樹中的契約 | `PromptSetV6 / FeatureSchemaV2 / AIAnalystPolicyV3` |
| HEAD 內的舊 contracts blob | `4b6c9b2e17732766f1ffcffd1dcdb7f4aa7cd4dd`，三項版本仍為 V1 |
| 新增本交接檔之前的變更路徑 | 56 個 |
| 新增本交接檔之前的 fingerprint 檔案數 | 234 |
| 舊工作樹集合 SHA-256 | `e78203651f3ec6f3bd17f16261b3615a9209572d7e66b81e8cf00ba2965acba5` |
| 正式 SQLite | `/Users/eason/Documents/Coding/StockOS/data/qve.db` |
| 正式 DB SHA-256 | `31bcd861823f903904d1ffab16f6adf93db36044f083dac4869e0a7ff78cb679` |
| 本次 DB journal mode | `delete`；檢查時無 WAL／SHM。未修改 journal mode |
| 最新 AI run／snapshot | run 25／snapshot 12 |
| 封存交付 manifest | 240 份全部 hash 相符 |
| `active.lock` | 檢查時不存在；不構成 live 執行授權或完整程序查核 |

工作樹 aggregate 的舊計算方式：取得 `git ls-files -c -o --exclude-standard -z` 的去重排序路徑，對每個實際檔案取 bytes SHA-256，將 `[(relative_path, sha256), ...]` 以 Python 預設 `json.dumps` 序列化後再取 SHA-256。它涵蓋版本控制可見的原 234 檔，不含 ignored data。

**本交接檔是使用者本輪要求的新檔**，故加入後會多一個路徑，正常 aggregate 也會變。若要重算上表舊值，僅排除本檔 `docs/FSI_S1_OFFLINE_EXECUTION_PLAN_AND_HANDOFF_v0_3_1.md`；S1 的新 baseline 應另外記錄本檔 hash。不要把這個已知新增誤判為 V6 程式漂移。

已讀取的核心檔案 hash：

| 檔案 | SHA-256 |
|---|---|
| [src/valuation_engine/ai/contracts.py](/Users/eason/Documents/Coding/StockOS/src/valuation_engine/ai/contracts.py) | `2f7f14c7ae6d59cb386a2c9110043b3cfd4f61aa91034f0d549de191b5f4884c` |
| [src/valuation_engine/ai/prompts.py](/Users/eason/Documents/Coding/StockOS/src/valuation_engine/ai/prompts.py) | `f0ba44e3b3a66e8f4c8b0c9584f02fb228357ca60a7543c8920a60b98931d175` |
| [src/valuation_engine/ai/guards.py](/Users/eason/Documents/Coding/StockOS/src/valuation_engine/ai/guards.py) | `68502157a73393600311152f68a55160a088a6a669ee1af6689f1775e7f2a53c` |
| [src/valuation_engine/ai/service.py](/Users/eason/Documents/Coding/StockOS/src/valuation_engine/ai/service.py) | `94089c072a92de2d265ca05526a4cd6508167c2ec2541f24ed990ae57e9b4286` |
| [scripts/run_codex_validation_v6.py](/Users/eason/Documents/Coding/StockOS/scripts/run_codex_validation_v6.py) | `d54006fbbdc7406607657a22e99502a584a9db5916f1fb13fd5c78d4a41083b7` |
| [scripts/run_codex_repeatability_v6.py](/Users/eason/Documents/Coding/StockOS/scripts/run_codex_repeatability_v6.py) | `f5d587b714de38d4d0fc1275e019a8b98f94cb901aef17d0bfcefb8db6db01e8` |

`sources/` 永遠是唯讀參考；不得修改、搬移、重新命名或刪除。不要只從 HEAD／遠端 main 建立候選後就宣称具備 V6：當前 V6 大量內容尚在原 working tree，必須完整保留並綁定。

### H.4 明確 run／snapshot 與收據

七季基線：

| 季度 | Run | Snapshot | 權威收據 |
|---|---:|---:|---|
| FY2023-Q2 | 15 | 4 | [收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260926T031853Z-2c991fd948e6/pilot.json) |
| FY2023-Q3 | 17 | 5 | [收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260926T162419Z-e8111a42203b/quarters/FY2023-Q3/result.json) |
| FY2024-Q1 | 18 | 6 | [收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260926T162419Z-e8111a42203b/quarters/FY2024-Q1/result.json) |
| FY2024-Q2 | 20 | 7 | [收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T051436Z-0ec2cf068d62/quarters/FY2024-Q2/result.json) |
| FY2025-Q4 | 21 | 8 | [收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T051436Z-0ec2cf068d62/quarters/FY2025-Q4/result.json) |
| FY2026-Q1 | 22 | 9 | [收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T051436Z-0ec2cf068d62/quarters/FY2026-Q1/result.json) |
| FY2027-Q2 | 23 | 10 | [收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T051436Z-0ec2cf068d62/quarters/FY2027-Q2/result.json) |

兩次基線重跑：

| 季度 | 原 Run／Snapshot | 新 Run／Snapshot | 比較收據 |
|---|---|---|---|
| FY2023-Q2 | 15／4 | 24／11 | [Q2 comparison](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T081514Z-8a8c675a0951/quarters/FY2023-Q2/comparison.json) |
| FY2023-Q3 | 17／5 | 25／12 | [Q3 comparison](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T081514Z-8a8c675a0951/quarters/FY2023-Q3/comparison.json) |

七季 7／7 是當時機械門檻通過，兩次重跑 2／2 是執行及可比條件完成；沒有真人語意穩定性 PASS，亦沒有 M4.1 Final Pass。七季與重跑包的 `official_call_status` 均為 `missing`，不可生成已驗證 Q&A 品質結論。

### H.5 已定位的 16 個空支持特徵

下表由本輪唯讀 SQLite 查詢重新核對，metadata 的 supporting 清單與實際 `ai_feature_evidence` 支持關聯均為空。數值只是原始保存值，不能視為已獲人工认可。

| 集合 | 季度 | Run | Snapshot | Feature row ID | Feature | 原分數 |
|---|---|---:|---:|---:|---|---:|
| 基線 | FY2023-Q3 | 17 | 5 | 43 | `demand_momentum` | -0.50000000 |
| 基線 | FY2023-Q3 | 17 | 5 | 44 | `pricing_power` | -0.60000000 |
| 基線 | FY2023-Q3 | 17 | 5 | 53 | `inventory_quality` | -0.85000000 |
| 基線 | FY2024-Q1 | 18 | 6 | 60 | `pricing_power` | -0.45000000 |
| 基線 | FY2024-Q1 | 18 | 6 | 65 | `working_capital_quality` | -0.45000000 |
| 基線 | FY2024-Q1 | 18 | 6 | 68 | `export_control_outlook` | -0.65000000 |
| 基線 | FY2024-Q2 | 20 | 7 | 77 | `pricing_power` | -0.40000000 |
| 基線 | FY2025-Q4 | 21 | 8 | 102 | `china_outlook` | -0.60000000 |
| 基線 | FY2027-Q2 | 23 | 10 | 140 | `training_demand` | 0.15000000 |
| 基線 | FY2027-Q2 | 23 | 10 | 141 | `competition_outlook` | -0.40000000 |
| 基線 | FY2027-Q2 | 23 | 10 | 147 | `inventory_quality` | -0.55000000 |
| 基線 | FY2027-Q2 | 23 | 10 | 149 | `export_control_outlook` | -0.80000000 |
| 重跑 | FY2023-Q2 | 24 | 11 | 155 | `demand_momentum` | -0.65000000 |
| 重跑 | FY2023-Q2 | 24 | 11 | 164 | `working_capital_quality` | -0.45000000 |
| 重跑 | FY2023-Q3 | 25 | 12 | 172 | `demand_momentum` | -0.45000000 |
| 重跑 | FY2023-Q3 | 25 | 12 | 181 | `inventory_quality` | -0.80000000 |

前輪已將原始 synthesis 與現行 guard 處理逐項對照：16 個原支持清單均含 mixed，後處理可重算出空支持結果。這是問題診斷，**尚不是候選 G 的 A* 重驗**。

### H.6 已定位的 10 個 Q2 拒收案例

全部來自 run 24／snapshot 11。這些 feature 沒有正式 accepted feature row，但該 run 本身有 snapshot；因此不要把 `snapshot_id` 誤記為 null。

| Rejected claim ID | Run | Snapshot | Feature | 原候選分數 | 原拒收原因 |
|---:|---:|---:|---|---:|---|
| 197 | 24 | 11 | `demand_visibility` | -0.7 | `direction_unsupported` |
| 198 | 24 | 11 | `pricing_power` | -0.25 | `direction_unsupported` |
| 199 | 24 | 11 | `supply_constraint` | -0.6 | `direction_unsupported` |
| 200 | 24 | 11 | `custom_asic_outlook` | -0.25 | `direction_unsupported` |
| 201 | 24 | 11 | `customer_insourcing_outlook` | -0.45 | `direction_unsupported` |
| 202 | 24 | 11 | `customer_financing_quality` | -0.1 | `direction_unsupported` |
| 203 | 24 | 11 | `china_outlook` | -0.65 | `direction_unsupported` |
| 204 | 24 | 11 | `export_control_outlook` | -0.45 | `direction_unsupported` |
| 205 | 24 | 11 | `guidance_visibility` | -0.4 | `direction_unsupported` |
| 206 | 24 | 11 | `management_credibility_signal` | -0.25 | `direction_unsupported` |

新 session 以 DB instance、run、raw candidate reference、feature identity 去重；同名 feature 在不同 run 是不同實例。不得將類型不同的機械問題包裝成「26 個已判錯結論」。

### H.7 直接使用的既有證據入口

- [最新重跑與審查報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_V6_REPEATABILITY_REVIEW_REPORT.md)
- [已接受 cohort 與 repeat plan](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/repeat-plan.json)
- [240 份最終交付 manifest](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/delivery-manifest-final.json)
- [原保全結果](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/final-preservation.json)
- [獨立複核紀錄](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/independent-review.json)
- [35 張卡的真人入口](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review/REVIEW_GUIDE.md)
- [原 Q2／Q3 優先差異索引](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/REPEAT_REVIEW_FOCUS.md)
- [原差異原始資料](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/repeat-review-focus.json)

前輪回歸收據是 SQLite **417 passed、0 failed、1 PostgreSQL-only skipped**；當輪 Ruff／mypy／diff check 通過。更早 PostgreSQL 350 passed 屬較早版本範圍。這些都是歷史收據，本工單尚未跑任何新測試。

最新完成的真實 repeat attempt 為 `20260927T081514Z-8a8c675a0951`，已終止完成。S1 為離線，不需為了開始 W1 重新執行 provider discovery、auth、native probe、程序掃描或歷史 R03 重試。

### H.8 新 Session 第一個執行順序

1. 讀本檔與 [AGENTS.md](/Users/eason/Documents/Coding/StockOS/AGENTS.md)，核對 Git root、HEAD、dirty paths、核心檔案及權威 manifests。保留未知，不將版本字串當成內容相同的證明。
2. 綁定當下完整 V6 code bundle 與被比較資料；建立**新的**隔離 worktree／目錄及 artifact root。可以安全複製已核對的產品檔案／測試內容到隔離副本，不能複製 CLI credentials、`.env` 或無關 HOME 設定，也不能 commit 原工作樹來湊出基線。
3. 隔離副本須包含現有未提交 V6 修改；只從 HEAD 建 worktree 不夠。不要 reset／clean／stash／rebase／pull。若建立 branch，依專案使用 `codex/` 前綴。
4. 可沿用現有依賴，但確認 Python import 的產品路徑與測試工作目錄指向候選副本，避免測到正式 checkout 或把預設 DB 指向正式資料。
5. 先建立可在舊 guard 上重現的 mixed／overlap／最終支持空／保存一致性回歸，再實作候選 G。其後做 profile、storage／reader、兩種 comparator，最後做 A* audit 與 W6 交付。
6. SQLite 使用新的測試 DB；PostgreSQL 只用已確認隔離的 `QVE_TEST_POSTGRES_URL`。未配置時記錄缺項並完成其他可做工作，不安裝／啟動替代服務或猜測正式連線。
7. 新產物放獨立 candidate root；若隔離 code 位於暫存目錄，交付前將新 diff／報告／收據存入新的持久 artifact 目錄並提供絕對路徑，避免換 session 後只剩暫存路徑。可以在正式 repo 的 ignored `data/m41/fsi/s1/<UTC>-<unique-id>/` 新增候選交付目錄，但不得覆寫任何既有資料。產品程式修改限隔離副本。
8. 依 W1–W6 完成必要離線工作，不以「還需要設計」代替授權實作。遇到單項缺口，留下真實證據並完成不受阻工作；完成後提供進度表、白話解釋及 S2 待批准計畫。

本次只新增本交接 MD。沒有建立候選 DB／工作區，沒有執行第 2–8 步。這個事實應在接續報告中保留。

### H.9 首版方法整合不可遺漏的基礎限制

- 只使用已核准 PIT source package 與允許 Quant context；`available_at <= cutoff`，資料 hash／來源／speaker 不得自行補造。
- 模型不能讀 DB、repo、`.git`、其他季度、HOME／credentials，也不能用 web、MCP、shell、外部 retrieval 補資訊。S1 用 fake provider，不進行新的 runtime 隔離探測。
- Exact quote／mechanical admission 與人類語意正確性分開；模型既有後見知識無法只靠關網移除。
- 數字僅依既有原文引用欄位規則保留；生成 narrative 的數字禁令、price／future-outcome mask、advisory-only 與 deterministic Quant 邊界保持。
- 不新增 forecast delta、consensus、guidance 數字契約、逐字稿、rating／target price、交易訊號或 M5。
- FSI 只取固定版本的方法，移除搜尋最新財報、三個月內限制、模型／估值直接更新與投資建議。方法與 provider 分離，不安裝整套 plugin。

---

## 0. 使用方式與優先次序

本文整合 v0.3 的完整 S1 工單與最後審查修正，取代其後續執行用途；v0.2／v0.3 原件保留。本檔已補齊必要 PIT、資料、指標及接續資訊，不依賴讀取前一個 session 才能開始。

依使用者最新明確要求，在本檔記錄的 S1 範圍內工作，並遵守執行環境的上層指令及專案限制。本檔作為使用者要求的交接紀錄，不提供 S2、正式資料寫入或其他額外授權；後續使用者修正範圍時，以其最新要求為準。

本輪修正 v0.2 的四處不足：

1. 將 `mixed`／角色重疊／最終支持清單變空，升為必須實作與回歸的 guard 不變量。
2. 明確固定 **28 個特徵全數「正值＝有利，負值＝不利」**，不提供個別 feature 自行反轉的入口。
3. 候選不是另一段 prompt 而已；必須有貫穿 service、run、feature、cache、reader、驗收的明確身分。
4. B／C 方法比較與同候選重跑使用不同規則；實際底層模型未驗證時，僅能聲稱可觀察設定一致。

本輪目標是可審查的候選 diff 與離線收據，不是第三份「建議再研究」報告。必要時可以回報具體 blocker，但應完成不受阻的離線工作，不擴張授權。

---

## 1. 已知基線與新發現

### 1.1 基線狀態：全部來自 owner 提供的審查

| 項目 | 本地審查所述狀態 | 本工單的解讀 |
|---|---|---|
| 契約 | V6／V2／V3 | 凍結原件；候選身分另立 |
| 七季執行 | 7/7 完成、通過當時既定機械門檻 | 保留歷史紀錄，不宣稱通過新 guard |
| 重跑 | 2/2 已完成 | 不等於語義穩定性已通過 |
| 真人審查 | 0/35 | 不以 AI 評語或離線測試補填 |
| 官方電話會議內容 | 七季資料包全部缺失 | Q&A、迴避問題分析無可驗證輸入 |
| M4.1 Final Pass | 尚未完成 | 本工單不批准 Final Pass 或 M5 |
| 新 guard 問題 | 基線 12 個、重跑 4 個，共 16 個非零已收錄 feature 的最終支持清單為空 | 屬機械證據完整性問題，不等於 16 個結論全錯 |
| 既有 Q2 差異 | 10 個新增缺值，負向證據放在反駁欄而未能支持負向 claim | 另一類診斷案例；不直接恢復分數 |
| 模型身分 | `actual_model_identity_verified=false` | 不得改寫為已確認底層模型相同 |

16 個已收錄案例與 10 個拒收／缺值案例，不可直接加成「26 個不同問題」。必須用實際 DB、run、snapshot／raw candidate reference、feature identity 去重並呈現交集。不同重跑的同名 feature 是不同結果實例，不可以 feature 名稱單獨去重。

### 1.2 已回報的 guard 缺口

依本輪審查，現有處理次序為：

```text
原始 supporting 清單含 mixed 證據
    → mixed 通過初步方向檢查
    → 後續被加入 contradicting 集合
    → 從 supporting 移除
    → 未重新檢查 supporting 是否為空
    → 非零 feature 仍被接受／保存
```

Codex 開工時應針對已定位程式及指定案例重現此窄範圍問題，不必重做整套 repository 研究。若實際綁定版本已改變，報告差異，不為符合「16」而更改查詢或測試資料。

### 1.3 保全與驗收的影響

既有 7/7 收據仍是歷史事實，不回改為「當時沒有跑完」。但舊收據不能證明新發現的不變量成立，也不能單獨支撐 M4.1 Final Pass。

原始輸出仍保留。對受影響結果應在**新的 companion audit** 標註待複核；不要更新正式 feature、支持關聯、信心值或既有完成狀態。本輪不把所有歷史分析一概判錯。

---

## 2. S1 的授權邊界

使用者已在本對話明確表示「ok 按照這個計劃進行」，並要求完整 MD 以換 session。這是 S1 的授權紀錄；在使用者要求接續本計畫的新 session 中，先核對當前基線，再按 W1–W6 執行，不必重新提出廣泛概念審查。S2 真實模型及正式升格仍須獨立授權。

### 2.1 允許

- 唯讀綁定實際本地 baseline、既有報告與明確 IDs。
- 在隔離開發分支／worktree 中，修改候選 guard、候選 execution profile、明確 ID reader 與相關離線測試。
- 新增獨立 candidate DB、cache、output、receipt 和人工審查輔助目錄。
- 使用合成資料，以及已核准、可安全唯讀取得的封存 baseline 輸入／raw output 做離線驗證。
- 執行本地非 live 測試；PostgreSQL 僅使用已設定且確認為隔離測試用途的 `QVE_TEST_POSTGRES_URL`。未配置或不可用時如實列缺項，不猜測其他連線、不接正式 DB。
- 產出 diff、manifest、測試收據、guard impact audit、真人審查指南及 S2 待批准計畫。

### 2.2 禁止

- **任何股票分析 pipeline 的 live provider 呼叫**，包括 auth／能力探測、歷史 runner、smoke generation、重試或替代 provider 測試。
- 修改正式 DB、正式 run／feature／evidence／review rows、原始 240 份交付或既有凍結收據。
- 覆寫 V6 prompt、V2 schema、V3 policy，或讓候選設定成為正式預設。
- 回填 16 個已接受案例的支持欄位，或恢復 10 個拒收案例的分數。
- 新增逐字稿、consensus、數值 guidance、forecast delta、付費 MCP、整套 FSI plugin 或 Managed Agents runtime。
- 對 CLI credentials 做讀取、複製、提取或替代認證；啟用額外 API 路徑。
- merge、push、PR、deploy、正式 migration、自動 promotion 或開始 M5。

Codex 作為 coding assistant 進行程式分析與離線 shell／測試，不屬於禁止的股票分析 provider 呼叫。禁止的是由本工單啟動 Claude／Codex／Gemini／其他 provider 去重新分析財報或探測其模型能力。

### 2.3 工作樹與分支

不得自動 pull、reset、stash、rebase、清理或覆寫 owner 既有變更。若本地 V6 含未提交變更，不能只從遠端 main／HEAD 建立 worktree，卻聲稱候選以 V6 為基線。

優先使用已存在的隔離工作區。需新建時，以不改動原 working tree 的方式固定相關內容及 manifest；若沒有安全的方法完整保留本地 V6，回報 blocker。不要透過任意 commit owner 的修改來解決。

本工單不要求 commit；可用未提交的隔離 diff 交付。基線與修改後的 content manifest 必須足以辨識實際內容。

---

## 3. 先固定單一分數方向

### 3.1 必須寫入 candidate 說明與測試的規則

```text
對全部 28 個 FeatureName：
    feature_value > 0：對公司前景有利。
    feature_value < 0：對公司前景不利。
    feature_value = 0：依既有契約表達有來源支持的中性／平衡判斷。
    NULL／未產生：缺資料、證據不足或遭拒收，不是 0。
```

`supply_constraint` 的正值代表**供給壓力緩解**，不是「約束更嚴重」。其餘風險型名稱亦不得憑名稱自行反轉方向；以現行 prompt 中有利／不利的定義解讀。

這項規則修正 v0.2 第 4 章與 `FSI02-10` 容易讓人理解為「不同 feature 可自訂 polarity」的表述。本輪不更改任何既有分數。

### 3.2 證據角色仍然相對於 claim

| 結論 | 已准入證據 | 預期角色 |
|---|---|---|
| 需求減弱，分數負 | 同範圍、同期間的客戶延後採購 | 支持此負向結論 |
| 需求減弱，分數負 | 同範圍、同期間的需求擴張 | 可能反駁此負向結論 |
| 供給壓力緩解，分數正 | 同期間瓶頸減少 | 支持此正向結論 |
| 供給壓力緩解，分數正 | 同期間瓶頸加劇 | 可能反駁此正向結論 |

上表為合成示例。方向相容只是機械檢查的一部分，不等於語意 entailment。Topic、期間、對象、限定條件、speaker、來源仍須核對；schema 沒有承載的語意不得假稱已由程式完整驗證。

---

## 4. Guard 修補：候選版本的完整性契約

### 4.1 拆成獨立變更 G，不包進 FSI 方法

將修補命名為獨立的 **G：Evidence Admission Integrity Fix**。實際 guard 版號由本地版本治理決定，本文件不占用 V7 等正式版本。

要求：

- baseline guard 及其歷史收據可識別；候選 guard 有獨立 `guard_profile_id`、規則／程式 hash。
- B 與 C 共用同一個候選 guard；不能 B 用舊 guard、C 用新 guard。
- 原 `AIAnalystPolicyV3` 檔案不原地改寫。候選收據同時記錄 base policy 與新 guard profile，不假裝只有 prompt 變更。
- 若本地 V3 對 `mixed`／overlap 有明確、與下列候選規則相衝突的語意，將衝突單列；不得不標版本地改寫 V3。核心最終支持不變量及其他隔離工作仍應完成。

### 4.2 非零 feature 的硬性不變量

對**候選 guard 接受且分數非零**的 feature，必須同時成立：

```text
final_supporting_evidence 非空
final_supporting_evidence ∩ final_contradicting_evidence = 空集合
全部 final references 可解析至此 run／source package 的已准入 evidence
至少一個 final support 符合既有可機械驗證的方向、topic 與其他准入條件
保存後的支持關聯與最終驗證時完全一致
```

檢查時間點必須在**所有**過濾、去重、角色整理、reference resolution 之後，且在 accepted feature 的保存完成前再檢查。

不得先通過一個支持檢查，就假設後續步驟不會把支持移除。

### 4.3 `mixed` 的候選處置

本工單採保守候選規則，避免為了提高完成量放寬證據門檻：

| 情況 | 候選預設處置 |
|---|---|
| 非零結論只有 `mixed` 支持 | 不足以機械確認單一方向支持；拒收／缺值，保留原始資料與理由 |
| 有合格單向支持，另含 `mixed` | `mixed` 不單獨充當決定性方向支持，也不僅因為 mixed 就自動成為反駁 |
| Mixed span 內同時有支持和反對內容 | 原文與模型原始角色保留在 companion audit；不自動拆句、重新標成 positive／negative |
| Mixed 經過整理後唯一支持消失 | 最終支持不變量必須攔截，不能保留非零 accepted feature |
| 模型以 mixed 表達有條件的單向主張 | 保留待人審；不得在 S1 用模型重新詮釋來補過 gate |
| 分數零且只有 mixed | 不自動當作 neutral；依現行零值契約核對，不用 0 代替不知道 |

若現有 schema 只有 supporting／contradicting 兩種欄位，**不新增第三個 FeatureSchemaV2 欄位**。未能確定角色的 mixed reference 及原因放入 candidate sidecar audit；原始 synthesis 不變。

最終正式角色清單中可以不把未解 mixed 放入任一側，但 audit 與人工畫面必須完整呈現它。不得藉「不是 final support」隱藏有意義的限定條件或反證。

這個 guard 只能落實可機械確認的保守限制，不能保證每一個通過的結論都被原文真正支持。

### 4.4 支持／反駁重疊

- 同一欄位內重複引用同一 evidence：可穩定去重，保留 input／output 數量及 trace。
- 同一個 feature claim 的同一 evidence 同時位於兩側：標記 role conflict，候選預設拒收該 feature，不採「反駁優先」或「支持優先」靜默解決。
- 不同 feature 或不同期間的 claim 可以對同一來源形成不同關係；不能做全域 evidence 角色標籤後套用到所有 feature。
- 此處 evidence identity 應使用現有 canonical reference，不只比對顯示文字；相同原文不一定是同一證據實例。

Overlap 的拒收是結構衝突，不表示人類已判斷結論錯誤。若未來要允許同一引文承載不同子主張，應另做可表達子主張的契約，不在 S1 偷加。

### 4.5 最終驗證與保存

建議的處理次序；實際函式名稱依本地程式映射：

```text
讀取原始 candidate（原件不變）
  → 驗證 references／source／span／speaker／PIT 等既有條件
  → 對每個 feature 建立獨立 evidence-role trace
  → 處理同側去重、跨側 conflict 與 mixed 非決定性角色
  → 套用既有可機械驗證的方向／topic 等條件
  → 檢查最終支持、最終交集、最終 references
  → 由既有程式計算 confidence，不讓模型填寫
  → 交易式保存 accepted feature 與 final evidence links
  → 回讀或既有一致性檢查確認保存結果與驗證結果一致
```

保存步驟若再出現關聯過濾、reference 解析失敗或最終支持為空，不能提交 accepted feature 的半套狀態。該次 transaction 回復；另以可稽核但非 accepted feature 的方式保存失敗原因。

預期拒收應走既有可處理的 rejection／missing 路徑，不把輸入品質問題變成整個流程未處理的例外。Unexpected persistence inconsistency 則記為工程錯誤，不能被當作一般缺資料吞掉。

### 4.6 拒收碼與 audit

優先重用既有碼，新增時用 candidate namespace，至少能區分：

```text
FINAL_SUPPORT_EMPTY
EVIDENCE_ROLE_OVERLAP
NO_DIRECTIONAL_SUPPORT_MIXED_ONLY
EVIDENCE_REFERENCE_INVALID
PERSISTED_SUPPORT_INVARIANT_FAILED
```

每個案例保留 raw lists、准入狀態、最終 lists、移除原因、舊結果、新 guard 結果及 guard profile。不得用一個 generic failure 讓人無法辨識是 provider、schema、guard 還是保存問題。

---

### 4.7 Confidence 變動稽核（本次審查新增）

`confidence()` 仍由既有程式計算，保留函式與公式身分，不引入模型自評。但 mixed／角色整理會改變傳入 items、contradictory、去重集合及扣分，即使函式沒改，結果也可能變動。

- 對每個可比較案例記錄：舊保存 confidence、新 candidate confidence、兩邊 evidence IDs／角色／去重集合、計算函式 hash、差值及原因。
- 新 guard 拒收時，新的 accepted confidence 為 null／NOT_APPLICABLE，不能填零來假裝產生新正式值。
- 說明變動來自哪些支持／反證／mixed 處理；此變化歸入 G 的影響，不宣稱是 FSI 或真人語意信心改善。
- 在回歸中包含合格單向支持＋mixed 的案例，驗證支持仍完整、mixed audit 可見、confidence 計算與記錄的輸入一致。

---

## 5. 16 個已收錄案例與 10 個缺值案例：只做離線重驗

### 5.1 精確識別

案例 manifest 必須綁定以下既有資料，不從季度名稱猜 ID：

```text
db_instance_id + db_snapshot_digest
analysis_run_id + snapshot_id（指該 run 的 snapshot；僅當該 run 沒有 snapshot 時為 null）
feature_id（原特徵未被接受保存時為 null）或 rejected_claim_id
feature_name + raw_candidate_reference
source_package_hash + raw_synthesis_hash
原始保存結果與 evidence relation references
```

如果新發現以 feature row 計數，報告也必須以同單位計數；不要把 evidence row 數當成 feature 數。

### 5.2 必須產出的差異表

| 欄位 | 內容 |
|---|---|
| 案例來源 | baseline／repeat／Q2 rejected case |
| 原始結果 | accepted／rejected／missing，不改寫 |
| 原支持／反駁 | raw synthesis 裡的 IDs 與 implication |
| 原最終支持／反駁 | DB 實際保存的關聯 |
| 新 guard 結果 | accepted／rejected／blocked，及理由 |
| 結果差異原因 | mixed、overlap、最終支持空、其他 |
| Confidence 變動 | old confidence、new confidence／null、兩邊實際計算輸入、反證扣分與差異原因；歸因 Guard G，不算 FSI 品質增益 |
| 人工狀態 | 待審；不預填 correct／unsupported |
| 對應審查卡 | 原有明確 run ID 卡片的 reference，沒有則列為額外診斷案例 |

### 5.3 A* 的定位

可以將凍結 raw outputs 交給 G 做 **A*：offline guard revalidation**。這是安全的機械檢驗，不呼叫模型，也不寫正式 DB。

A* 不等於一個新的 AI 分析 run，不算重跑，不增加七季完成量，不增加真人審查數，亦不算 FSI 品質結果。

對那 16 個最終支持為空的非零案例，至少要證明新不變量不會再接受同樣的最終狀態；是否因其他有效支持而在新規則下得到不同結果，需以完整 trace 說明，不能先指定全部應轉成某個分數。

若只有合成 fixture、未取得真實封存 inputs，應寫「合成重現完成，真實案例重驗未執行」，不把 16 個實例標成已逐項驗證。

---

## 6. 候選身分與 execution profile

### 6.1 不存在現成入口，S1 必須做最小入口

本輪審查指出 prompt、run identity、cache hash 依賴全域版本常數，V6 runner 又固定驗證 V6。因此只新增 `B_prompt.md`／`C_prompt.md` 不足以形成有效候選。

要求一個**明確、不可變、可注入的 candidate execution profile**，由獨立 candidate entrypoint 傳入，串到實際使用版本與收據的地方。

這是執行 metadata／dependency injection，不是新 FeatureSchemaV2。不建立多 agent 控制平台或通用 workflow engine。

### 6.2 最小 profile 內容

| 類別 | 至少記錄 |
|---|---|
| Candidate | profile ID、B／C method ID、method text hash、profile format version |
| 基線 | repository、code bundle identity、V6 reference、V2 schema hash、V3 policy hash |
| Guard | guard profile ID、規則 hash、實際 guard implementation hash |
| Prompt | 不可變 profile 保存各 stage 模板、方法／bundle hash；每次 stage 真正組裝後，把完整有效 request／prompt hash 與上游血緣寫入對應 call receipt，不能預先虛構動態 hash |
| Inputs | source package、cutoff、允許 Quant context、batch plan hashes |
| Runtime | provider adapter、CLI version、requested model、reasoning、timeout、retry、batching、可觀察工具／隔離設定 |
| Storage | candidate root、DB instance、output／cache／receipt roots |
| Limits | S1 `live_calls_allowed=false`、`max_live_calls=0` |

未知設定以 null／UNKNOWN 保留，不能補猜；缺少影響隔離或比較的必要欄位時，live entrypoint 必須拒絕啟動。S1 可以生成未 ready manifest，但不能把示意 placeholder 當成可執行配置。

### 6.3 必須貫穿的範圍

```text
candidate entrypoint
    → execution profile
    → prompt assembly／request envelope
    → service／provider adapter 呼叫邊界
    → extraction／synthesis／challenge stage identity
    → run／feature metadata（或明確外部 sidecar binding）
    → cache keys／admission artifacts
    → DB＋run＋snapshot manifest
    → candidate reader／review cards／comparison／acceptance
```

若現有欄位只能保存固定 V6 字串，不可寫入候選內容卻標為 V6。可在不動正式 DB schema 的前提下，以候選側 metadata 映射加明確 manifest 綁定；reader／驗收必須檢查該 binding。若做不到，回報精確阻礙，不創造雙重真實版本。

### 6.4 正式預設保持原樣

可以為既有 service 增加顯式 profile 參數並保留原預設；或以薄 adapter 重用既有函式。不得用執行期間修改 module-level constants、全域 monkey patch、共用 `.env` 切換或改全域 CLI 設定來實現候選。

並行建立 B／C profile 不得互相污染。對既有 default route 做 regression，確認未傳候選時仍使用原本 profile、storage roots 及 reader 行為。

保持正式預設不變是變更控制，不是認定舊 guard 沒問題。正式採用 guard 修補需另有 promotion／revalidation 決策。

### 6.5 Hash 與 cache

區分：

- **Profile／method identity**：候選規則與 prompt bundle 的身分。
- **Stage input digest**：該 stage 的有效 prompt、實際輸入、來源與所依賴設定。
- **Invocation identity**：每次真實新呼叫不同的 run／call ID；不混進用來判斷同一方法的穩定 hash。
- **Derived-result identity**：准入與 feature 計算額外依賴 guard、schema、policy 及相關程式版本。

快取至少不能跨 B／C profile、跨不同有效 prompt、不同資料包或不同准入 guard 誤用 derived features。Guard 變更後，舊 accepted features 不可當成新 guard 的結果；凍結 raw response 可專門用於標示清楚的離線重驗。

所有實驗 cache 位於候選 root。未來第一輪 B／C live comparison 預設不共用生成結果 cache；fresh-repeat 也不得以 cache／resume reuse 代替。離線 fixture reuse 與真實 fresh call 是不同狀態。

---

## 7. 儲存隔離與明確 IDs

### 7.1 隔離的範圍

正式 DB 不寫入任何候選。候選根目錄涵蓋 DB、output、cache、logs、receipts、config 及 review sidecars。

檢查實際 resolved path 與檔案 identity，防止相對路徑、symlink、hard link 或既有 config alias 指回正式檔案。B／C 也不得只靠檔名區分；第一版可分開候選 DB，或同候選 DB 內由 profile＋明確 IDs 隔離，但均不得進正式 DB。

優先使用已存在的封存一致性快照。需要讀正式 SQLite 時，沿用已核准的唯讀／一致性匯出方法；不可只複製活動主檔、忽略 WAL，也不可藉此做 checkpoint、改 journal mode 或其他正式 DB 操作。

只用 mtime 或不一致讀取的主檔 hash，不能證明正式資料未變。使用現有 logical preservation／一致性 manifest；有並行外部寫入導致無法歸因時如實記錄，不偽造「完全無變更」。

### 7.2 全部候選 reader 共用明確解析器

明確 reference 至少是：

```text
DB instance identity + baseline/candidate profile identity
+ analysis_run_id + snapshot_id + expected input/contract hashes
```

candidate detail view、review cards、summary、aggregate、comparison 都必須由同一個經驗證 manifest 解析。缺 ID、ID 不存在、quarter 不符、hash 不符或 profile 不符，全部 fail closed。

**不得 fallback 到 latest、earliest、最後一次成功或第一筆同季度資料。** 不同 DB 的整數 ID 相同，不等於同一個 run。

本輪可以重用正式畫面的格式化函式，但不全面改寫正式 `research-view` 選擇邏輯。S1 的保證是「候選不會被正式預設讀取」及「候選自有讀取精確」，不是聲稱正式便利查詢的歷史問題已全部修好。

---

## 8. 比較規則：B／C 與重跑必須分開

### 8.1 組別

| 名稱 | 定義 | 用途 |
|---|---|---|
| A | 既有 V6 封存結果與當時 guard | 描述性基線，不改寫 |
| A* | 同一 raw output 在候選 G 下離線重驗 | 量測 guard 行為差異；零分析模型呼叫 |
| B | 角色澄清 prompt＋G | 控制組 |
| C | B＋經篩選的 FSI 方法＋同一 G | FSI 方法候選 |
| B-repeat／C-repeat | 相同候選的全新模型呼叫 | 檢查各候選的重跑差異 |

FSI 的方法增量看 **C vs B**。A* vs A 是 guard 變更診斷，不是 FSI 增益。

### 8.2 Method comparator

B／C 方法比較允許不同：candidate ID、method ID、指定方法段落、有效 prompt hash，以及必然不同的 run IDs／storage paths／時間戳／輸出。

B／C 必須相同：來源包、cutoff、Quant context、schema、base policy、guard 實作、runner 實作、provider／CLI、requested model、reasoning、timeout、重試策略、分批計畫、可觀察工具與隔離配置。

`C = B + curated FSI rubric` 應以明確 diff／allowlist 表示；其餘共用 prompt 部分不應偷偷改動。若 C 與 B 實際有效 prompt 完全相同，報告沒有方法差異，不聲稱測到了 FSI。

輸出差異不構成「不可比較」；它正是要觀察的結果。被比較前提的意外漂移才構成 invalid comparison。

### 8.3 Repeatability comparator

同候選重跑固定 profile、方法與各 stage prompt 模板、原始 source package、cutoff、允許 Quant context、extract batch plan、schema、base policy、Guard G、runner／provider／CLI、reasoning、timeout、retry 及可觀察設定。Invocation IDs 必須不同，且有新的呼叫生命週期證據。

依階段驗證，不能要求整個多階段流程的所有完整 request hashes 都一樣：

1. **Extraction**：固定原始資料與方法後，各批實際有效 request hashes 必須相同。
2. **Synthesis**：本次新的 extraction 產物可不同，因此完整 prompt／stage-input hash 可不同；模板與方法固定，輸入須精確來自本次已准入 evidence。
3. **Challenge**：同理，完整 hash 可因本次新 evidence／features 而變動；Quant context 與模板固定，資料血緣不得混入舊 run。
4. 必須驗證動態差異僅來自本次上游產物、正常產生的 run-local references 等已明列因素。方法、原始來源、設定意外漂移仍使比較無效。
5. 來源內容偶然相同不證明 cache reuse；不同 invocation ID 也不單獨證明 fresh。需核對新 call／完成收據及 reuse／cache 標記。

既有 Q2／Q3 重跑已呈現 `same_extract_prompt_hashes=true`、`same_exact_prompt_hashes=false`，可比條件仍通過。這是本次接納的規則修正；不更動歷史收據。

以下皆不算 repeat：cache 命中、復用原始 response、恢復同一未完成呼叫、跨 B／C 比較、跨 provider 比較、A* 離線重驗。

不得直接將固定驗證 V6 或要求 prompt 一樣的現行重跑函式當作 B／C 方法比較器。可以重用底層 diff 工具，但比較模式與前提驗證必須明確分開。

### 8.4 底層模型未驗證的處置

未來收據必須分別記錄：

```text
requested_model
observed_model_identity（沒有則 null）
actual_model_identity_verified（維持實際證據值）
model_identity_evidence_reference（沒有則 null）
observable_configuration_match
actual_model_equality（無證據則 unknown，不填 true）
comparison_qualification
```

例如兩組都符合相同 requested model 與可觀察設定，但底層身分不可驗證，應標為：

```text
OBSERVABLE_SETTINGS_MATCHED_ACTUAL_MODEL_UNVERIFIED
```

這個標籤允許把結果作為**附限制的觀察比較**，不自動滿足任何要求「已證明底層模型相同」的 gate。未知也不等於已證明模型不同。

模型自稱自己的型號、同一 requested alias、沒有觀察到切換事件，不能自行升格成 verified。S1 不為消除此限制新增 provider 探測。

未來 S2 是否接受此比較限制，由 owner 事前批准。記錄呼叫時間、順序及批次，避免把服務端不可觀察變化完全歸因於方法；小樣本比較不宣稱因果證明或統計顯著。

---

## 9. 真人審查與機械指標

### 9.1 保留 35 項正式真人審查

原有 35 張明確 ID 卡片繼續使用。候選程式可新增 companion guide 與案例附件，不預填真人 verdict、reviewer、審查時間或完成數。

將 16 個新問題案例列入提示，至少讓真人看到：原結論、原分數、原文、模型原始角色、DB 最終角色、guard trace，以及「這是機械問題，尚未判定語意正誤」。

案例可能對應多張卡，也可能不是原 35 張卡中的 run；必須精確 mapping，不用新增案例數改變 35 的分母，不為填滿數量重複計數。

### 9.2 四個層次分開

| 層次 | 回答的問題 | 不能推論 |
|---|---|---|
| 來源定位 | 引文和 speaker 等 reference 是否通過既有檢查？ | 不等於引文足以推出結論 |
| 最終支持不變量 | accepted 非零 feature 保存後是否仍有機械合格支持？ | 不等於 human correct |
| 真人語意審查 | 主張、方向、期間及條件是否確實被來源支持？ | 不自動證明全部應抽取資訊已找到 |
| Gold-item recall | 人工事先確認的應抽取資訊是否被捕捉？ | 不等於現行類別 missed rate |

保留以下兩種漏失率與 NULL 規則；S1 只做必要標示與 guard 診斷，不擴大指標平台：

- 現行類別漏失率：真人判為 missed 的有效已審查類別數 ÷ 有效已審查類別數；對應既有 `miss_rate`，不偷換分母。
- Gold-item recall：正確捕捉的適用人工 gold items ÷ 適用且應抽取的人工 gold items；omission 為相同二元匹配定義下未捕捉的比例。
- Gold items 須由真人在看候選結果前建立或確認，綁定來源、定位、topic、期間、條件及預期含義；去重同一資訊，不讓重複引文膨脹分母或分子。
- 無人審、無 gold set 或沒有適用分母時，相關比率為 null／NOT_MEASURED；35 張類別卡不是 gold-item 分母。
- 缺逐字稿的 Q&A 項目不適用，放 companion metadata，不新增 review verdict，也不減少原 35 張卡要求。合法新聞稿／財報中的 management evidence 仍可審查。

### 9.3 新增的機械診斷

至少列出 accepted nonzero features、其中 final supporting 為空者、mixed-only cases、overlap cases、最終拒收原因及 missing count。候選 guard 對自己接受的非零結果，final-support-empty count 必須為 0。

比例若需要顯示，必須寫明分母。分母為零顯示 null／NOT_MEASURED，不用 100% 代表沒有產出也全數合格。

嚴格 guard 導致 missing 增加可能是正確拒收，不是立即退步；missing 下降也可能是放寬規則，不是立即改善。沒有真人審查，不選出 B／C 的品質勝者。

---

## 10. 最小實作工作包

| 工作包 | 交付 | 實作限制 |
|---|---|---|
| W1 基線與保全 | 本地 manifest、明確 case/run IDs、正式 artifact preservation references | 不重做全庫介紹、不變更原工作樹 |
| W2 Guard G | 最終支持 invariant、mixed／overlap 行為、保存一致性、回歸測試 | 候選 versioned path；不寫正式 rows |
| W3 Candidate profile | profile injection、獨立離線入口、身分／hash 全鏈路 | 不改 module globals，不建立新 runtime 平台 |
| W4 Storage／reader | candidate root／DB、explicit-ID resolver、read／review／aggregate 對齊 | 不以版本欄位代替物理隔離 |
| W5 Comparator | method 與 repeat 兩種前提驗證、模型身分限制 | 本輪只用合成收據測，不做 live |
| W6 Audit／review | 16／10 案例離線 impact、原／新 confidence 及原因、35 卡 companion guide、測試報告 | 不代填人審，不回填舊分數；Guard G 影響與 FSI 效果分開 |

本地定位提示來自 owner 審查，行號不是固定基線：

| 位置 | 核對／修改焦點 |
|---|---|
| `src/valuation_engine/ai/guards.py`，約 line 94 | mixed、角色整理、最終支持與保存前驗證 |
| `src/valuation_engine/ai/prompts.py`，約 line 18 | 全 28 feature 有利／不利方向；候選文字不覆寫原 V6 |
| `src/valuation_engine/ai/contracts.py` | V6／V2／V3 與型別限制；不擴充 feature output schema |
| `src/valuation_engine/ai/service.py`，約 line 200 | 全域版本使用點、profile 傳遞、cache／run／feature identity |
| `src/valuation_engine/cli/ai.py`，約 line 334 | 候選需避開 latest selector；重用格式化但明確選擇 |
| `src/valuation_engine/ai/validation.py` | explicit-ID review、舊指標語意保持 |
| `scripts/run_codex_repeatability_v6.py`，約 lines 216、258 | 不冒用 V6 限制；模型身分 unverified 保持 |

新增檔名由 Codex 遵循既有 layout 決定，報告列出實際 path 與 diff。不要把表內每個位置都視為必須改動；能重用則重用。

---

## 11. S1 離線測試矩陣

全部初始狀態為 **NOT RUN**。以下是規格，不是測試收據。Synthetic、真實封存重驗、live 與 human 是不同證據來源。

### 11.1 Guard（G）

| ID | 案例 | 預期 |
|---|---|---|
| S1-G01 | 全部 28 個 FeatureName | 正＝有利、負＝不利；供給壓力範例不反轉 |
| S1-G02 | 正向 claim 有合格正向支持 | 保留支持並通過其餘既有條件；不冒充人審 |
| S1-G03 | 負向 claim 有合格負向支持 | 壞消息可支持負向結論 |
| S1-G04 | 正／負 claim 只有 mixed 支持 | 不接受沒有方向支持的非零 feature |
| S1-G05 | 合格單向支持＋mixed | 保留合格支持；mixed 不自動變成反駁；audit 可見 |
| S1-G06 | 同側 duplicates 與跨側 overlap | 前者穩定去重，後者 role conflict；無靜默優先規則 |
| S1-G07 | 初步有效、後處理刪完 supporting | 最終檢查拒收，不產生 accepted 非零 feature |
| S1-G08 | 無效 source／span／speaker／reference／PIT | 即使分數方向相符仍拒收；既有 guard 不減少 |
| S1-G09 | Neutral、mixed、NULL | 不互相自動替代；零分行為符合已綁定契約 |
| S1-G10 | 保存時關聯失敗／保存後支持消失 | transaction 不留下 accepted 半套資料；診斷原因可追溯 |
| S1-G11 | 固定的 16 個已接受案例 | 真實可用者逐項重驗；空支持非零狀態不再被接受；原件不改 |
| S1-G12 | 10 個 Q2 拒收案例 | 原始拒收／NULL 保留；不 bulk swap 或自動恢復分數 |

### 11.2 隔離與身分（I）

| ID | 案例 | 預期 |
|---|---|---|
| S1-I01 | Baseline commit＋dirty content | 實際 V6 綁定完整，不以遠端／HEAD 猜測 |
| S1-I02 | 候選指向正式 DB／symlink／hard link／相對別名 | 拒絕啟動或寫入 |
| S1-I03 | 跨 DB 相同整數 run IDs；錯 profile／snapshot／hash | 明確拒絕錯配，不靜默 fallback |
| S1-I04 | 候選 read／review／aggregate | 同一 manifest 得到同一組結果，無 latest／earliest 選擇 |
| S1-I05 | Candidate profile 全鏈路 | Prompt、request、run、feature binding、cache、receipt、驗收一致 |
| S1-I06 | B／C 並行構造；未提供 candidate 的預設呼叫 | 不污染 globals；正式 defaults 與路徑不變 |
| S1-I07 | Prompt／input／guard／policy hash 改變 | 相關 cache／derived identity 失效；不冒用舊結果 |
| S1-I08 | 候選 output／log／config／cache 路徑 | 皆留在獨立 root；不寫原有交付與正式 DB |

### 11.3 比較與能力限制（C）

| ID | 案例 | 預期 |
|---|---|---|
| S1-C01 | B／C 只有允許的方法 prompt 差異 | Method comparator 可比較，不因 prompt hash 不同而誤拒 |
| S1-C02 | B／C 來源、guard、reasoning、timeout、retry 或 batching 漂移 | Method comparison 標為 invalid，逐欄說明 |
| S1-C03 | 同候選 repeat 的固定條件與動態 stage-input 差異 | C03a：模板／profile／原始輸入／設定漂移須拒絕；C03b：extract requests 相同，後段僅因本次新上游產物而不同可比較；C03c：上游血緣錯配須拒絕。三個子案例仍屬一個矩陣項目 |
| S1-C04 | Unique invocation IDs 但回應來自 cache／resume | 不算 fresh repeat；A* 也不算 |
| S1-C05 | 兩方 requested model 相同、actual unverified | 保留 unknown 與限制，不填 actual equality=true |
| S1-C06 | 收據缺必要欄位或只有 placeholder | 可生成未 ready 計畫，但不可通過執行 gate |
| S1-C07 | 七季未有 transcript；有合法其他 management source | 不生成 Q&A 品質結論，也不把整個 management 一律歸零 |
| S1-C08 | 未提供 guidance數字／delta／consensus；生成 confidence | 保持 V2／V3 與既有 Quant context；不增加數值契約 |

### 11.4 稽核與範圍（A）

| ID | 案例 | 預期 |
|---|---|---|
| S1-A01 | 35 張卡、16／10 案例映射及去重 | 原 ID 與人工欄位保留，不增加虛假完成數 |
| S1-A02 | 類別 missed 與 gold-item omission；沒有分母 | 分開標示；未人審／無 gold 時 null |
| S1-A03 | 離線入口企圖呼叫分析 provider／auth probe | 在呼叫前硬失敗；合成 transport 零 live 分析呼叫 |
| S1-A04 | SQLite 與隔離 PostgreSQL 測試 | 有收據才列 PASS；環境不可用列 BLOCKED／NOT RUN，不接正式 DB |
| S1-A05 | 原 Quant／Regime／AI rows 與原有交付保全 | 一致性方法查核；不以 mtime 冒充完整保全 |
| S1-A06 | Candidate 完成後的 promotion／正式預設 | 沒有自動切換、merge、live pilot、Final Pass 或 M5 |

**本矩陣共 34 項。** 每项可由多個 unit／integration cases 覆蓋，不能以矩陣條目數冒充 pytest passed 數。

S1-C07／C08 的離線收據只證明 fixture、資料適用性標示與可機械驗證的契約行為；沒有 live 呼叫，不能宣稱已證明真實模型不會產生無來源 Q&A、delta 或其他語意錯誤。C03 的三個子案例不增加矩陣總數，總數仍為 34 項。

### 11.5 與 v0.2 的對應

| v0.2 要求 | 本輪對應 |
|---|---|
| FSI02-01～06 | I01～04、I06、I08、A05 |
| FSI02-07～14 | G01～12；FSI02-10 的個別 polarity 表述由 G01 取代 |
| FSI02-15～18 | C07～08；既有 schema／PIT tests 保留 |
| FSI02-19 | I05～07、C06 |
| FSI02-20～23 | A01～02、真人審查指南；完整 gold-set 品質仍未驗證 |
| FSI02-24～26 | C01～06；live／語意部分留給 S2，不以合成通過代替 |
| FSI02-27～28 | A03～06、I08 |

不能把 v0.2 的 28 項整體標成 PASS。S1 完成的是離線子集與新增 guard 回歸，真人／live 品質項仍未完成。

---

## 12. 離線執行與測試保護

測試預設禁止網路與分析 provider transport；PostgreSQL 只允許已確認隔離用途的 `QVE_TEST_POSTGRES_URL`。SQLite 與 PostgreSQL 分開記錄結果，不能把未跑的 PostgreSQL 算作通過。不得為通過測試連正式服務、下載新依賴或偷偷執行 live markers。

可以用 fake provider、凍結 receipt、fixture、transaction fault injection 驗證流程，但須清楚標記 synthetic。Fake model output 不放入正式或真實 candidate cohort。

測試命令、程式版本、資料 fixture hash、開始／結束、退出碼及完整結果應有收據。未有相依套件／測試服務時，報告缺項，不把 skipped 包裝成 passed。

Fixture 需要故意包含壞資料，確保新 guard 的回歸真的會在舊漏洞行為下失敗，並在新候選下通過。不能只測一個「正常支持清單」正向路徑。

S1 不需要為了查驗 provider 的 `--version`／auth 狀態而再啟動官方 CLI；本輪使用既有收據，必要的 live readiness 留到另行批准階段。

---

## 13. S2 計畫只預留，不執行

### 13.1 呼叫量

依本輪 Codex 審查所述 Q2 現行分批：

```text
每組：20 extraction + 1 synthesis + 1 challenge = 22 次
B、C 各一次：22 × 2 = 44 次
B、C 各一次，且各再 fresh repeat 一次：22 × 4 = 88 次
```

這是**條件式呼叫數估算**，不是費用／時間估算，也不是已批准額度。未含重試、修復呼叫、探測或新的分批方式；若來源包與 batch plan 改變，須重新計算。

**S1 的實際預算：0 次股票分析 pipeline live 呼叫。**

### 13.2 S2 啟動前仍需的條件

- S1 必要離線 gate 有收據，正式基線保全成立。
- B／C profile、同一 guard、同一 source package 與其餘控制設定固定。
- Pilot 綁定明確 Q2 quarter／run references，不只用「Q2」縮寫。
- Owner 批准呼叫範圍、最大重試數、total-call cap 與模型身分未驗證的比較限制。
- 人工評估 rubric 與缺值／反證判讀標準在看到 candidate 結果前固定。
- 原 35 項真人審查持續推進；它與 candidate 品質評估不互相冒用。

未知底層模型不意味比較毫無價值，但必須附限制；它不應成為偷偷換 provider 或放寬隔離的理由。

---

## 14. S1 完成定義與回復

### 14.1 完成不是模型品質通過

S1 可標為 `OFFLINE_ENGINEERING_READY` 的條件：必要 guard、identity、storage／reader 與 comparator 的離線測試通過；缺項明列且不影響安全啟動；有足夠保全與版本收據；未發生任何禁止的 live 或正式寫入。

若有「會讓候選讀到錯 DB」「profile 不一致」「支持空仍能保存」等 blocker，只能 PARTIAL／BLOCKED，不能因 unit test 數多而標 ready。

完成後仍不得宣稱：

- FSI 比 B 或原本方法更準確。
- 同一候選語義穩定性已通過。
- 16 個結論已被真人判錯或判對。
- 35 項真人審查已完成。
- M4.1 Final Pass、正式 guard promotion 或 S2 已獲批准。

### 14.2 停止條件

Formal path alias、未授權正式寫入、意外分析 provider 呼叫、candidate 身分錯配、來源包漂移、凍結契約遭改寫，均立即停止受影響路徑並留收據。

有單一測試失敗可在本工單允許的候選範圍修復再跑，不能為了讓數字好看刪除失敗 fixture、放寬門檻或轉連正式 DB。

### 14.3 回復

停止 candidate entrypoint，即停止候選使用；正式預設不依賴新 candidate root。隔離分支的 diff 可供 owner 丟棄或另案合併，不能用 reset 清掉原工作樹。

候選 artifacts 暫保留作稽核，依既有政策處理；不刪除舊 240 份交付，不回寫舊 run。Formal guard promotion 與歷史重驗／重算是後續獨立決策。

---

## 15. Codex 本輪交付

主要交付：`docs/FSI_S1_OFFLINE_IMPLEMENTATION_REPORT.md`，外加實際候選 diff、測試與 audit artifacts。路徑可依既有 layout 調整，但需在報告給清楚入口。

報告必須包含：

1. **Bound baseline**：commit／dirty manifest、V6／V2／V3 hash、正式 refs、工作區與 preservation 方法。
2. **Implemented diff**：實際修改檔案、guard G 行為、candidate profile 傳遞、哪些 defaults 未變。
3. **Guard findings**：16 與 10 案例的明確 ID、去重、raw／final／new guard 差異，以及原／新 confidence、實際輸入與變動原因；真實資料與 synthetic 分開。
4. **Tests**：34 項矩陣對應實際 tests／receipts；unit count、skipped、BLOCKED、NOT RUN 全部列明。
5. **Identity and comparability**：B／C prompt 差異 allowlist、repeat 判定、模型未驗證限制與 cache 策略。
6. **Human-review companion**：35 卡的附加指引與受影響案例連結；人工欄位沒有預填。
7. **Preservation and side effects**：正式 DB／原交付是否可證實未變、candidate-only 輸出、分析 pipeline live calls 實際數。
8. **Remaining decision**：是否達 S1 ready；若能提出 S2，僅列待批准 manifest 與 44／88 次條件式計畫，不執行。

避免只交一篇設計摘要而沒有實際 diff／測試；也避免只交測試總數而沒有對新漏洞的具體回歸證據。

---

## 附錄 A：新 Session 可直接使用的接續指令

> 使用者已在原對話同意按修正計畫執行 S1；以下文字用於新 session 接續，範圍維持離線候選實作。

```text
請閱讀 /Users/eason/Documents/Coding/StockOS/docs/FSI_S1_OFFLINE_EXECUTION_PLAN_AND_HANDOFF_v0_3_1.md，接續執行已授權的 S1。
這輪不再做廣泛唯讀概念審查；授權範圍僅是隔離開發環境的候選程式實作、
離線測試、明確 ID 讀取、封存 raw output 的離線 guard 重驗及審查輔助資料。

目標：1121eason/StockOS。以已核對的本地 PromptSetV6 / FeatureSchemaV2 /
AIAnalystPolicyV3 固定實際 baseline；不要用遠端舊版本覆蓋本地，不可自動
pull/reset/stash/rebase 或清理既有修改。若無法安全隔離本地實際 V6，回報
具體 blocker，繼續不受阻的離線工作。

本輪先做：
1. 將 guard 修補獨立成 G。補上 mixed、支持/反駁重疊、後處理支持變空、
   保存後支持關聯一致性的回歸。非零 accepted feature 在最後必須保有合格
   supporting evidence。B/C 共用 G；不放寬 source/span/speaker/PIT 規則。
2. 全 28 features 統一正值有利、負值不利；supply_constraint 正值是壓力
   緩解。Supporting/contradicting 相對於結論，不以好壞消息直接分欄。
3. 重驗已定位的基線 12 + 重跑 4 個空支持案例，以及既有 Q2 10 個拒收案例。
   明確 IDs、去重、保留原始結果。離線重驗不是新模型 run，更不是人工 verdict。
4. 建立最小不可變 candidate execution profile 與獨立入口，貫穿 prompt、
   service、run、feature binding、hash、cache、receipt 及驗收；禁止 monkey
   patch 全域版本，不讓候選輸出冒用 V6 身分。正式預設保持不變。
5. 用獨立 candidate DB/root；reader、review、aggregate 全部用同一 explicit-ID
   manifest，缺項 fail closed，絕不 fallback 到最新或最早 snapshot。
6. 分開 method comparator 和 repeatability comparator：B/C 可以 prompt 不同；
   同候選 repeat 固定方法模板、原始輸入及設定；extract request hashes 相同，
   後段完整 hashes 可因本次新 evidence/features 而不同，必須驗證本次上游血緣。
   同時記錄 guard 變更前後 confidence 與原因，避免把 G 的影響算成 FSI 增益。
7. 保留 actual_model_identity_verified=false 或實際未知值，不從 requested
   model 推論底層身分相同。S1 只用既有／synthetic receipts，不做新 provider probe。
8. 執行可用的離線 SQLite 與隔離 PostgreSQL tests；後者僅用 QVE_TEST_POSTGRES_URL。
   無環境標 BLOCKED/NOT RUN，不能改用正式 DB。
   產出 34 項矩陣對應（含 C03 三個子案例）、diff、guard impact audit、真人審查
   companion 與保全收據。先跑能在舊 guard 重現的新回歸，再完成候選修補。

硬性範圍：0 次股票分析 pipeline live 呼叫。不得啟動歷史模型 runner、auth/
capability probe、provider fallback、付費 API、plugin/MCP 安裝。可用 fake provider。
不得寫正式 DB、回填 16 個支持欄位、恢復 10 個分數、修改原始 240 份交付、
覆寫凍結 V6/V2/V3、代填 35 項人審、修改 Quant/Regime 或自動 promotion。
本輪也不授權 commit/push/PR/merge/deploy、S2 live pilot 或 M5。

請交付 docs/FSI_S1_OFFLINE_IMPLEMENTATION_REPORT.md 及可追溯 artifacts。
清楚分開 synthetic tests、真實封存重驗、live evidence、human review。
若 S1 通過，只提出待批准 S2 計畫；不要執行 44 或 88 次呼叫。
```

---

## 附錄 B：候選 Manifest 最小示意

以下是外部執行／稽核 metadata 的示意，不是 FeatureSchemaV2，也不是現成可用的 config。Null 欄位須在適當階段由 host 綁定；不可讓模型自行聲稱版本或身分。

```json
{
  "manifest_version": "FSI-S1-CandidateManifest-draft-1",
  "status": "UNBOUND_OFFLINE_ONLY",
  "repository": "1121eason/StockOS",
  "baseline": {
    "git_commit": null,
    "worktree_content_digest": null,
    "prompt_version": "PromptSetV6",
    "schema_version": "FeatureSchemaV2",
    "policy_version": "AIAnalystPolicyV3"
  },
  "candidate": {
    "profile_id": null,
    "arm": "B",
    "method_id": "claim_relative_role_clarification",
    "method_hash": null,
    "effective_prompt_bundle_hash": null,
    "guard_profile_id": null,
    "guard_implementation_hash": null,
    "schema_hash": null,
    "base_policy_hash": null
  },
  "inputs": {
    "source_package_hash": null,
    "analysis_cutoff": null,
    "allowed_quant_context_hash": null,
    "batch_plan_hash": null
  },
  "runtime": {
    "provider_adapter": null,
    "cli_version": null,
    "requested_model": null,
    "observed_model_identity": null,
    "actual_model_identity_verified": false,
    "reasoning_settings": null,
    "timeout_settings": null,
    "retry_policy": null,
    "observable_settings_hash": null
  },
  "storage": {
    "candidate_root": null,
    "db_instance_id": null,
    "analysis_run_id": null,
    "snapshot_id": null
  },
  "execution": {
    "live_calls_allowed": false,
    "max_live_calls": 0,
    "is_fresh_model_run": false,
    "production_mutations_allowed": false,
    "promotion_allowed": false
  },
  "human_review": {
    "verdict": null,
    "reviewer": null,
    "reviewed_at": null
  }
}
```

Profile／input digest 的穩定內容不應包含每次不同的 invocation 時間與 ID；執行收據另記這些欄位。比較器按第 8 章逐欄驗證，不直接用整份 receipt 的 hash 判斷「同方法」。

---

## 附錄 C：來源、查核限制與修訂摘要

**[R1] Owner 於前輪貼回的首次 Codex 唯讀審查。**提供本地 repository、V6／V2／V3、7/7、2/2、0/35、缺 transcript、六項原始 findings 及 10 個 Q2 缺值案例。這些是使用者提供的本地查核結果。

**[R2] Owner 於本輪貼回的第二次 Codex 唯讀審查。**提供 12＋4 個最終支持清單為空的非零 feature、mixed 的處理次序、28 個 feature 的一致 polarity、全域版本與 runner 限制、`actual_model_identity_verified=false`，及每組 22 次的呼叫估算。本文以此形成 S1 規格；未自行重查正式 DB 或執行 tests。

**[D02] 已提供的 v0.2 MD。**作者在本輪讀取對話環境中的該檔案，據此修訂第 4 章 polarity、FSI02-10、candidate entrypoint 與比較定義。原件保留，不覆寫。

**上游參考範圍不變。**仍僅借用先前已討論的 Anthropic FSI 分析檢查方法；本輪沒有重新查核上游 main、安裝或執行其 Agent。本次 guard 修補與 candidate engineering 的依據是本地審查，不是對上游功能的新增認證。

| v0.2 | v0.3 |
|---|---|
| 原則上要求保留 supporting | 明確要求所有後處理與保存後的 final-support invariant |
| Mixed／overlap 只有一般測試要求 | 明訂保守候選角色處理、拒收原因與 transaction consistency |
| 容易誤解成個別 feature 可反轉 polarity | 固定 28 個全為正有利、負不利 |
| 假設可用配置接入 candidate | 指定最小 profile injection，全鏈路身分與 hash 綁定 |
| 方法比較／重跑概念可能共用 | 分開 comparator、allowlist、freshness 和 prompt 相等規則 |
| 相同實際模型作為前提 | 逐項保留可觀察設定與 actual unverified 限制 |
| 下一輪仍是 S0 唯讀評估 | 提供 owner 可明確下達的 S1 限縮實作指令；S2 仍未開放 |

**交接狀態：S1 已獲使用者授權，尚未開始候選實作、新測試與 A* 重驗。本輪只產出完整交接文件並唯讀核對基線；後續完成宣告須有真實 diff、收據及明確驗收。**


## 附錄 D：本整合版來源與修訂紀錄

| 來源／修訂 | 證據與處理 |
|---|---|
| 原 v0.3 | [原始工單](/Users/eason/Desktop/StockOS_QVE_FSI_S1_Offline_Implementation_Work_Order_v0_3.md)；SHA-256 `4f4de82dd8aa1a515994e6870eba35a54e2c6fbcafab34c84d0cab8a38c30a0d`，原件不改 |
| 使用者授權 | 本對話「ok 按照這個計劃進行」及要求完整 MD 以換 session，限縮為 S1，記錄於 H.1 |
| v0.3.1 修訂一 | §8.3、profile hash 定義、S1-C03 與接續指令已整合多階段重跑的固定／動態輸入區分 |
| v0.3.1 修訂二 | §4.7、W6、案例差異表及交付要求已納入原／新 confidence 與原因 |
| 完整性補充 | 納入原 v0.2 的必要指標／NULL／PIT 限制、實際 baseline、精確案例及接續順序，不需依賴舊 session |
| 上游方法參考 | `anthropics/financial-services@574ed3624aebd0418c7e96cd101262f30210ab26`；本次沒有新增上游版本或安裝任何工具 |
| 狀態 | 完成這份計畫不等於 S1 程式已實作。所有 34 項新增驗收仍 NOT RUN |

這是一份已整合的執行與交接文件，不是新的股票分析 schema、模型驗收收據或正式工程交付報告。

