# StockOS M4.1：Codex Provider 修復與 Q2 驗收工程計畫書

日期：2026-09-24  
正式專案：`/Users/eason/Documents/Coding/StockOS`  
文件狀態：工程執行計畫；本次僅建立文件，未啟動新的模型呼叫或季度驗收。

## 1. 目標與完成定義

先解決 Codex CLI 執行請求卡住且缺乏可判讀紀錄的問題，再以現有 V3 政策與 V5 提示詞完成一個全新的 FY2023-Q2 驗收。Q2 通過後，依原規格逐季執行另外六季，最後完成兩次重跑比較及人工審查交付。

以下結果分開報告，不以其中一項代替另一項：

| 層級 | 完成條件 |
|---|---|
| Provider 可執行 | 合成輸入可完成，失敗可定位，沒有未確認狀態的重複執行 |
| 歷史輸入可使用 | C1–C12 齊全且通過，CLI／政策／有效隔離設定與收據相符 |
| Q2 通過 | 新 run、新完成快照、有效彙整、正式證據與必要挑戰均通過季度驗收 |
| 七季完成 | 七個指定季度逐季通過，所有結果可追溯且保護資料未變更 |
| M4.1 最終驗收 | 七季、兩次重跑比較、正式專案測試與原規格人工審查均完成；未解除缺口逐項列明 |

工程師負責程式修復、測試、執行與收據；人工審查者負責實際語意判定。AI 不代填人工審查結論。

## 2. 現況基線與證據可信度

本次編寫文件時已重新確認 Git 根目錄正確，分支為 `main`，工作目錄包含既有未提交 M4.1 修改。下列執行結果讀自正式專案的既有收據；不是本次重新執行模型所得。

| 項目 | 已確認結果 | 工程意義 |
|---|---|---|
| V3 政策 | `AIAnalystPolicyV3`、引文上限 `80` words、彙整／挑戰至少 `600` 秒 | 補丁已在正式程式碼中；仍須完成正式驗收 |
| 目前提示詞 | `PromptSetV5`；schema 為 `FeatureSchemaV2` | V5 是提示詞版本，不代表提高證據准入標準的容忍度 |
| 隔離收據 | `experiment-v3.json` 含 C1–C12，全數 PASS，政策 hash 與目前程式碼相同 | 執行前仍須比對 CLI 與有效設定，不能只看舊 PASS 字樣 |
| Q2 run 11 | V3，0/2 有效呼叫、無完成快照、FAIL | 啟動失敗已被保留 |
| Q2 run 12 | V3，22/22 有效呼叫、snapshot 1、FAIL | 缺 downside；另有一筆引文不在原文 |
| Q2 run 13 | V4，22/22 有效呼叫、snapshot 2、FAIL | 八筆挑戰被拒，必要挑戰與 anomaly 挑戰未成立 |
| V5 | 完成收據、provider-check、Q2 context 檔均不存在 | 尚無正式完成證據；重啟前仍須確認程序與資料庫，不能據此斷言沒有在途執行 |
| 資料保全 | V3、V3 retry1、V4 收據均記錄十張保護表內容與筆數未變 | 後續每次仍須重新計算 |
| PostgreSQL | 本次 shell 與 `.env` 均未設定 `QVE_TEST_POSTGRES_URL` | 目前確切缺口是測試資料庫未設定；連線限制須取得設定後才可判定 |

前次同任務診斷已確認：一般外層 sandbox 會使 CLI 的本機 app-server 初始化回傳 `Operation not permitted`；使用允許的外層執行方式、保持內層 `qve_pit` 限制時，合成呼叫與 run 12／13 可完成。後來兩次 V5 執行請求沒有返回可判讀的啟動結果，其卡住位置仍待查明，不能直接歸因於模型、帳號或自動審核拒絕。

前次診斷也發現 run 13 的挑戰描述含 `FY2023-Q2`，被禁止數字的敘述檢查拒絕。V5 已要求模型避免數字與季度標籤；其效果尚未由新 Q2 驗證。

前次測試基線為 **243 passed、1 skipped、2 failed**；Ruff、mypy、差異空白檢查通過。這些數字來自本任務前次執行紀錄，本次文件工作未重跑，後續須保存新的測試日誌。失敗項目：

- `tests/unit/test_gemini_provider.py::test_google_probe_and_isolation`
- `tests/unit/test_gemini_provider.py::test_service_ineligibility_is_not_login_failure`

## 3. 範圍與固定約束

- 完整保留既有 M4.1 修改、歷史 run、快照、收據及拒絕紀錄；不執行 reset、restore 或 clean。
- `sources/` 維持唯讀；不修改同步參考檔。
- 不提交、推送、部署；不擴展至 26 季或 M5。
- 歷史來源與截止時間不變；診斷輸出不能回填為正式證據。
- 保持原文逐字比對、來源區塊、時間點與來源 hash 驗證；不以修字、截字或替換符號的方式救回失敗引文。
- 超長引文只有在來源原文、來源區塊、時間點均驗證成功後可留在隔離紀錄；不得再次納入正式證據。`span_not_in_source` 仍是季度失敗原因。
- 程式目前使用 `len(span.split())` 計算 80 words；不是 80 個中文字元。500 字元 schema 限制與提示詞建議的 400 字元內短句另行保留，不混用三者。
- 外層執行權限與內層模型隔離分別留證；內層唯讀、無外部檢索與禁止提權的政策維持原規格。
- PostgreSQL 測試只使用確認為測試用途的專案設定，不能從正式資料庫 URL 自動補值。

## 4. 工作分解與執行順序

| 工作包 | 內容 | 產出 | 通過門檻／依賴 |
|---|---|---|---|
| P0 現況封存 | 保存 Git 根目錄、分支、差異、檔案 hash；讀取最新 run 與執行狀態 | 工作目錄基線、版本與收據清單 | 確認沒有衝突、重複執行或來源變動 |
| P1 啟動修復 | 最小合成探測、錯誤分類、階段紀錄、防重複啟動 | 啟動診斷收據與必要修補 | 可明確分辨請求未返回、程序啟動失敗、推論逾時、完成 |
| P2 回歸與隔離 | 相關測試、C1–C12 完整性、CLI／設定比對、必要隔離重測 | 測試日誌、版本指紋、隔離確認收據 | 相關測試通過，十二項 gate 完整有效 |
| P3 Q2 正式驗收 | 原來源／截止時間，新執行、新快照、新收據 | Q2、保全、拒絕分類與 provenance 收據 | 全部季度門檻通過；FAIL 即停止季度排程 |
| P4 六季與重跑 | 按原順序逐季執行；七季通過後新跑 Q2、Q3 | 七季結果、兩組比較、人工審查卡 | 每季通過才進下一季，重跑輸入與版本相同 |
| P5 測試補齊與交付 | 解決兩項 Gemini 失敗、完成測試 DB 回歸、人工審查交付 | 正式測試收據、工程報告與剩餘阻礙 | 不將略過／未執行項目記為 PASS |

P5 的資料庫設定與 Gemini 診斷可在等待模型時處理；一次只執行一個正式季度。相關程式有新修改後，才重跑受影響測試。整體測試尚有失敗或 PostgreSQL 缺口時，Q2 結果可以獨立記錄，但不能宣告完整工程驗收。

### P0：保存基線與確認在途執行

1. 在正式根目錄保存 tracked diff、untracked 檔案清單與內容 hash，範圍涵蓋本次預計修改的檔案；排除憑證與 `.env` 內容。
2. 以唯讀方式比對新收據、最新 `AIAnalysisRun`、provider calls 與可觀測的程序狀態。不能僅靠最終收據不存在就重跑。
3. 如果先前命令狀態仍未知，停止新的正式模型啟動，先取得可判讀狀態。終止工具等待不等於已確認子程序結束。
4. 發現使用者或其他工作的新修改時，先讀取差異；無法確認相容性就列出衝突並停止受影響修改。

### P1：讓啟動與失敗可以定位

1. 先使用不含 NVIDIA 歷史資料的合成輸入，沿用目前 CLI、環境過濾、schema 與內層 `qve_pit` 設定。
2. 外層啟動前建立唯一 attempt ID，採 UTC 時間加隨機識別碼；資料庫 run ID 由資料庫產生，不預設為 14。
3. 提案新增不可覆寫的 attempt 目錄與互斥執行保護。入口須檢查開始紀錄、部分產物與在途 run；不能只檢查 `pilot-v5.json`。
4. 分階段留下 `launch_requested`、`runner_started`、`provider_checked`、`inference_started`、`stage_completed` 與 `finished`。外層請求沒有返回時，記錄可觀測事實為狀態未知，不偽造 PID、退出碼或拒絕理由。
5. 保留 stdout／stderr hash，補上長度受限、去除敏感內容的錯誤分類與摘要。避免儲存登入憑證、完整環境變數或非必要來源全文。
6. 一般啟動路徑若因權限失敗，可使用工具正式提供的受審核外層執行方式；內層隔離設定保持一致。若工具明確拒絕，記錄原始拒絕原因並停止該路徑。
7. 保持 extraction 目前 180 秒、synthesis／challenge 600 秒的 stage 設定；把外層未返回與模型 stage timeout 分開。確認程序已結束後才允許下一次獨立嘗試，禁止無界自動重試。

驗收：一次成功的合成呼叫能留下完整生命週期；受控的啟動失敗與逾時能各自留下明確狀態；輸出不包含憑證；不會因缺少完成收據而同時啟動第二個正式季度。

### P2：程式回歸與 C1–C12

目前 runner 只要求 gates 非空且其中所有值為 PASS，還應明確驗證 key 集合恰為 C1–C12。補上 CLI 版本、transport policy hash、有效設定與收據的綁定；若任何一項改變或證據不足，先重跑相應隔離檢查並產生新收據。

| Gate | 要確認的條件 |
|---|---|
| C1 | 官方 CLI 的 ChatGPT 訂閱登入狀態；不讀取憑證內容 |
| C2–C3 | 合成 headless 呼叫完成，結構化輸出符合 schema |
| C4–C5 | 真實系統探測確認外部檔案／寫入／模型命令網路存取受阻 |
| C6–C7 | web、browser、MCP、apps／plugins／connectors 的有效限制 |
| C8 | 隔離區外隨機 canary 的內容無法取得 |
| C9 | 內層禁止提權，無提權請求或授予 |
| C10 | 來源注入指令不能造成外部檢索或未提供的證據 |
| C11 | 單季封裝與暫存工作目錄符合規格，使用者規則／記憶不混入 |
| C12 | 使用者設定前後 hash 相符 |

單純模型口頭拒絕不等於隔離成立；原生權限探測與有效設定收據均須保留。已知 `unified_exec` backend 不能僅憑設定宣稱關閉，依真實權限探測判定邊界。

### P3：Q2 正式驗收

固定輸入如下；執行前重新產生封裝並逐項比對：

| 欄位 | 值 |
|---|---|
| Quarter | `FY2023-Q2` |
| Information cutoff | `2022-08-25T13:30:00+00:00` |
| Approved source IDs | `10, 9, 107, 108` |
| Package | `PITQuarterPackageV1`，4 份來源、932 個 narrative blocks |
| Package hash | `331e90ebd3ca261c06cf090a5d46ae852a4ded7eb133c434e5f7537abd3ff4c5` |
| Policy／Prompt／Schema | `AIAnalystPolicyV3`／`PromptSetV5`／`FeatureSchemaV2` |
| Requested model | `gpt-6-astra`；未暴露實際模型身份時繼續記錄 `requested_only` |

使用 `refresh=True` 產生全新分析。執行前後對十張金融、Quant、forecast、valuation 與 Regime 保護表計算筆數和內容 hash。

Q2 必須同時符合：

- 新 run 與完成快照可追溯；有效彙整結果存在，所有要求的 provider calls 成功。
- 來源集合、封裝、截止時間、原文 span、來源 hash 與可用時間一致。
- 80 words 的超長引文隔離條件成立；任何被隔離引文都未重新出現在正式證據或其下游引用中。
- 特徵 schema 覆蓋完整；缺值明確保留，不能用虛構的中性值補齊。
- `upside`、`downside`、`regime` 挑戰各自成立，適用時具有 anomaly 挑戰；其他 challenge 與 adjustment 依原規格檢查。
- 特徵、章節、挑戰只引用正式准入證據；敘述仍通過原有數字與禁止內容檢查。
- 沒有不可隔離的拒絕原因；十張保護表內容與筆數未變。

任一項不符就寫入 FAIL 與具體 blockers，停止後續六季。失敗紀錄不可修改成成功；後續修復與新嘗試使用獨立版本／attempt 收據。有效呼叫筆數不直接等同 Q2 通過。

### P4：六季、重跑比較與人工審查

Q2 PASS 後依序執行：

1. FY2023-Q3
2. FY2024-Q1
3. FY2024-Q2
4. FY2025-Q4
5. FY2026-Q1
6. FY2027-Q2

每季保存自己的 cutoff、來源、封裝 hash、run／snapshot ID、拒絕原因、保全結果與 PASS／FAIL。任一季失敗就停止。

七季皆通過後，以相同 provider、requested model、CLI、政策、prompt、schema、來源封裝與 context，分別新跑 Q2 和 Q3。比較證據重疊、特徵方向與幅度、缺值、挑戰與拒絕數量；不以任意自動一致率宣稱語意正確。

輸出前五季 × 七類的 35 張人工審查卡，保留人工 reviewer、判定、時間與證據引用欄位待填。七季與重跑通過不會自動產生 M4.1 Final Pass。

### P5：正式測試與交付

先保存前次兩項 Gemini 失敗的可重現原因，確認是測試替身、環境依賴或實作錯誤，再修正對應問題。不以刪除測試、放寬斷言或無理由 skip 清除失敗。

PostgreSQL 先確認 `QVE_TEST_POSTGRES_URL` 指向專案指定測試資料庫，並確認測試使用獨立 schema。測試 fixture 會建立及移除 `pytest_*` schema，因此必須先確認目標身份。migration contract 另讀取測試 DB 的 `public.alembic_version`，不能只準備空 schema 就宣稱驗收。

`scripts/validate_postgres_m11.py` 目前含固定連線、建立資料庫與歷史資料匯入行為；本計畫不直接把該腳本當作通用測試命令。先使用明確配置的測試 DB，必要的初始化僅在該測試 DB 執行。未設定、連線被拒、權限不足或 migration 不符都分別報告；不改用正式 DB。

## 5. 變更位置與測試矩陣

| 位置 | 預計工作 |
|---|---|
| `src/valuation_engine/ai/codex_pit.py` | 啟動與失敗診斷、有限錯誤摘要；保留 transport 限制與 stage timeout |
| `src/valuation_engine/ai/cli_provider.py` | 必要的 capability／錯誤分類銜接 |
| `scripts/run_codex_pilot_v5.py`、`scripts/run_codex_validation_v5.py` | attempt 防重複、進度持久化、完整 gate 集合與版本比對；新收據獨立命名 |
| `src/valuation_engine/ai/prompts.py`、`contracts.py` | 先保留 V5，只有新證據顯示需要修改時才提出新 prompt 版本 |
| 相關 `tests/` | 驗證實際失敗行為、資料保全與禁止路徑；優先沿用既有案例 |
| `docs/` | 新增修復／執行報告，清楚標記歷史結果與最新結果 |

| 測試範圍 | 必要案例／驗收證據 |
|---|---|
| 啟動與 timeout | 啟動失敗、stage 逾時、成功退出、敏感內容去除、未知在途狀態禁止重跑 |
| 隔離入口 | C1–C12 缺一項、空集合、非 PASS、CLI／政策不符時拒絕歷史輸入 |
| 引文 | 80／81 words 邊界、原文不符、未知區塊、時間超出 cutoff、隔離後重新引用 |
| 完成條件 | synthesis 缺失、snapshot 缺失、必要挑戰缺失均 FAIL |
| V5 格式 | 季度數字標籤仍被 guard 拒絕；有效的無數字敘述可通過其餘條件 |
| 資料保全 | 正式證據與拒絕紀錄分開；Quant／Regime 等十表前後不變 |
| 正式專案 | 完整 pytest、Ruff、mypy、diff check；PASS／FAIL／SKIP 分列 |
| PostgreSQL | 指定測試 DB 的 migrations、PIT／immutable contract 與完整測試日誌 |

先跑受影響測試，再跑一次完整 SQLite 回歸；新修改或未解除失敗才需要重跑。建議命令如下，測試 DB 設定另外以不暴露憑證的方式傳入：

```sh
.venv/bin/pytest -q -ra tests/unit/test_codex_pit.py tests/unit/test_cli_provider.py tests/unit/test_ai_guards.py tests/unit/test_pit_pilot.py tests/unit/test_quarter_package.py tests/unit/test_prompts.py tests/integration/test_ai_analyst.py
.venv/bin/pytest -q -ra
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src
git diff --check
```

## 6. 收據與可追溯性

新產物提案位置：`data/m41/codex/attempts/<UTC時間>-<唯一ID>/`。實作時讓 Q2 與六季 runner 明確引用同一次驗收的產物，不依「最新檔案」猜測所屬執行。既有 `pilot-v3*.json`、`pilot-v4.json` 與其他歷史紀錄保留原樣。

每次 attempt 至少記錄：

- `manifest.json`：Git commit、相關未提交檔案 hash、CLI／policy／prompt／schema／model、來源收據連結。
- `progress.jsonl`：各階段 UTC 時間與結果；若尚無 DB run，明確記錄為空值。
- `launch.json`、`provider-check.json`、`isolation.json`：啟動與隔離的獨立結果。
- `context.json`、`pilot.json`、`preservation.json`：Q2 原輸入、正式判定、十表保全。
- `tests/`：命令、退出碼、通過／失敗／略過清單、去除敏感內容的輸出。
- 後續每季與重跑的獨立收據，以及 `engineering-report.md`。

完成收據採原子寫入且拒絕覆寫；中斷時保留 partial 狀態。若程序被強制結束而無法落盤，重啟後先以唯讀核對並新增中斷紀錄，不把缺失紀錄補寫成已完成。

## 7. 停止條件與復原

| 事件 | 必須採取的動作 |
|---|---|
| Git 根目錄錯誤、既有差異衝突 | 停止修改，列出實際路徑或衝突 |
| 在途執行狀態不明 | 禁止啟動另一個正式 run，先查明狀態 |
| 隔離 gate 缺失／失敗／版本不符 | 停止歷史輸入，保留診斷收據 |
| 來源、截止時間或 package hash 改變 | 停止，列出與原核准輸入的差異 |
| Q2 或後續任一季 FAIL | 記錄 blocker，停止後續季度 |
| 保護表改變 | 立即停止並輸出差異；不自動回滾資料庫或刪除紀錄 |
| 測試 DB 未設定或連線受限 | PostgreSQL 記為 BLOCKED／NOT RUN，保留確切原因 |
| 全套測試仍有失敗或人工審查未完成 | 保持整體驗收未完成，不能宣告 Final Pass |

程式修復若需撤回，只撤回本次有明確基線與差異證據的局部修改；若無法與既有 M4.1 修改分離，先停止並列出差異。歷史 run 與收據不刪除。

## 8. 時程與交付節點

以下為工程投入估算，不是完成承諾；外層執行限制、帳號可用性、測試 DB 與人工審查等待另計。

| 節點 | 估算 | 交付判定 |
|---|---|---|
| P0–P1 | 0.5–1 個工作日 | 啟動路徑可用，錯誤與在途狀態可辨識 |
| P2 與測試修復 | 0.5–1 個工作日 | 相關回歸與完整隔離門檻通過 |
| P3 | 執行耗時依實際回報，另預留結果核對時間 | 一份新的 Q2 PASS 或有明確原因的 FAIL 收據 |
| P4 | Q2 PASS 後估算；依第一季實測時間安排六季與兩次重跑 | 七季、重跑結果與 35 張待人工審查卡 |
| P5 | 0.5–1 個工作日工程整理，加外部依賴等待 | 正式測試結果、工程報告與剩餘阻礙 |

作為執行預算參考，若仍為 20 次 extraction 加 2 次長階段呼叫，單次皆用滿 timeout，合計為 `20 × 180 + 2 × 600 = 4,800` 秒，即 80 分鐘；這不含初始化、重試與收據處理，也不是預測耗時。實際排程應依新的成功啟動與階段耗時調整。

第一個交付節點是 P1 的可判讀啟動診斷。工程報告須逐一列出完成、失敗、略過與阻礙；保持測試通過、Q2 通過與 M4.1 最終通過三種結論清楚可辨。

## 9. 依據

- [原七季執行規格](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_7_QUARTER_EXECUTION_PLAN.md)
- [V2 根因與隔離診斷](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_PILOT_V2_DIAGNOSIS.md)
- [C1–C12 定義與歷史實驗報告](/Users/eason/Documents/Coding/StockOS/docs/M4_1_CODEX_CLI_PIT_EXPERIMENT_REPORT.md)
- [V3 retry1 正式收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/pilot-v3-retry1.json)
- [V4 正式收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/pilot-v4.json)
- [目前隔離收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/experiment-v3.json)
- [V4 核准來源與 cutoff 封裝](/Users/eason/Documents/Coding/StockOS/data/m41/codex/FY2023-Q2-context-v4.json)

上述歷史文件的舊版本狀態保留為當時紀錄；本計畫不將舊收據解讀為新版本已通過。
