# FSI S1 補修獨立驗證與進度更新

日期：2026-09-30，Australia/Brisbane。

**結論：本次檢查範圍內 R01／R02 已修復，接受新候選的 `OFFLINE_ENGINEERING_READY`，限 SQLite 離線工程。**

狀態由前輪的 `PARTIAL／NEEDS_FIX` 前進至 SQLite 候選工程通過。這不包含正式套用、PostgreSQL、模型品質、真人審查、S2 或 M4.1 Final Pass。

## 1. 驗證對象

- 新候選：`/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260929T124230Z-fc5be56d/candidate`
- [實作者補修報告](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-20260929T124230Z-fc5be56d/FSI_S1_REPAIR_REPORT.md)
- [前輪獨立審查與缺口定義](/Users/eason/Documents/Coding/StockOS/docs/FSI_S1_INDEPENDENT_REVIEW_2026_09_29.md)
- 本次獨立證據：`/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771`
- Git HEAD：`22e9b9ee944408cb67d5217ca66dd880498fb440`，既有工作樹修改保留。
- 候選 runner bundle hash：`7775b28f4782ac58904021577ad5332542888b99b6581a72c7a2531e5c1bc7b7`。

原報告、原候選、補修候選與舊收據均未修改。前一份 2026-09-29 進度報告記錄的是修補前狀態，本文件提供修補後的最新驗證結論。

## 2. 兩項缺口的修復證據

| 問題 | 程式核對 | 本次獨立重現結果 | 判定 |
|---|---|---|---|
| R01：摘要／challenge 驗證不足 | 新 `admission.py` 共用准入；完整 stage schema 驗證；重建並比對 admitted 與頂層產物 | 頂層拼接被判 `lineage.final_outputs`；不合規 challenge 被拒；錯誤產物不能保存讀回，method comparison 列 invalid | 已修復 |
| R02：證據寫入異常仍 commit | 同一 transaction／connection 回讀 run、實際 evidence、features、links、snapshot 並驗證 | 故障注入前後 run／snapshot／evidence／features／links 數量不變；只新增 1 筆工程錯誤；拋出 `PersistenceError`，沒有成功 reference | 已修復 |

新候選保留了原四個反例的測試期待。本次以 AST 比對三個測試函式，內容一致；其中一個參數化函式產生兩例，所以合計四例。沒有透過修改測試期待把失敗改成通過。

正常 section／challenge、無效引用、anomaly code、schema 缺漏／型別錯誤、讀取／review／aggregate 共用 gate 與 evidence 遺失的補充測試亦通過。

## 3. 測試與稽核結果

| 項目 | 結果 | 本次證據方式 |
|---|---|---|
| 原 S1 與封存 A* | 104 passed | 本次重跑 |
| 邊界回歸 | 12 passed，包含原四個反例 | 本次重跑；不是另外再加四項 |
| 本次獨立測試合計 | **116 passed，0 failed，0 skipped；exit 0，10.06 秒** | 新 harness 禁止網路、子程序與新 review root 以外的 DB 寫入 |
| 修補前四例 | 4 failed | 前輪已獨立重現；本次核對補修交付 JUnit，沒有再跑一次舊版 |
| 完整 SQLite suite | 529 passed、2 failed、1 skipped | 本次核對補修交付 JUnit，未重跑整套 |
| Ruff／mypy | 交付收據 exit 0；mypy 報告 79 個 source files | 本次核對收據與檔案 hash，未重跑 |
| Patch／diff check | 交付收據通過 | 本次核對收據；沒有套用 patch |
| PostgreSQL | NOT RUN | 本次未連線 |

完整套件的兩個失敗仍為 `test_google_probe_and_isolation`、`test_service_ineligibility_is_not_login_failure`；唯一 skip 是 `test_live_postgresql_migration_contract`。整庫全綠仍未達成，不能用本次 116 項通過代替完整 repository 結果。

A* 全量重驗包含在本次 104 項中。另比較原、新完整 audit JSON，唯一不同的頂層欄位是 `runner_implementation_hash`；所有 feature 結果、G hash、原卡及 counts 均相同：

- 98 個 accepted 維持 accepted。
- 73 個 accepted 改為 rejected，含原 16 個空支持案例，另有 57 個；其中 72 個角色重疊、1 個方向不受支持。
- 61 個原 rejected 維持 rejected，其中包含指定的原 10 例。
- 接受的 98 個非零 feature，空支持為 0；真人仍為 0/35。

這證明補修沒有改變 G 的歷史判定結果，並未證明 FSI 方法品質改善。

## 4. 保全與授權範圍

開始前核對原 1,097 個保護路徑、新候選 246 個檔案與補修交付 67 份 manifest 項目；連同外部 manifest 及既有進度文件，本次前後追蹤 1,413 個受保護檔案。最終結果見本次 `preservation-after.json`。

正式 DB SHA-256 維持 `31bcd861823f903904d1ffab16f6adf93db36044f083dac4869e0a7ff78cb679`。沒有正式 DB 寫入、模型呼叫、provider 探測、PostgreSQL、commit／push／PR／merge／deploy 或 S2。

補修報告提到的 `StockOS_FSI_PROGRESS_REPORT_2026_09_29.md` 是本對話上一輪新增的進度報告，屬已知文件新增。它已納入本次保全，沒有編輯或刪除。

`candidate-repair.patch` 是相對原 S1 候選的增量補修；目前結論不授權將它單獨套回正式 checkout。未來正式升格須檢查完整 S1 變更與補修的組合及正式基線。

## 5. 目前進度與下一步

| 工作 | 最新狀態 | 下一步 |
|---|---|---|
| R01／R02 | 已修復並獨立複驗 | 不再列為未修 blocker |
| SQLite 離線候選工程 | 通過，限本次候選版本 | 保留此版為後續準備的已驗證基線 |
| PostgreSQL | 未驗證 | 有隔離 `QVE_TEST_POSTGRES_URL` 才驗證；未跑前不宣稱跨 backend 通過 |
| 原 M4.1 人工審查 | 0/35 | 真人填寫判定、引用、理由與時間；模型可整理材料，不能代填人工完成數 |
| G 的 73 個變動 | 機械結果已確認，合理性待人審 | 優先檢查原 16 個案例及另外 57 個影響，判斷是否過度拒收 |
| S2 比較方法 | 未實測 | 先固定 B／C 評估 rubric、缺值／反證處理及可比條件 |
| S2 工程／啟動 | 未執行 | 準備 live adapter 工程驗證、實際設定、隔離條件、total-call／retry cap 與待批准執行方案；取得範圍批准後才呼叫模型 |
| 候選正式套用與升格 | 未執行 | 品質證據與正式驗收安排完成後另行決定 |
| M4.1 Final Pass | 未完成 | 原人工審查、語義穩定性與適用版本的原定門檻需分別滿足 |

**下一個可推進的工作是人工品質審查準備與 S2 離線準備，不是再修已通過的 R01／R02，也不是直接啟動真實模型。** 原 35 張卡與 G 的 73 個變動是不同粒度，不能合併成 108 個人審分母。S2 尚無新授權；本次只完成驗證與進度更新。

## 6. 本次可追溯證據

- [116 項獨立測試日誌](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771/s1-repair-independent.log)
- [測試命令、時間與退出碼](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771/s1-repair-independent-receipt.json)
- [R02 回滾觀察](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771/observations/persisted-evidence-observation.json)
- [原／新 audit 完整比對](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771/audit-comparison.json)
- [原交付測試與品質收據核對](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771/delivered-checks.json)
- [保全前清單](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771/preservation-before.json)
- [保全後結果](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771/preservation-after.json)
- [本次驗證 manifest](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/reviews/s1-repair-verification-20260929T142801Z-0a6ae771/review-manifest.json)
