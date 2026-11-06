# FSI S1 獨立驗證與補修工單

審查日期：2026-09-29（Australia/Brisbane）。

**審查結論：S1 SQLite 候選為 PARTIAL／NEEDS_FIX。原 104 項測試可重現通過，但新增 4 個反例重現 2 個工程缺口，尚不接受 `OFFLINE_ENGINEERING_READY`。**

本次核對實際候選程式、凍結基線、patch、測試收據與資料庫封存，並執行獨立離線測試。沒有改寫原交付報告、原候選程式或測試，沒有套用 patch、呼叫模型、執行 PostgreSQL、S2 或正式升格。

## 1. 審查對象與證據

- [原交付報告](/Users/eason/Documents/Coding/StockOS/docs/FSI_S1_OFFLINE_IMPLEMENTATION_REPORT.md)
- [已授權的 S1 計畫](/Users/eason/Documents/Coding/StockOS/docs/FSI_S1_OFFLINE_EXECUTION_PLAN_AND_HANDOFF_v0_3_1.md)
- 原候選：`/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate`
- 本次獨立證據：`/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e`
- Git HEAD：`22e9b9ee944408cb67d5217ca66dd880498fb440`，保留既有 dirty worktree。
- 審查的 patch SHA-256：`19e611ea35b1184fbada2f95f8c7e5701c0828c3fe4dc01106b1ab4467afbac3`。

## 2. 必須補修的兩項發現

### FSI-S1-R01（P2）— 收據未完整驗證摘要及 challenge 輸出

位置：[compare.py:178](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/compare.py:178)、[compare.py:206](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/compare.py:206)。

`receipt_errors()` 重算 extraction 與 feature 的准入，卻沒有 challenge 准入分支；最終輸出一致性僅比對 evidence／features，未比對 `sections`／`challenges`。`Store.save()` 及 `resolve()` 都依賴這個驗證器。

三個純合成反例均可重現：

1. 只替換頂層 `sections`，加入不存在的 evidence key 與無來源數字；未更動原 stage output。驗證仍回傳 `[]`，B/C comparator 仍回傳 `valid=true`，保存及讀回成功。
2. 只替換頂層 `challenges`，同樣通過驗證、比較、保存及讀回。
3. 將 challenge 的 raw output／admitted output 改成不符合 `ChallengeDraft` 的內容，重算這兩個自洽 hash，並同步頂層 challenges。驗證、保存及讀回仍通過。

這不是斷言正常 `analyze_offline()` 已生成這些錯誤；正常 service 有 schema／敘述與引用檢查。缺口在收據入口與後續讀取：它們未證明收到的摘要／challenge 確實出自同一份原始輸出並通過相同准入規則，因此可能把損壞或拼接的產物視為有效。

證據：[sections observation](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/sections-observation.json)、[challenges observation](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/challenges-observation.json)、[challenge admission observation](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/challenge-admission-observation.json)。

修補要求：

- 依凍結的每階段 schema 驗證完整 raw output，而非只驗證其中 feature／evidence 元素。
- 以相同的准入函式重建 sections／challenges，保留 evidence reference、safe narrative、anomaly code／quant context 等既有條件。
- 驗證 raw → admitted → 最終 payload 的一致性。必填產物缺漏、型別錯誤、未准入內容或不同 stage 的產物均應拒絕。
- `save`、`resolve`、review／aggregate、method／repeat comparator 必須使用一致的驗證；不能只增加表面的 hash 比對。

### FSI-S1-R02（P2）— 保存時使用記憶體中的 evidence，未驗證實際落盤內容

位置：[storage.py:124](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/storage.py:124)、[storage.py:154](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/storage.py:154)。

`save()` 回讀 feature 與 links，最後的 `final_invariant()` 卻仍使用寫入前的 `payload['evidence']`，沒有回讀同一 transaction 中實際保存的 evidence payload。

在全新的合成 candidate DB 加入測試 trigger，令 evidence 插入後將 implication 從 positive 改為 negative，結果如下：

| 項目 | 保存前 | 保存後 |
|---|---:|---:|
| runs | 1 | 2 |
| snapshots | 1 | 2 |
| evidence／features／links（各） | 1 | 2 |
| engineering errors | 0 | 0 |

`save()` 沒有拋錯，並回傳成功 reference；直到 `resolve()` 才拋出 `persisted feature invariant failed`。讀取端有攔下，但保存端已 commit，沒有履行保存失敗須回滾的契約。這是故障注入下的缺口，不代表正式或封存 DB 已发生這種損壞。

證據：[persisted evidence observation](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/persisted-evidence-observation.json)。

修補要求：

- 在 commit 前、同一個 transaction／connection 內回讀實際 run、evidence、features、links 與 snapshot，核對完整內容／身分與准入條件。
- `final_invariant()` 必須使用實際讀回的 evidence，並確認其與已准入輸入一致。
- 任一不符不得回傳成功 reference；整筆 run／snapshot／evidence／features／links 回滾，之後另存去敏工程錯誤。
- 不要用另外開一條連線的 `resolve()` 取代交易內檢查；它無法正確驗證尚未 commit 的資料。

## 3. 測試結果與證據強度

| 驗證 | 本次結果 | 說明 |
|---|---|---|
| 原 S1 指定測試 | **104 passed，exit 0** | 本次獨立重跑，6.15 秒 |
| 新增邊界回歸 | **4 failed，exit 1** | 原候選上重現上述 2 項缺口；不是已修復測試 |
| 真實封存 A* 全量重算 | **與原 audit 完全一致** | 以唯讀 archive SQLite 重算，沒有模型呼叫 |
| 原完整 SQLite 回歸收據 | 519 passed／2 failed／1 skipped | 本次核對 JUnit，沒有重新跑整套 |
| 原 baseline Gemini 收據 | 相同兩項 failed | 本次核對收據及凍結程式一致性，沒有重新執行兩項測試或定位環境根因 |
| PostgreSQL | NOT RUN | 本次未連線，不能算通過 |
| `git apply --check` | exit 0 | 本次重新執行，沒有 apply |
| Ruff／mypy | 原交付記錄 PASS | 本次沒有重跑；產品程式未修改 |

完整回歸的兩項失敗為 `test_google_probe_and_isolation`、`test_service_ineligibility_is_not_login_failure`；skip 為 `test_live_postgresql_migration_contract`。它們與本次新增的 4 個 S1 反例分開記錄，不可混算或用舊失敗解釋新缺口。

- [原 104 項獨立重跑日誌](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/s1-independent.log)
- [新增回歸原始碼](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/test_review_boundaries.py)
- [4 個失敗的日誌](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/review-boundaries.log)
- [A* 重算摘要](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/archive-recomputation.json)
- [原交付 JUnit 核對](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/delivered-test-receipts-summary.json)

## 4. 73 個拒收的正確解讀

| 原狀態 → 新 G 狀態 | 數量 |
|---|---:|
| accepted → accepted | 98 |
| accepted → rejected | 73 |
| rejected → rejected | 61 |
| 總候選數 | 232 |

- 73 個是原本 171 個 accepted 的一部分；包含原 16 個空支持案例，**額外受影響的是 57 個**。
- 73 個中，72 個因 `FSI.EVIDENCE_ROLE_OVERLAP` 被拒，1 個因 `direction_unsupported` 被拒。
- 指定 16 個空支持案例全部被拒，指定 10 個原 Q2 拒收仍拒收，符合本次 G 的預期。
- 新 G 接受的 98 個非零 feature，空 supporting 為 0。
- 真人審查仍為 0/35。這些數字證明新規則的效果與影響範圍，不能證明 73 個舊結論全錯，或 FSI 方法品質變好。
- 原報告末段的「73 個額外拒收」應釐清為「73 個原 accepted 改為拒收，含原 16 個，另有 57 個擴大影響」。

## 5. 進度與下一步

| 階段 | 項目 | 審查後狀態 |
|---|---|---|
| S1／W1 | 基線、隔離、原件保全 | 已核對 |
| S1／W2 | G 的空支持、角色與方向攔截 | 原測試通過；保存後完整性仍需 R02 |
| S1／W3–W5 | Profile、保存／讀取、comparator | 已有候選；R01／R02 需補修 |
| S1／W6 | A* audit、35 卡 companion | 重算一致；尚未真人審查 |
| S1 工程驗收 | SQLite candidate readiness | **PARTIAL／NEEDS_FIX** |
| 跨 backend | PostgreSQL | 未驗證 |
| 方法品質 | 73 個變動的判讀與人審 rubric | 待完成，不以機械拒收當作正確率 |
| S2 | 真實 B/C pilot／fresh repeat | 未執行，仍需另案條件與批准 |
| 正式升格 | 套回正式程式、正式 DB／M4.1 | 未執行 |

白話說明：擋掉「沒有支持卻給分」的主要規則已經有效；但檢查交付產物與保存資料的兩道程序還有漏網情況。應先把這兩項修好，再決定何時做真人判讀與真實模型比較。

## 6. 可交給下一位模型的 S1 補修工單

本節是針對既有 S1 的補修範圍，不授權 S2、正式套用或新模型呼叫。

1. 先讀本報告、原 S1 計畫與原交付報告，核對 HEAD／dirty worktree 與候選 hashes。保留原交付為凍結證據，從本次審查的 candidate 建立新的隔離修補副本及唯一 review 目錄。
2. 把本次 4 個最小反例移為新候選的回歸測試，僅調整 import／檔案定位／輸出目錄；先在未修版確認相同失敗，再修程式。不要反向修改期待以湊通過。
3. 完成 FSI-S1-R01 的完整 schema／准入／頂層產物驗證。另補正常合法 section／challenge 可接受、缺漏／錯型別拒絕、無效 evidence／anomaly 拒絕，以及 comparator 與所有 reader 使用相同 gate 的測試。
4. 完成 FSI-S1-R02 的交易內完整回讀與原子回滾。保留原 links／feature 故障測試，增加 evidence 內容變動或遺失的測試；失敗時不得新增成功 run／snapshot。
5. 重跑原 104 項、4 個反例及新增正反案例，再做適用的完整 SQLite 回歸、Ruff、mypy、patch check。完整回歸若仍有 baseline 失敗，分開記錄，不宣稱全綠。PostgreSQL 僅使用已確認隔離用途的 `QVE_TEST_POSTGRES_URL`；無環境列 NOT RUN，不改接正式服務。
6. 重算 A* audit。若沒有改 G 規則，16／10 與 73（含 16、額外 57）的實質結果應保持；程式 bundle hash／新候選 identity 變化應誠實記錄，不冒用舊 receipt。
7. 更新新的交付報告與驗收矩陣，附補修前後證據、diff、測試退出碼、原件／正式 DB／舊交付保全。不要修改原收據或代填 35 張真人卡。

硬性範圍：0 live 模型／auth／discovery／版本探測；不修改 `sources/`、Quant／Regime、凍結 V6／V2／V3、正式 DB 或原 240 份交付；不自動 commit／push／PR／merge／deploy、套回正式 checkout、S2 或升格。

完成條件：兩項缺口均有修補前失敗、修補後通過的證據；原 S1 正常路徑不退化；保存異常不留下成功資料；所有產物的驗證一致；保全無差異。符合這些條件後，才重新判定 SQLite 的 `OFFLINE_ENGINEERING_READY`，跨 backend 與模型品質仍分開列狀態。

## 7. 保全範圍

本次開始前已核對 235/235 原 Git-visible 檔案、240/240 舊交付、9/9 候選新增檔、候選內 233 個已複製基線檔、patch、正式 DB 與 archive DB 的 bytes hashes。候選刻意未複製 `.agents/agents/qve-pit-analyst/agent.md` 和 `.env.example`，沒有把缺少這兩檔當作內容變更。

前後另比對 1,095 個受保護檔案；包括原交付程式、原收據與主要產物，不含原先可重建的測試暫存目錄／工具 cache。本次所有測試寫入新 review root，模型與子程序均由獨立 harness 禁止；沒有修改產品程式。

- [保全前清單](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/preservation-before.json)
- [保全後比對](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/preservation-after.json)
- [本次交付 manifest](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-independent-20260929T122112Z-6bc4469e/review-manifest.json)
