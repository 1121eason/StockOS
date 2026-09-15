# Milestone 3.1 Execution Report

**建議 Milestone 3 Final Pass。**

## 1. Confidence Model Changes

RegimePolicyV1.1 / RegimeEngineV1.2-active-lineage。Evidence 為 prototype 機率、分離度、四個獨立面向支持度、分數一致性及證據強度的等權組合；Data Quality 只計有效觀測完整度與相關品質問題；History 為 error samples、revision windows、rolling history 的最小充足度。Composite = Evidence × DQ × (0.35 + 0.65 × History)。

五組新 evidence 權重是方法定義，已於 corrected replay 前凍結；不是估計準確率。原 M3 所有 score weights、prototypes、scales、40%/65% confidence gates、兩季 persistence、25-point gap 和四季 structural guard 逐項相等。負 FCF margin 留在經濟訊號；historical error magnitude/interval width 留作診斷，不再混入資料可靠度。方法及契約見 REGIME_METHOD.md、REGIME_OUTPUT_CONTRACT.md。

## 2. Active Data Quality Lineage

每一 snapshot 保存 Feature → Input Observation → Warning / Quality Issue 完整圖。警告須匹配 fact IDs 或精確 period/metric；source 級問題則按來源與可用 metric/period 限定。Registry issue 只讀 cutoff 前已知問題，原 ledger 不刪除。FY2020-Q4 Revenue 可用於季節性，但該季 reported EPS 並不參與 FY2023-Q3 的 EPS 特徵或 M2 aggregate EPS。

詳細機器可讀圖與逐筆排除理由：data/m31/report/history.json、fy2023-diagnostic.json。缺歷史季度屬 History；存在季度中缺必要欄位屬 DQ。資料品質不是企業營運好壞。

## 3. FY2023 Q1–Q4 Diagnostic

| Quarter | Confirmed | Candidate | Status | Candidate p / gap | Evidence | DQ | History | Composite | Cycle | Counter |
|---|---|---|---|---|---|---|---|---|---|---|
| FY2023-Q1 | Growth | Mature Growth | PENDING_CONFIRMATION | 32.41% / 4.76% | 58.78% | 100.00% | 66.67% | 46.04% | -40.96 | 1 |
| FY2023-Q2 | Cyclical Downturn | Cyclical Downturn | STABLE | 66.11% / 46.54% | 80.73% | 100.00% | 75.00% | 67.61% | -92.78 | 1 |
| FY2023-Q3 | Cyclical Downturn | Cyclical Downturn | STABLE | 65.31% / 44.40% | 79.66% | 100.00% | 83.33% | 71.03% | -82.01 | 2 |
| FY2023-Q4 | Cyclical Downturn | Mature Growth | PENDING_CONFIRMATION | 34.21% / 5.06% | 59.36% | 100.00% | 91.67% | 56.14% | -29.36 | 1 |

### FY2023-Q1

Scores: {"cash_quality": "-0.30932292", "deterioration": "0.20091763", "growth": "0.32624037", "profitability": "-0.08643250", "revision": "-0.24880082"}.

Old confidence 0.47465581 / counter 1 / decision PERSISTENCE_PENDING; corrected Evidence 0.58776300 × DQ 1.00000000 × history multiplier 0.78333333 = Composite 0.46041435 / counter 1 / decision PERSISTENCE_PENDING. Prior confirmed Growth → Growth; candidate Mature Growth → Mature Growth. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.

Active penalties: [].

Excluded warnings:
- {"parameter": "FY2020-Q4:eps_diluted", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped
- {"parameter": "FY2020-Q3:diluted_shares", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped
- {"parameter": "FY2020-Q3:eps_diluted", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped
- {"parameter": "FY2020-Q2:diluted_shares", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped
- {"parameter": "FY2020-Q2:eps_diluted", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped

### FY2023-Q2

Scores: {"cash_quality": "-0.51563122", "deterioration": "0.71970666", "growth": "-0.36319544", "profitability": "-0.53385043", "revision": "-1.00000000"}.

Old confidence 0.48235930 / counter 1 / decision PERSISTENCE_PENDING; corrected Evidence 0.80733313 × DQ 1.00000000 × history multiplier 0.83750000 = Composite 0.67614150 / counter 1 / decision STRONG_EVIDENCE_TRANSITION. Prior confirmed Growth → Growth; candidate Cyclical Downturn → Cyclical Downturn. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.

Active penalties: [].

Excluded warnings:
- {"parameter": "FY2020-Q4:eps_diluted", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped
- {"parameter": "FY2020-Q3:diluted_shares", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped
- {"parameter": "FY2020-Q3:eps_diluted", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped

### FY2023-Q3

Scores: {"cash_quality": "-0.79762476", "deterioration": "0.71616062", "growth": "-0.23093559", "profitability": "-0.56162724", "revision": "-0.83608211"}.

Old confidence 0.39456175 / counter 0 / decision PERSISTENCE_PENDING; corrected Evidence 0.79656483 × DQ 1.00000000 × history multiplier 0.89166667 = Composite 0.71027031 / counter 2 / decision STATE_RETAINED. Prior confirmed Growth → Cyclical Downturn; candidate Cyclical Downturn → Cyclical Downturn. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.

Active penalties: [].

Excluded warnings:
- {"feature": "fcf_margin", "reason": "margin_anomaly"} → economic_signal_not_measurement_reliability
- {"parameter": "FY2020-Q4:eps_diluted", "reason": "unverified_share_basis"} → outside_active_feature_lineage_or_unscoped

### FY2023-Q4

Scores: {"cash_quality": "-0.17071414", "deterioration": "0.17933472", "growth": "0.28553099", "profitability": "-0.14301717", "revision": "-0.02806557"}.

Old confidence 0.63333397 / counter 1 / decision PERSISTENCE_PENDING; corrected Evidence 0.59360180 × DQ 1.00000000 × history multiplier 0.94583333 = Composite 0.56144837 / counter 1 / decision PERSISTENCE_PENDING. Prior confirmed Growth → Cyclical Downturn; candidate Mature Growth → Mature Growth. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.

Active penalties: [].

Excluded warnings:
- None.

## 4. Historical Regime Path Before vs After

| Quarter | M3 confirmed | M3.1 confirmed | Candidate | Status |
|---|---|---|---|---|
| FY2021-Q1 | Growth | Growth | Growth | LOW_CONFIDENCE |
| FY2021-Q2 | Growth | Growth | Hypergrowth | LOW_CONFIDENCE |
| FY2021-Q3 | Growth | Growth | Growth | LOW_CONFIDENCE |
| FY2021-Q4 | Growth | Growth | Hypergrowth | LOW_CONFIDENCE |
| FY2022-Q1 | Growth | Growth | Hypergrowth | LOW_CONFIDENCE |
| FY2022-Q2 | Growth | Growth | Hypergrowth | LOW_CONFIDENCE |
| FY2022-Q3 | Growth | Growth | Growth | LOW_CONFIDENCE |
| FY2022-Q4 | Growth | Growth | Growth | STABLE |
| FY2023-Q1 | Growth | Growth | Mature Growth | PENDING_CONFIRMATION |
| FY2023-Q2 | Growth | Cyclical Downturn | Cyclical Downturn | STABLE |
| FY2023-Q3 | Growth | Cyclical Downturn | Cyclical Downturn | STABLE |
| FY2023-Q4 | Growth | Cyclical Downturn | Mature Growth | PENDING_CONFIRMATION |
| FY2024-Q1 | Growth | Hypergrowth | Hypergrowth | STABLE |
| FY2024-Q2 | Hypergrowth | Hypergrowth | Hypergrowth | STABLE |
| FY2024-Q3 | Hypergrowth | Hypergrowth | Hypergrowth | STABLE |
| FY2024-Q4 | Hypergrowth | Hypergrowth | Hypergrowth | STABLE |
| FY2025-Q1 | Hypergrowth | Hypergrowth | Hypergrowth | STABLE |
| FY2025-Q2 | Hypergrowth | Hypergrowth | Hypergrowth | STABLE |
| FY2025-Q3 | Hypergrowth | Hypergrowth | Hypergrowth | STABLE |
| FY2025-Q4 | Hypergrowth | Hypergrowth | Growth | PENDING_CONFIRMATION |
| FY2026-Q1 | Growth | Growth | Growth | STABLE |
| FY2026-Q2 | Growth | Growth | Growth | STABLE |
| FY2026-Q3 | Growth | Growth | Growth | STABLE |
| FY2026-Q4 | Growth | Growth | Hypergrowth | PENDING_CONFIRMATION |
| FY2027-Q1 | Hypergrowth | Hypergrowth | Hypergrowth | STABLE |
| FY2027-Q2 | Hypergrowth | Hypergrowth | Hypergrowth | STABLE |

每個 label、transition 或決策變更的精確歸因如下（完整當季與前季 state 在 path-changes.json）：

- FY2023-Q2: Old confidence 0.48235930 / counter 1 / decision PERSISTENCE_PENDING; corrected Evidence 0.80733313 × DQ 1.00000000 × history multiplier 0.83750000 = Composite 0.67614150 / counter 1 / decision STRONG_EVIDENCE_TRANSITION. Prior confirmed Growth → Growth; candidate Cyclical Downturn → Cyclical Downturn. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.
- FY2023-Q3: Old confidence 0.39456175 / counter 0 / decision PERSISTENCE_PENDING; corrected Evidence 0.79656483 × DQ 1.00000000 × history multiplier 0.89166667 = Composite 0.71027031 / counter 2 / decision STATE_RETAINED. Prior confirmed Growth → Cyclical Downturn; candidate Cyclical Downturn → Cyclical Downturn. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.
- FY2023-Q4: Old confidence 0.63333397 / counter 1 / decision PERSISTENCE_PENDING; corrected Evidence 0.59360180 × DQ 1.00000000 × history multiplier 0.94583333 = Composite 0.56144837 / counter 1 / decision PERSISTENCE_PENDING. Prior confirmed Growth → Cyclical Downturn; candidate Mature Growth → Mature Growth. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.
- FY2024-Q1: Old confidence 0.63791848 / counter 1 / decision PERSISTENCE_PENDING; corrected Evidence 0.65964375 × DQ 1.00000000 × history multiplier 1.00000000 = Composite 0.65964375 / counter 1 / decision STRONG_EVIDENCE_TRANSITION. Prior confirmed Growth → Cyclical Downturn; candidate Hypergrowth → Hypergrowth. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.
- FY2024-Q2: Old confidence 0.63430579 / counter 2 / decision PERSISTENCE_CONFIRMED; corrected Evidence 0.75656667 × DQ 1.00000000 × history multiplier 1.00000000 = Composite 0.75656667 / counter 2 / decision STATE_RETAINED. Prior confirmed Growth → Hypergrowth; candidate Hypergrowth → Hypergrowth. Core thresholds and features unchanged. Later held states inherit their own chronological confirmation chain, not a new manual override.

## 5. Transition Timeline

| Version | Effective/detected checkpoint | From | To | Decision |
|---|---|---|---|---|
| M3 | 2023-08-24T13:30:00+00:00 | Growth | Hypergrowth | PERSISTENCE_CONFIRMED |
| M3 | 2025-05-29T13:30:00+00:00 | Hypergrowth | Growth | PERSISTENCE_CONFIRMED |
| M3 | 2026-05-21T13:30:00+00:00 | Growth | Hypergrowth | PERSISTENCE_CONFIRMED |
| M3.1 | 2022-08-25T13:30:00+00:00 | Growth | Cyclical Downturn | STRONG_EVIDENCE_TRANSITION |
| M3.1 | 2023-05-25T13:30:00+00:00 | Cyclical Downturn | Hypergrowth | STRONG_EVIDENCE_TRANSITION |
| M3.1 | 2025-05-29T13:30:00+00:00 | Hypergrowth | Growth | PERSISTENCE_CONFIRMED |
| M3.1 | 2026-05-21T13:30:00+00:00 | Growth | Hypergrowth | PERSISTENCE_CONFIRMED |

Transition 時間仍是 first-tradable checkpoint，不回填到最早候選季；原 M3 rows 留存。LOW_CONFIDENCE 會把 qualifying counter 歸零；STABLE 表示當前 candidate 已獲確認，包含當季剛確認的切換。

## 6. Stability Comparison

| Metric | M3 | M3.1 |
|---|---|---|
| regime_changes | 3.00 | 4.00 |
| change_frequency | 0.12 | 0.16 |
| one_quarter_flips | 0.00 | 0.00 |
| one_quarter_flip_frequency | 0.00 | 0.00 |
| average_observed_regime_duration | 6.50 | 5.20 |
| mean_absolute_probability_change | 0.03 | 0.04 |
| cycle_change_dispersion | 37.07 | 37.07 |

首尾 duration 有截斷，只有 26 季，不是長期估計。Probability 每季每類平均絕對變動由 2.79 個百分點升至 4.44 個百分點，符合減少信心收縮後的較明顯反應；Cycle 完全相同。觀測持續期為 9、3、8、4、2 季，末段截斷；新增一段連續三季 downturn，並未形成單季抖動，因此穩定性審查接受這項方法變更。不能單憑 FY2023 標籤變動宣稱更準。

## 7. Sensitivity Comparison

同一組 14 個 ±10% cases；凍結容忍值 25.00%。最大 label change：M3 11.54%；M3.1 0.00%。

| Case | M3 changed labels | M3.1 changed labels | M3.1 transitions / 1Q flips |
|---|---|---|---|
| score_scales_centers_-1 | 0.00% | 0.00% | 4 / 0 |
| growth_weight_-1 | 0.00% | 0.00% | 4 / 0 |
| revision_weight_-1 | 0.00% | 0.00% | 4 / 0 |
| profitability_weight_-1 | 0.00% | 0.00% | 4 / 0 |
| cash_quality_weight_-1 | 0.00% | 0.00% | 4 / 0 |
| deterioration_weight_-1 | 0.00% | 0.00% | 4 / 0 |
| transition_gap_-1 | 0.00% | 0.00% | 4 / 0 |
| score_scales_centers_+1 | 11.54% | 0.00% | 4 / 0 |
| growth_weight_+1 | 0.00% | 0.00% | 4 / 0 |
| revision_weight_+1 | 0.00% | 0.00% | 4 / 0 |
| profitability_weight_+1 | 0.00% | 0.00% | 4 / 0 |
| cash_quality_weight_+1 | 0.00% | 0.00% | 4 / 0 |
| deterioration_weight_+1 | 0.00% | 0.00% | 4 / 0 |
| transition_gap_+1 | 0.00% | 0.00% | 4 / 0 |

## 8. Regression Results

全部 26 季 financial feature vectors、五組 scores、Cycle Score 與原 M3 精確一致。FY2024 AI acceleration 仍顯示 Hypergrowth candidate；FY2025/26、FY2027 全狀態列於上表與 regressions.json。

合成測試覆蓋四季 structural guard、4:1/10:1 split 全分類不變、相關與無關警告、低品質中斷確認、候選/確認分離、價格 shock、未來 filing/quality issue 隔離、禁止讀取 price/return/outcome tables、不可變與 deterministic replay。

## 9. Test Results

- SQLite: 140 passed, 1 skipped in 14.59s
- Actual PostgreSQL: 141 passed in 45.94s
- Server: PostgreSQL 17.10 on aarch64-unknown-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit
- Core migration: 0007_regime_confidence; labels unchanged.
- SQLite/PostgreSQL 26 states + feature vectors exact parity.
- Double replay: all state/identity/counts unchanged; both backends original-row preservation passed.
- All 120 source content hashes verified. M3 policy/method freeze preserved in V1 archive.

## 10. M3.1 AC1–AC15 PASS / PARTIAL / FAIL

| AC | Status | Evidence |
|---|---|---|
| AC1 | PASS | history.json: feature_lineage → input_observations → quality_lineage.active_penalties; relevant issue tests |
| AC2 | PASS | FY2023 diagnostics excluded FY2020-Q4 EPS; exact metric/period tests |
| AC3 | PASS | 0007_regime_confidence persisted fields and immutable contract tests |
| AC4 | PASS | confirmed_regime/candidate_regime scalar columns, snapshot contracts |
| AC5 | PASS | transition_status scalar column, idempotency and pending/reset tests |
| AC6 | PASS | 26 full normalized vectors; strict contract validation |
| AC7 | PASS | REGIME_OUTPUT_CONTRACT.md; confirmed-only and mixed-vector rejection tests |
| AC8 | PASS | fy2023-diagnostic.json + report four complete diagnostics |
| AC9 | PASS | path-changes.json including old/new/prior states; frozen policy receipt |
| AC10 | PASS | regressions.json FY2024 raw fundamental scores unchanged |
| AC11 | PASS | four-quarter synthetic guard and historical guard checks |
| AC12 | PASS | stability-comparison.json and sensitivity-comparison.json |
| AC13 | PASS | SQLite test-results.txt; PostgreSQL actual validation.json; parity receipt |
| AC14 | PASS | SQL forbidden-table guard, price shock/future filing tests, import boundary |
| AC15 | PASS | scope limited to confidence, provenance, transition metadata and contract |

## 11. Remaining Limitations

- Evidence/probability scores 未作統計機率校準；沒有實證預測準確率承諾。
- 只有 NVIDIA 26 季；穩定性結果不代表其他公司或未見時期。
- 警告無法定位來源/欄位時保留為 unscoped，不猜測影響；未建檔的來源錯誤仍可能存在。
- Forecast lookback 使用明確保守依賴窗；完整度按有效 observation 計數，非另行調整 feature 權重。
- Historical snapshots 是已封存來源的 PIT 重建；不是當年真正運行的 live model。

## 12. Recommendation

建議 Milestone 3 可獲 Final Pass；由 PM 作最終接受決定。

M3.1 到此停止。未開始 AI Analyst、Opportunity Score、Buy/Hold/Sell、returns optimization 或 valuation multiple calibration。
