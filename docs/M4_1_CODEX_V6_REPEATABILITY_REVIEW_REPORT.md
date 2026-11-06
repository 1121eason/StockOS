# M4.1 V6 同條件重跑與真人審查準備

日期：2026-09-27（Brisbane）。使用者於七季 7／7 PASS 報告後要求「ok 繼續」。本輪範圍是 R09 的 Q2／Q3 同條件重跑比較，以及 R10 的 35 張待填審查卡；不代填真人判定，不做 commit、push、部署或季度擴展。

**終局：R09 兩季同條件重跑比較 2／2 完成，R10 待填審查卡 35／35 已產生；獨立 DB 複核與保全 PASS。唯一真實 attempt `20260927T081514Z-8a8c675a0951` 於 09:18:04Z 正常結束，37／37 呼叫有效，沒有重試。真人仍 0／35，語義穩定性未判定，M4.1 尚未 Final Pass。**

Review：`data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/`；實際啟動紀錄於 `launch-02/`。

## 執行條件與修補

- 新入口 `scripts/run_codex_repeatability_v6.py` 接收明確的七季完成收據，重驗完整 plan、歷史 PASS 前綴、後四季 context／preflight／result、正式 DB rows、目前來源及隔離綁定。七季資料另產生固定 hash，不能只看報告上的 PASS。
- Q2 基線 run 15／snapshot 4，Q3 基線 run 17／snapshot 5。實際舊 metadata 都是 extract 180 秒、synthesize／challenge 600 秒、兩次嘗試上限。重跑明確採 `CodexStageBudgetV1`，沒有偷偷沿用上一輪新四季的 V2 600 秒擷取時限。
- 固定 requested model `gpt-6-astra`、CLI `codex-cli 0.155.0-alpha.9.2`、PromptSetV6、AIAnalystPolicyV3、FeatureSchemaV2、PITQuarterPackageV1、CodexPITSandboxV2、package／context／來源及分批。Actual model 未由 CLI 暴露，保持 requested_only。
- 每季必須重新呼叫 provider、取得新 run／snapshot；重用呼叫不能算重跑。第一個非 PASS 停止，沒有外層重試。
- 比較會核對固定條件與實際執行 budget、相同的 extract request hashes，並列出 evidence Jaccard、特徵方向／幅度差異、缺漏變化、challenge overlap、拒絕數量。後續 synthesize／challenge 的輸入依賴新產生的 evidence，完整 prompt hash 可能不同，會明示而非誤判成固定輸入漂移。
- 完成比較不等於語義一致或正確；`semantic_stability` 維持 `human_interpretation_required`，不使用任意相似度門檻自動判真人 PASS。

## 測試與套用

| 項目 | 結果 |
|---|---|
| 隔離初始測試 | 13 errors；入口尚不存在，原 log 保留 |
| 最終新增回歸 | 33 項，納入受影響與完整回歸 |
| 隔離受影響測試 | 初次 205 passed；補強 context 綁定後 206 passed |
| 正式 DB 唯讀 plan 演練 | PASS，DB bytes 不變，沒有 CLI／模型呼叫 |
| Patch check／apply | 全部 exit 0，兩個新增檔案 bytes 與測試副本一致 |
| 正式完整 SQLite | 417 passed、0 failed、1 PostgreSQL-only skipped；44.17 秒 |
| Ruff／mypy／diff check | 全部 exit 0；mypy 71 source files |

首次唯讀 plan 演練從隔離副本目錄出發，因歷史 pilot 收據的 checkout-relative preflight 路徑無法解析而停止，沒有 DB 寫入。保留失敗 log 後，以正式根目錄解析原收據、仍執行隔離副本程式，再次演練 PASS。正式 plan 與該次演練 bytes SHA-256 相同：`2f0014b0a8e3295a28edd04a555a6c294e5fabdc6b8dd96a21da50fb92dd2b1e`。

本輪只新增 runner 與測試，未修改 `src/`、schema、Gemini 程式／測試。PostgreSQL 沒有重跑；前輪專用庫 350 passed 的版本範圍保留，不能算作本輪完整測試。

## 程序查核與實際啟動

第一次 preflight 在 08:11:16Z 取得 611 列、0 解析錯誤，但 PID 46062 被分類為尚未辨明的 Codex 程序，父程序為桌面工具服務，未放行。沒有新 attempt、沒有模型呼叫。原查核、log 與 launcher-error 全部保留。

08:14:00Z 的受審核唯讀 PID 查詢 exit 1、沒有匹配：該 PID 已不在程序表中。沒有送訊號，歷史 exit code 保持 null。新的啟動前查核沒有豁免此類程序，而是再次完整查詢：599 列、0 解析錯誤、0 未解決程序，live isolation PASS，989 份歷史檔案不變。

唯一真實 attempt：`20260927T081514Z-8a8c675a0951`；launcher PID 47649，08:15:14Z 建立，08:15:22Z 開始 FY2023-Q2 第一批 extract，08:50:30Z 開始 FY2023-Q3，09:18:04Z terminal completed。外層 exit 0；`process_state_unknown=false`，該 attempt 正常解除自己的 lock。整批約 63 分鐘，沒有內層重試或外層重啟。執行中只讀 journal／receipt；terminal 後才以唯讀 DB 獨立重算比較。

| 項目 | 基線 | 新結果 | 目前狀態 |
|---|---|---|---|
| FY2023-Q2 重跑 | run 15／snapshot 4 | run 24／snapshot 11；22／22 valid calls | 執行與可比條件 PASS，獨立重算相符 |
| FY2023-Q3 重跑 | run 17／snapshot 5 | run 25／snapshot 12；15／15 valid calls | 執行與可比條件 PASS，獨立重算相符 |
| 真人審查卡 | 前五季核准基線 | 35 張卡 | 已產生，判定待填 |
| 真人判定 | 0／35 | 本輪沒有新增 | 未完成 |
| M4.1 Final Pass | 七季 7／7 PASS、重跑比較 2／2 完成 | 真人 0／35、語義判斷待完成 | 未結案 |

## 比較結果及需要真人釐清的差異

兩季各 11 項固定條件均相符，包括全部 extract request hashes 與 V1 實際 budget。以下指標已從正式 DB 獨立重算，與不可覆寫的 [Q2 比較收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T081514Z-8a8c675a0951/quarters/FY2023-Q2/comparison.json)、[Q3 比較收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T081514Z-8a8c675a0951/quarters/FY2023-Q3/comparison.json)相符。

| 指標（基線 → 重跑） | FY2023-Q2 | FY2023-Q3 |
|---|---|---|
| 正式 evidence 數 | 540 → 531 | 406 → 402 |
| 原文 span hash Jaccard | 83.30% | 82.78% |
| 有值特徵／28 | 27 → 17 | 16 → 15 |
| 明確缺漏／28 | 1 → 11 | 12 → 13 |
| 共同有值特徵方向一致 | 16／17（94.12%） | 14／14（100%） |
| 共同特徵平均絕對差（值域 -1 至 1） | 0.06176471 | 0.04285714 |
| 正負翻轉 | competition_outlook：-0.20 → +0.10 | 無 |
| 新增缺漏／新增有值 | 10／0 | 2／1 |
| Challenge 維度 Jaccard | 100% | 100% |
| direction_unsupported 隔離候選 | 0 → 10 | 9 → 9 |

**這是比較執行完成，不是語義穩定 PASS。** 方向一致率只計算兩邊都有值的特徵，不能掩蓋缺漏變化。Jaccard 是兩組引用 hash 或 challenge 維度的交集／聯集，也不是語義正確率。

Q2 新缺漏為 `china_outlook`、`custom_asic_outlook`、`customer_financing_quality`、`customer_insourcing_outlook`、`demand_visibility`、`export_control_outlook`、`guidance_visibility`、`management_credibility_signal`、`pricing_power`、`supply_constraint`；加上原先缺漏的 `switching_cost_strength` 共 11 項。被隔離候選及方向規則需與原文一起核對，不能把未納入正式值等同來源完全沒有資訊。Q2 的 `competition_outlook` 從 -0.20 變成 +0.10，應優先檢查。

Q3 新缺漏為 `pricing_power`、`working_capital_quality`，新增有值為 `competition_outlook`（+0.10）。共同特徵雖無正負翻轉，`long_term_demand_durability` 從 +0.40 降至 +0.20；完整幅度差異保留於比較收據。

[優先複核索引](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/REPEAT_REVIEW_FOCUS.md)列出上述 14 個正負翻轉或缺漏狀態變化，包含前後原始解讀、隔離候選、350 個去重引用與 source／block／hash／available_at。350 個引用錨點全部解析，無失效連結；匯出使用唯讀 DB，前後 DB bytes 不變，沒有代填真人 verdict。

Q2 最慢 extract 為 151.06 秒，整合 301.38 秒，challenge 45.06 秒；Q3 最慢 extract 175.77 秒，整合 249.55 秒，challenge 37.75 秒。全部在原 V1 限制內，37 次呼叫 retry_count 均為 0。Actual model 仍未由 CLI 提供，只能核對相同 requested model，不能宣稱已確認底層模型身份完全相同。

## 真人審查包

[審查入口](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review/REVIEW_GUIDE.md)提供前五季 × 需求、供給、競爭、產品週期、管理層、異常、模型挑戰七類，共 35 張卡。

原 `export_review()` 使用最早 snapshot 選擇器，可能取到歷史版本，因此本輪匯出明確指定 run 15、17、18、20、21／snapshot 4–8，不依最早或最新猜測。各卡連到該季完整證據冊，包含特徵、原始 AI 解讀、可點選的 evidence 引用、source／block／SHA-256、available_at、明確缺漏及隔離拒絕紀錄。原始 source files 不變。

`verdict`、`reviewer`、`reviewed_at`、`notes`、`semantic_support` 均為 null；人工選取 evidence_ids 為空。沒有寫入 AIHumanReview。新目錄及不可覆寫的檔案避免覆蓋已填結果；請將真人填答另存成 submission，完成後再驗證匯入。生成卡片不是完成審查。

35 張卡繼續綁定原核准七季中的前五季；本次重跑結果作為補充比較，沒有以新結果覆蓋審查基線。審查包 manifest 的 48 份檔案 hash 與所有本地連結已核對。

## 正式資料與保全

[獨立複核](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/independent-review.json)：integrity PASS，blockers 為空。989／989 份歷史檔案 hash、十張 Quant／Regime／財務保護表，以及十二張 AI／建議表既有 rows 均未變。原七季核准結果重核相符；舊 FAIL 與 unknown 原因保持原紀錄。

| 本輪正式 DB 新增 | 數量 |
|---|---:|
| analysis run／snapshot | 2／2（run 24–25／snapshot 11–12） |
| provider calls | 37，全部 valid |
| evidence／有值特徵／feature-evidence 關聯 | 933／32／661 |
| challenges／隔離拒絕 | 16／19 |
| analysis events／adjustment proposals | 6／4 |
| 真人 reviews | 0 |

建議資料未套用到 Quant／Regime；`sources/`、HEAD、CLI config 及既有工作樹修改保持。只新增重跑入口與回歸測試，更新本報告及三份進度文件；沒有 commit、push、部署或 M5 工作。

## 交付與下一步

- [最終重跑收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T081514Z-8a8c675a0951/repeatability.json)、[完整生命週期](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260927T081514Z-8a8c675a0951/progress.jsonl)。
- [交付 manifest](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/delivery-manifest-final.json)、[保全結果](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/final-preservation.json)。測試與命令日誌保存在同一 review 目錄。
- R09 2／2 比較已完成、R10 35 張卡已生成。下一項為 R13：真人先看差異索引，再完成前五季七類的 35 項判定，記錄理由、引用、reviewer 與時間；依實際判定計算品質比率並處理不支持或漏失項目。
- 人工審查與語義穩定性尚未驗收。R14 必須連同適用版本的 SQLite／PostgreSQL 證據與全部門檻複核後才可結案；不因 2／2 收據 PASS 自動宣稱 M4.1 Final Pass。
