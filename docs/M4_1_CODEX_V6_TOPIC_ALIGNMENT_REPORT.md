# M4.1：PromptSetV6 特徵與引用對齊

本輪基線建立於 2026-09-26T03:05:52Z；正式 checkout 為 `/Users/eason/Documents/Coding/StockOS`。使用者已指示開始改善特徵引用與涵蓋率。本輪範圍為一般化修補、回歸、新的單季 Q2 與獨立複核；六季擴展另行處理。

**已完成修補及真實 Q2 驗證。V6 run 15／snapshot 4 的季度 gate、引用改善與獨立保全複核均 PASS：特徵由 6／28 提升至 27／28，跨 topic 拒絕由 21 件降為 0。** 唯一缺漏為沒有同主題正式證據的 `switching_cost_strength`；沒有補造數值。M4.1 Final Pass 尚未達成。

## 已確認問題與修補

V5 run 14／snapshot 3 的 27 個候選中，21 個因跨 topic 引用而被拒，6 個入庫；`switching_cost_strength` 沒有候選與同主題正式證據，共 22 個特徵明確缺漏。V5 提示沒有明確說明兩組引用都必須與 feature_name 同 topic；現有 guard 已有這項要求。

V6 在 synthesize 請求加入 `feature_evidence_keys`，由本次已驗證的證據建立 28 組可引用鍵；保留正反證據與原始 flat evidence，不改寫引用、不重新分類 topic、不刪除被拒候選。提示明確要求 supporting／contradicting 兩組都遵守同 topic 規則，章節摘要仍可跨 topic。空組必須缺漏；有證據也不能強行填中性值。

版本為 `AIAnalystPolicyV3 / PromptSetV6 / FeatureSchemaV2`。PIT、敘述安全、topic、direction、confidence 及反向證據 guard 未變。新 `scripts/run_codex_pilot_v6.py` 共用原 runner 的完整閘門；僅以明確參數改變期望的 prompt 版本與 attempt 標籤。V5 的預設 pin 仍為 V5，V6 不能改變固定來源／cutoff／package／模型等預期值。

## 測試與套用

先在本輪 review 下的隔離副本修補與測試。新增回歸修補前 **4 failed、2 passed**；修補後 **6 passed**。涵蓋輸入不變、反向證據保留、來源文字／偽造 index 不能新增可引用鍵、空 topic 不填造、未知 topic 在 provider 前拒絕，以及實際 service/provider/SQLite 紀錄路徑。

| 驗證 | 結果 |
|---|---|
| 隔離副本受影響測試 | 125 passed，exit 0 |
| 隔離副本全套 SQLite | 316 passed、2 項既有 Gemini failed、4 skipped；3 項 archive skip 因副本未複製實際 archive |
| 正式 checkout 受影響測試 | 125 passed，exit 0 |
| 正式完整 SQLite | 319 passed、2 項既有 Gemini failed、1 PostgreSQL-only skipped，exit 1 |
| Ruff、mypy、git diff --check | 通過；mypy 71 source files |

兩項既有失敗為 `test_google_probe_and_isolation`、`test_service_ineligibility_is_not_login_failure`。未修改 Gemini 程式或測試，未宣稱全套全綠。PostgreSQL 未執行。

以不可覆寫 patch 封存候選，`git apply --check` 通過後才套用，既有 M4.1 修改保留。離線核對 run 14，541 筆證據不變，新索引有 27 個非空 topic，精確指出所有 21 個被拒候選的跨 topic keys；這不是模型改善已通過的證明。

## 新 Q2 的判定與結果

新執行保留舊 run 14／snapshot 3，使用新 attempt 與新 DB ID。固定 cutoff `2022-08-25T13:30:00+00:00`、來源 ID 9／10／107／108、932 blocks、package hash `331e90ebd3ca261c06cf090a5d46ae852a4ded7eb133c434e5f7537abd3ff4c5`、requested model `gpt-6-astra`。

原生與七項合成隔離沿用前輪不可覆寫收據；transport 程式與政策沒有變更，收據 bytes 與綁定重新檢查 PASS，正式 runner 也重新比對當前 CLI／設定並通過。新 prompt 固定核准值檢查 PASS。真實啟動前已完成新的程序查核，沒有 active lock，所有相關舊 attempt 已終結。本輪沒有額外執行 synthetic probe 或隔離模型呼叫。

正式季度 gate 保持原規格。另記錄本修補的效果：topic mismatch 是否歸零、相較 run 14 的 6／28 有值特徵是否改善、其餘缺漏原因、每筆正式引用與十張保護表／歷史資料保全。不能為了達到固定涵蓋數而填造特徵。

真實 V6 Q2 於 **2026-09-26T03:18:53Z–03:54:10Z** 執行，attempt `20260926T031853Z-2c991fd948e6`。preflight PASS；20 次 extract、1 次 synthesize、1 次 challenge 全部 valid，沒有重試，所有子程序 exit 0 且 confirmed_stopped，first failure 為 null、runner 終止要求為空。外層 exit 0；正式新增 run 15／snapshot 4，季度 gate PASS、blockers 空。互斥鎖由該 attempt 正常釋放。

| 項目 | V5 基線 run 14／snapshot 3 | V6 run 15／snapshot 4 |
|---|---:|---:|
| 有值特徵 | 6／28 | 27／28 |
| 明確缺漏 | 22 | 1 |
| 跨 topic 引用拒絕 | 21 | 0 |
| 全部隔離候選 | 21 | 0 |
| 正式證據 | 541 | 540 |
| 有效 provider calls | 22／22 | 22／22 |
| 挑戰 | 8 | 8 |

V6 的 27 個候選全部通過既有 guard。所有正式特徵的引用 topic 都與 feature_name 一致；`switching_cost_strength` 沒有同主題證據，也沒有候選，維持缺漏。8 項挑戰包括 upside／downside／regime 各 1、anomaly 3、advisory adjustment 2；沒有套用調整至 Quant。

本輪重新擷取證據，因此 541 與 540 的差異屬兩次完整執行的觀察結果。這是修補後單季實測改善，並非同版本重複性測試，也不替代真人語意審查。

獨立複核於 **2026-09-26T03:54:23Z** 完成，使用唯讀 SQLite 連線重算季度判定、核准 context／package／preflight、逐次 request／response hash、kernel／isolation 路徑與 bytes、程序狀態及外部存取／升權計數；全部通過。實際 synthesize 請求中的索引與該請求的完整 evidence payload 重新推導結果一致。CLI 的模型身分仍為 `requested_only`，沒有將 requested model 當作額外取得的實際模型身分證明。

十張保護表與十二張 AI／建議表的既有 rows 數量及內容 hash 全部不變，156／156 歷史 artifacts 保全通過。舊 run 14／snapshot 3 與更早歷史完整保留。正式 DB 因新增分析資料而改變，不能宣稱整個 DB bytes hash 未變。

啟動前完整程序名稱清單 656 列、解析錯誤 0，沒有 Python runner；逐一核對五個 Codex／code-mode PID，確認三個 app-server、兩個輔助程序，沒有 exec／sandbox。早先 inline 程序查詢及 pgrep 工具沒有回傳，因此取消該兩個唯讀工具呼叫，改採完整清單與限縮 PID 身分核對；沒有把工具取消當作 OS 程序退出證據。新啟動前沒有 active lock，六個既有執行 attempts 都有 terminal 紀錄。

## 證據

[本輪 review 目錄](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/topic-alignment-20260926T030552Z-9ca5383d/) 保存起始基線、156 份歷史檔案 hash、候選 patch、修補前後與正式測試日誌、run 14 離線對齊檢查。

- [Q2 收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260926T031853Z-2c991fd948e6/pilot.json)：SHA-256 `489d57b0728f1c98b0d629de44ad6b1ba979be80c6661ef869471e749f04d3b4`。
- [獨立複核](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/topic-alignment-20260926T030552Z-9ca5383d/v6-independent-review.json)：含 27 項特徵值、引用數、缺漏原因、逐次呼叫與保全結果。
- [受影響測試](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/topic-alignment-20260926T030552Z-9ca5383d/formal-affected-tests.log)與[完整 SQLite 回歸](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/topic-alignment-20260926T030552Z-9ca5383d/formal-full-sqlite.log)。
- [最終保全](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/topic-alignment-20260926T030552Z-9ca5383d/final-preservation.json)與[交付 manifest](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/topic-alignment-20260926T030552Z-9ca5383d/delivery-manifest.json)。

`sources/` 唯讀；本輪無 commit、push 或部署。六季擴展 0／6、同版本重跑比較 0／2、真人審查 0／35；Gemini 測試及 PostgreSQL 驗收仍待補齊。下一批應使用明確固定 V6 的季度入口並逐季停止於首個 FAIL；不可直接沿用仍固定舊版本的入口。M4.1 Final Pass 尚未達成。
