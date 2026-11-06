# M4.1 真人審核結案報告 (Human Review Closure Report)

- **結案日期**：2026-10-07（Australia/Brisbane）
- **審核員（Reviewer）**：`eason`
- **審查完成時間**：`2026-10-07T11:56:06+10:00`
- **審查範圍**：前 5 個代表季度 × 7 大類別 = 35 張審查卡，以及 Q2/Q3 同條件重跑之 14 個爭議指標與 16 個歷史空支持案例。
- **資料庫寫入**：35 筆記錄已透過 `qve ai-review-import` 成功寫入 `ai_human_review` 資料表。
- **正式交付檔案**：[`data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review/submissions/submission_20261007T015923Z.json`](file:///Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-repeatability-20260927T075909Z-1d52b600/human-review/submissions/submission_20261007T015923Z.json)

---

## 1. 審查統計與門檻達成狀況

| 指標項目 | M4.1 門檻要求 | 實際達成結果 | 判定 |
|---|---|---|---|
| **真人審核卡完成數** | 35 / 35 (100%) | **35 / 35 (100%)** | **PASS** |
| **合格率 (Correct + Partially Correct)** | >= 80% | **100% (35 / 35)** | **PASS** |
| **完全正確率 (Correct Rate)** | >= 60% | **71.4% (25 / 35)** | **PASS** |
| **無支持/幻覺率 (Unsupported Rate)** | <= 10% | **0.0% (0 / 35)** | **PASS** |
| **重大事實漏失率 (Missed Rate)** | <= 10% | **0.0% (0 / 35)** | **PASS** |
| **Guard G 歷史空支持處分確認** | 100% 裁決 | **16 / 16 (100% 同意沒收)** | **PASS** |
| **重跑正負翻轉爭議解釋** | 需真人定性分析 | **已定性裁決 (跑分 vs 管道)** | **PASS** |

---

## 2. 35 張審查卡詳細結果分佈

### 前 5 季 × 7 類別裁決矩陣

| 季度 | 需求 (demand) | 供給 (supply) | 競爭 (competition) | 產品週期 (product_cycle) | 管理層 (management) | 異常 (anomalies) | 模型挑戰 (model_challenge) |
|---|---|---|---|---|---|---|---|
| **FY2023-Q2** (Run 15) | correct | correct | partially_correct | correct | partially_correct | correct | correct |
| **FY2023-Q3** (Run 17) | correct | correct | partially_correct | correct | partially_correct | correct | correct |
| **FY2024-Q1** (Run 18) | correct | correct | partially_correct | correct | partially_correct | correct | correct |
| **FY2024-Q2** (Run 20) | correct | correct | partially_correct | correct | partially_correct | correct | correct |
| **FY2025-Q4** (Run 21) | correct | correct | partially_correct | correct | partially_correct | correct | correct |

- **完全正確類別（25 卡，71.4%）**：
  - **需求（Demand）**：準確捕捉資料中心爆發性成長與遊戲顯卡庫存去化週期，引用精準。
  - **供給（Supply）**：精準追蹤長交期（12 個月以上）與網絡產品封裝限制，無虛構事實。
  - **產品週期（Product Cycle）**：Hopper 架構與 Grace CPU 之世代交替節奏分析切中官方披露。
  - **異常（Anomalies）**：地緣政治與中國許可證出口管制影響分析客觀，無過度推論。
  - **模型挑戰（Model Challenge）**：對量化預測之毛利率修復速度與庫存減損風險之質疑極具專業洞察。
- **部分正確類別（10 卡，28.6%）**：
  - **競爭（Competition）**：抓到關鍵跑分技術優勢，但因受 Intel/AMD 競品條款影響，在跑分與渠道競爭之權衡未達絕對穩定。
  - **管理層（Management）**：抓到核心指引，但定價權指標過度依賴 Item 1A「風險因素假設」，而非實際價格侵蝕數據。

---

## 3. 重大爭議點裁決紀錄

### 1. Q2 `competition_outlook` 正負翻轉事件（-0.20 → +0.10）
- **現象**：基線給 -0.20，同條件重跑給 +0.10。
- **審核裁決**：`partially_correct`。
- **理由**：重跑引用的 MLPerf 跑分領先確實為官方報導之客觀技術優勢，但基線強調的轉售競爭亦屬實。AI 在兩次推論中對「技術領先」與「市場競爭」的權衡權重存在局部擾動，方向顛倒但皆有事實依據，判定為部分正確。

### 2. 12 項被 Guard G 沒收之缺漏特徵（如 `pricing_power`、`demand_visibility`）
- **現象**：在重跑中被 Guard G 判定為 `direction_unsupported` 並隔離。
- **審核裁決**：`unsupported`（同意 Guard G 處分）。
- **理由**：經查原文，AI 所引用的售價下跌或能見度受阻，多來自 10-Q 中的「風險提示假設條款」（如若對手降價可能影響我們），而非已發生的客觀事實。Guard G 嚴格要求「假設不等於事實」並將其沒收，維護了質化分析的高純度標準。

### 3. 16 個歷史空支持案例
- **現象**：舊版 V6 中有 16 個特徵在 `supporting_evidence` 為空的情況下獲得非零評分。
- **審核裁決**：`unsupported`（同意 Guard G 處分）。
- **結論**：零支持證據絕不可給分。Guard G 的防護規則合理且必要，未發生過度誤殺。

---

## 4. 結案結論

至此，**M4.1 的真人品質審核門檻（Human Review Gate）已 100% 達成並正式通過**。
專案已具備堅實的人審基線，可以安全推進至 **FSI-S2 模型對比實驗**。
