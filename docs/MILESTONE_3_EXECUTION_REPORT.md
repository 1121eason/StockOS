# Milestone 3 Execution Report

**已收到範圍的實作與驗證完成；暫不建議無條件 Final Pass。**

V1 能辨識 FY2023 Q2/Q3 的 downturn 候選與強烈負 Cycle Score，但低信心門檻使已確認主狀態保留 Growth。此限制保留原始結果，不以調參美化歷史標籤。另：使用者附件在第 22 節 Structural Deterioration Guard 中途截斷，尚未收到後續測試／驗收條件；本報告不自行推定其內容。

## 1. Implementation Completed

沿用既有 repository、PIT 資料契約與 M2 frozen Model A。新增財務特徵、五組 signed scores、五種 regime confidence normalization、hysteresis、structural guard、Cycle Score、immutable history、append-only transitions、CLI、雙資料庫重播與敏感度分析。沒有新 repository 或後續 milestone。

## 2. Database / Migration

Core migration `0006_regimes` 擴充既有 regime_snapshots，新增 regime_transitions；labels 保持 `0003_forecast_outcomes`。新增欄位對 legacy rows 為 nullable，新引擎完整填寫必要欄位；兩表由 SQLite/PostgreSQL triggers 禁止 UPDATE/DELETE。M1/M1.1/M2 原始列皆通過保留檢查。原始備份與 preservation receipts 已保存。

正式 RegimeEngineV1.1-confidence-streak cohort 有 26 snapshots；首輪 26 個 development snapshots 保留不改寫。正式 cohort 依 assumption payload 與連續 identity chain 區分，不能把整張表的 52 列當成 52 季。Implementation V1.1 僅修正低信心季度不應累計確認期的 bug；未改已凍結的任何 threshold／weight。

## 3. Financial Feature Contract

Growth：Revenue YoY/QoQ、EPS/FCF YoY、NTM/FY1/FY2 revenue/EPS growth。Revision：同 fiscal target 的 latest、2Q、4Q revenue/EPS/FCF/GM/OM revisions 與 breadth。Profitability：GM/OM/FCF margin、YoY changes、operating leverage。Cash：AR/inventory growth、DSO、capex/revenue、SBC/revenue。Confidence：已實現 financial-error history、interval widths、sample counts。

EPS 與 shares 統一到 cutoff 的拆股基準；EPS/FCF baseline 小於可比 revenue 的 1% 或非正值時，百分比 unavailable。Operating leverage 的 revenue delta 太小亦 unavailable。FY1/FY2 與 Q4 roll 比較相同年度，沒有混用 rolling NTM。逐筆值、missing reasons、source hashes、fact IDs、forecast IDs 與 split factors 皆在 history.json。

## 4. Policy / Assumptions

[REGIME_METHOD.md](REGIME_METHOD.md) 與 regime/policy_v1.json 在歷史分類前凍結；policy-freeze.json 驗證兩份檔案 SHA-256。所有研究係數及 policy provenance 保存在正式 AssumptionSet。分數 [-1,+1]；deterioration 正值代表更差，其餘正值代表更強。Linear clipping、group averaging、prototype distances 與 weights 均可追溯。

## 5. Probability and Confidence

五種數值是 deterministic regime confidence score normalization，不是 statistically calibrated probabilities。Prototype scores 依 confidence 向 eligible regimes 均勻分布收縮，六位小數精確合計 1。Structural guard 未滿足時 structural confidence 為零，僅代表政策未允許分類。

Primary 是 persistence 確認後的狀態，Candidate 是當季最大 evidence probability。等待確認時兩者可不同，CLI 與報告明確顯示；不可把 primary 解讀為當季最大機率。

## 6. Transition Rules

一般切換需要連續兩個合格季度，兩季 confidence 均至少 40%；不合格季度歸零確認連續期。強證據可立即切換；strong negative override 仍不能越過 structural guard。Transition effective_at/detected_at 都是正式切換的 first-tradable checkpoint，不回填為候選首度出現的時間；created_at 是實際重建時間。

## 7. Structural vs Cyclical

Structural 要求連續四季、至少三個獨立面向，其中負 revenue growth 與 revenue/EPS 負 revisions 必須同時成立，再加 margin 或 FCF margin 惡化。單季 EPS miss 或 inventory spike 不足。這是持續惡化的保守量化 proxy，沒有聲稱可證明競爭地位穩定或永久損害。

## 8. Complete Historical Replay

| Quarter | Primary | Candidate | Confidence | Growth | Revision | Profitability | Cash | Deterioration | Cycle |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| FY2021-Q1 | Growth | Growth | 4.10% | 0.45 | unavailable | 0.56 | 0.12 | -0.36 | 16.69 |
| FY2021-Q2 | Growth | Hypergrowth | 11.69% | 0.65 | 0.69 | 0.16 | 0.36 | -0.38 | 34.89 |
| FY2021-Q3 | Growth | Growth | 15.23% | 0.52 | 0.33 | -0.01 | -0.27 | -0.03 | -12.85 |
| FY2021-Q4 | Growth | Hypergrowth | 16.61% | 0.76 | 0.67 | 0.28 | 0.16 | -0.31 | 13.98 |
| FY2022-Q1 | Growth | Hypergrowth | 24.06% | 0.81 | 0.83 | 0.51 | 0.31 | -0.57 | 52.84 |
| FY2022-Q2 | Growth | Hypergrowth | 27.15% | 0.67 | 0.29 | 0.85 | 0.30 | -0.54 | 26.49 |
| FY2022-Q3 | Growth | Growth | 29.41% | 0.70 | 0.22 | 0.59 | 0.02 | -0.38 | 11.76 |
| FY2022-Q4 | Growth | Growth | 33.06% | 0.52 | -0.02 | 0.67 | 0.12 | -0.28 | 5.95 |
| FY2023-Q1 | Growth | Mature Growth | 47.47% | 0.33 | -0.25 | -0.09 | -0.31 | 0.20 | -40.96 |
| FY2023-Q2 | Growth | Cyclical Downturn | 48.24% | -0.36 | -1.00 | -0.53 | -0.52 | 0.72 | -92.78 |
| FY2023-Q3 | Growth | Cyclical Downturn | 39.46% | -0.23 | -0.84 | -0.56 | -0.80 | 0.72 | -82.01 |
| FY2023-Q4 | Growth | Mature Growth | 63.33% | 0.29 | -0.03 | -0.14 | -0.17 | 0.18 | -29.36 |
| FY2024-Q1 | Growth | Hypergrowth | 63.79% | 0.74 | 0.59 | 0.66 | 0.29 | -0.56 | 43.30 |
| FY2024-Q2 | Hypergrowth | Hypergrowth | 63.43% | 0.96 | 1.00 | 0.97 | 0.72 | -0.92 | 100.00 |
| FY2024-Q3 | Hypergrowth | Hypergrowth | 62.03% | 0.95 | 0.96 | 0.99 | 0.65 | -0.89 | 98.71 |
| FY2024-Q4 | Hypergrowth | Hypergrowth | 63.93% | 0.78 | 1.00 | 1.00 | 0.76 | -0.89 | 100.00 |
| FY2025-Q1 | Hypergrowth | Hypergrowth | 65.37% | 0.85 | 0.89 | 1.00 | 0.78 | -0.88 | 75.58 |
| FY2025-Q2 | Hypergrowth | Hypergrowth | 66.88% | 0.94 | 0.58 | 0.84 | 0.50 | -0.67 | 24.16 |
| FY2025-Q3 | Hypergrowth | Hypergrowth | 68.03% | 1.00 | 0.38 | 0.85 | 0.44 | -0.63 | 23.20 |
| FY2025-Q4 | Hypergrowth | Growth | 68.98% | 0.80 | 0.01 | 0.21 | 0.01 | -0.07 | -33.73 |
| FY2026-Q1 | Growth | Growth | 68.38% | 0.76 | -0.52 | 0.15 | 0.16 | 0.03 | -37.51 |
| FY2026-Q2 | Growth | Growth | 68.62% | 0.78 | -0.22 | 0.15 | -0.16 | 0.05 | -47.28 |
| FY2026-Q3 | Growth | Growth | 69.77% | 0.85 | -0.24 | 0.31 | -0.01 | -0.06 | -30.25 |
| FY2026-Q4 | Growth | Hypergrowth | 70.61% | 0.96 | 0.60 | 0.86 | 0.35 | -0.66 | 38.71 |
| FY2027-Q1 | Hypergrowth | Hypergrowth | 70.59% | 0.91 | 0.63 | 0.84 | 0.20 | -0.60 | 30.14 |
| FY2027-Q2 | Hypergrowth | Hypergrowth | 71.42% | 0.91 | 0.25 | 0.50 | -0.03 | -0.32 | 5.65 |

26 季 primary counts：{'Cyclical Downturn': 0, 'Growth': 17, 'Hypergrowth': 9, 'Mature Growth': 0, 'Structural Deterioration': 0}。沒有出現某類不代表其不可能；synthetic tests 覆蓋 structural guard 與 shock 行為。

## 9. Transition Stability

正式轉換 3 次／25 個相鄰期間，frequency 12.00%；one-quarter flip 0 次。Observed average duration 6.50 季，首尾段受樣本邊界截斷。平均相鄰 probability absolute change 2.79%；Cycle Score 一階差分標準差 37.07。

| Effective timestamp | From | To | Reasons |
|---|---|---|---|
| 2023-08-24T13:30:00+00:00 | Growth | Hypergrowth | PERSISTENCE_CONFIRMED, GROWTH_ACCELERATION, REVISION_ACCELERATION, STRUCTURAL_EVIDENCE_INSUFFICIENT |
| 2025-05-29T13:30:00+00:00 | Hypergrowth | Growth | PERSISTENCE_CONFIRMED, GROWTH_DECELERATION, MARGIN_COMPRESSION, CYCLICAL_PRESSURE, STRUCTURAL_EVIDENCE_INSUFFICIENT |
| 2026-05-21T13:30:00+00:00 | Growth | Hypergrowth | PERSISTENCE_CONFIRMED, GROWTH_ACCELERATION, REVISION_ACCELERATION, CYCLICAL_PRESSURE, STRUCTURAL_EVIDENCE_INSUFFICIENT |

## 10. Sensitivity Analysis

按預先規劃 ±10% 改變 score centers/scales、各 layer weight 及強轉換 lead threshold，共 14 組。每組重新走完整 persistence path；不變更 PIT、denominator safeguards、minimum structural history，也不挑最好看的版本。

| Variant | Changed primary labels | Mean probability difference | Mean cycle difference | Transitions | Within 25% limit |
|---|---:|---:|---:|---:|---|
| score_scales_centers_-1 | 0.00% | 0.24% | 1.25 | 3 | True |
| growth_weight_-1 | 0.00% | 0.13% | 0.00 | 3 | True |
| revision_weight_-1 | 0.00% | 0.08% | 0.00 | 3 | True |
| profitability_weight_-1 | 0.00% | 0.05% | 0.00 | 3 | True |
| cash_quality_weight_-1 | 0.00% | 0.03% | 0.00 | 3 | True |
| deterioration_weight_-1 | 0.00% | 0.02% | 0.00 | 3 | True |
| transition_gap_-1 | 0.00% | 0.00% | 0.00 | 3 | True |
| score_scales_centers_+1 | 11.54% | 0.25% | 1.09 | 4 | True |
| growth_weight_+1 | 0.00% | 0.12% | 0.00 | 3 | True |
| revision_weight_+1 | 0.00% | 0.08% | 0.00 | 3 | True |
| profitability_weight_+1 | 0.00% | 0.05% | 0.00 | 3 | True |
| cash_quality_weight_+1 | 0.00% | 0.03% | 0.00 | 3 | True |
| deterioration_weight_+1 | 0.00% | 0.02% | 0.00 | 3 | True |
| transition_gap_+1 | 0.00% | 0.00% | 0.00 | 3 | True |

## 11. Historical Sanity Review

**Downturn：** FY2023 Q2/Q3 的 candidate 為 Cyclical Downturn，Cycle −92.78／−82.01，revision scores −1.00／−0.84，獲利與現金分數同步惡化。模型確實看見壓力，但 Q3 confidence 39.456% 未達 40%，因此 confirmation 中斷，primary 保留 Growth。Q4 candidate 回到 Mature Growth，又需重新確認。該季 confidence = 0.65 quality × 0.891667 history factor × mean(0.724725 error factor, 0.636811 interval factor)。35% quality penalty 包括當季負 FCF margin（15%）與歷史 FY2020 Q4 EPS share-basis warning（20%）；V1 傳遞完整歷史 context 的 warning，較當季實際 feature 視窗更保守。這是「保守降信心」和「state responsiveness」的實際衝突，不能只看 0 flips 就宣稱設計完美。

**AI acceleration：** FY2024 Q1 candidate 為 Hypergrowth，Q2 確認切換，反映 revenue/EPS/revision/margin 的同向改善。FY2025 Q4 candidate 轉 Growth、FY2026 Q1 確認；FY2026 Q4 candidate 再轉 Hypergrowth、FY2027 Q1 確認。未硬寫任何年度或預期 label。

**Structural：** 26 季沒有滿足四季聯合證據，不產生 structural primary；單一 inventory／EPS anomaly 不作永久惡化結論。

## 12. Data Quality and Limitations

缺 FCF／share basis、margin anomaly、forecast error history不足都降低信心；不填假值。早期歷史信心很低，primary 僅為暫時初始化／保留的狀態，不應忽略 candidate。DSO 使用期末 AR 而非平均 AR；FCF 延續 M2 的近似；固定 prototype 非業界通用分類標準。Cycle 的大幅波動可能反映真实衝擊，不以平滑到好看為目標。

## 13. Verification

- SQLite：130 passed, 1 skipped in 13.51s
- Actual PostgreSQL：131 passed in 35.80s；PostgreSQL 17.10 on aarch64-unknown-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit。
- 雙次重播 identities/states/counts 完全一致；SQLite/PostgreSQL 26 組 states 與所有 feature cells 完全一致。
- Future forecast/financial injection、SQL/import isolation、probability sum、hysteresis、four-quarter guard、small denominators、4x/10x split invariance、低信心確認中斷及 immutable triggers 通過。
- 120 份原始 source SHA-256 全通過；兩種資料庫的 M1/M1.1/M2 原始列皆保持不變。

## 14. Regime + Valuation Read-only View

下表在分類完成後才讀取既有 M2 valuation；沒有把 P/E、DCF 或價格傳入 classifier。沿用 M2 代表性切面供檢查，並非推定未收到的 M3 PM gate 規格。

| Quarter | Primary / Candidate | EPS revision | NTM P/E | Forward FCF Yield | DCF base | Reverse CAGR |
|---|---|---:|---:|---:|---:|---:|
| FY2022-Q1 | Growth / Hypergrowth | 15.82% | 39.07 | 2.50% | 262.56 | unavailable |
| FY2023-Q3 | Growth / Cyclical Downturn | -2.73% | 52.16 | 1.34% | 102.32 | unavailable |
| FY2024-Q1 | Growth / Hypergrowth | 86.20% | 44.76 | 1.78% | 270.02 | unavailable |
| FY2025-Q2 | Hypergrowth / Hypergrowth | 5.12% | 32.46 | 2.73% | 70.72 | 44.42% |
| FY2027-Q2 | Hypergrowth / Hypergrowth | 2.46% | 15.49 | 4.81% | 246.23 | 38.52% |

## 15. CLI / Reproduction

```sh
uv sync --locked
uv run qve init-db
uv run python scripts/run_m3.py
uv run qve regime --ticker NVDA --as-of 2026-08-27T09:30:00-04:00
uv run qve regime-history --ticker NVDA
uv run qve regime-transitions --ticker NVDA
uv run qve cycle-score --ticker NVDA --as-of 2023-05-25T09:30:00-04:00
```

CLI --as-of 是知識 cutoff，返回不晚於該時刻的最新 first-tradable snapshot，並先按序重建必要歷史；不把任意輸入時刻偽裝成當季可交易日。--json-output 提供完整 state；history.json 含完整 provenance。PostgreSQL 重現用 scripts/validate_m3_postgres.py；設定沿用 M2 本機測試庫。交付包未含 pre-M3 backups，請用 `scripts/run_m3.py --skip-preservation-audit` 重播；僅略過已提供 receipt 的舊列備份比對，不略過 source hash、classification 或 idempotency。

## 16. Received Requirements Coverage

| Received sections | Status | Evidence / limit |
|---|---|---|
| 1–7: definitions, financial inputs, assumptions, scores, probabilities | PASS | Versioned policy, full features, exact normalized probabilities |
| 8–10: persistence, transitions, snapshots | PASS with disclosed tradeoff | Immutable records and passing boundary tests; low confidence can retain stale primary |
| 11–14: history, sanity, structural guard, cycle | PASS / sanity limitation | 26 quarters; downturn candidate/cycle visible while primary is held |
| 15–16: valuation isolation / combined view | PASS | SQL/import guards; combined view after classification |
| 17–21: stability, sensitivity, data quality, CLI, reasons | PASS | Replayed metrics, 14 variants, deterministic reason codes |
| 22: received tests | PASS | Leakage, outcomes isolation, determinism, probability, transition and shock guard |
| 22 remainder / any later acceptance requirements | NOT RECEIVED | Source attachment ends mid-sentence; no invented requirements |

## 17. Recommendation / PM Review

不建議目前直接給予無條件 M3 Final Pass。需要 PM 評估：低信心時保留上一個 primary 是否符合產品用途；若 primary 必須及時代表已出現的 downturn，應另行設計並版本化 state/uncertainty policy，而不是把這次 40% 門檻降到剛好讓某歷史季通過。完整附件後段仍待確認。

最新 FY2027 Q2：primary Hypergrowth，confidence 71.42%，cycle 5.65。此結果為可重現的基本面研究分類，不是交易建議。M3 到此停止；沒有開始下一 milestone。
