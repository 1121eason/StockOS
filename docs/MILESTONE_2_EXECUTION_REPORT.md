# Milestone 2 Execution Report

**Final Pass recommended for PM review**

M1／M1.1 已由 PM 通過，原有 PIT/source/split/shares 規則維持。M2 使用固定的 deterministic GAAP 模型；所有歷史預測都是 `research_reconstructed_internal`，不是當時觀察到的華爾街共識。

## 1. Implementation Completed

完成雙 checkpoint、八季完整財務預測、NTM／FY1／FY2、guidance bias、empirical intervals、同標的期間修訂、財務誤差評估、historical forward valuation、DCF、Reverse DCF、sensitivity、歷史分位數、CLI、測試及方法文件。A／B／C 均保留。

## 2. Database / Migration Changes

Core：`0005_research`；labels：`0003_forecast_outcomes`。新增六個 core tables 與獨立的 forecast_outcomes label table。[欄位與資料契約](M2_DATA_MODEL.md)。原本 23 個 core／label tables 的原始列全部保留不變；基準檢查見 preservation.json。

正式 benchmark 為 156 runs（26 季 × 2 checkpoints × 3 models）。資料庫保留開發期不可改寫紀錄；accuracy 與正式 history 依 typed frozen assumption hash 選取，並未因表現好壞刪除模型。

## 3. Forecast Method

A：GAAP guidance anchor + 僅已實現歷史 guidance bias。B：mechanical historical trend。C：固定 50/50 ensemble，再重算完整損益。Revenue 結合 YoY／sequential／seasonality／acceleration／mean reversion；OpEx 可獨立稽核。EPS 分母為 forecast diluted weighted-average shares，市值／DCF 使用 PIT shares outstanding。詳見 [FORECAST_METHOD.md](FORECAST_METHOD.md)。

所有數值係數在完整 accuracy 評估前固定；policy-freeze.json 記錄方法與參數雜湊。沒有用後來股價或報酬調整參數。

## 4. Forecast Coverage

以下為 Model A 的 first-tradable snapshots；EPS 使用各估值日的共同股數基準。金額表格只做顯示四捨五入；JSON／資料庫保留 Decimal 精度。

| Quarter | Q+1 Revenue ($bn) | Q+1 EPS | NTM EPS | FY1 EPS | FY2 EPS | NTM P/E | Forward FCF Yield | DCF base | Reverse 5Y growth |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FY2021-Q1 | 3.650 | 0.914 | 5.205 | 5.299 | 7.885 | 67.822 | 2.361% | — | —% |
| FY2021-Q2 | 4.400 | 1.748 | 7.512 | 5.963 | 9.902 | 63.765 | 2.370% | — | —% |
| FY2021-Q3 | 4.800 | 1.921 | 9.481 | 6.516 | 10.624 | 55.744 | 1.806% | 198.902 | —% |
| FY2021-Q4 | 5.300 | 2.358 | 13.183 | 13.183 | 17.096 | 42.617 | 2.335% | 249.308 | —% |
| FY2022-Q1 | 6.701 | 3.559 | 16.074 | 15.268 | 18.622 | 39.069 | 2.502% | 262.560 | —% |
| FY2022-Q2 | 7.202 | 0.943 | 3.793 | 3.584 | 4.340 | 51.396 | 1.857% | 63.566 | 47.878% |
| FY2022-Q3 | 7.784 | 1.057 | 4.742 | 3.723 | 5.127 | 68.250 | 1.376% | 83.395 | 62.210% |
| FY2022-Q4 | 8.461 | 0.666 | 4.009 | 4.009 | 5.893 | 63.933 | 1.714% | 95.348 | —% |
| FY2023-Q1 | 8.452 | 1.027 | 5.048 | 4.266 | 7.207 | 31.764 | 2.815% | 120.428 | —% |
| FY2023-Q2 | 6.122 | 0.429 | 1.839 | 1.704 | 2.667 | 91.597 | 1.005% | 55.054 | —% |
| FY2023-Q3 | 6.197 | 0.484 | 3.013 | 1.657 | 3.727 | 52.160 | 1.342% | 102.323 | —% |
| FY2023-Q4 | 6.682 | 0.619 | 3.634 | 3.634 | 7.945 | 64.505 | 1.120% | 122.335 | —% |
| FY2024-Q1 | 11.308 | 1.774 | 8.607 | 6.766 | 14.051 | 44.759 | 1.779% | 270.017 | —% |
| FY2024-Q2 | 16.448 | 3.071 | 13.575 | 9.525 | 15.446 | 36.992 | 2.360% | 227.593 | —% |
| FY2024-Q3 | 20.560 | 4.208 | 18.013 | 11.215 | 18.068 | 27.675 | 3.356% | 195.637 | —% |
| FY2024-Q4 | 25.540 | 5.460 | 24.341 | 24.341 | 26.101 | 30.823 | 2.814% | 306.090 | 47.112% |
| FY2025-Q1 | 30.664 | 6.568 | 30.044 | 27.367 | 36.389 | 33.959 | 2.698% | 494.762 | 44.931% |
| FY2025-Q2 | 35.593 | 0.774 | 3.738 | 2.877 | 4.511 | 32.462 | 2.733% | 70.719 | 44.421% |
| FY2025-Q3 | 41.068 | 0.887 | 4.867 | 2.931 | 5.626 | 30.684 | 2.929% | 127.653 | 44.929% |
| FY2025-Q4 | 47.092 | 0.987 | 4.992 | 4.992 | 7.827 | 27.044 | 3.192% | 114.876 | 39.807% |
| FY2026-Q1 | 48.704 | 1.039 | 5.152 | 4.343 | 7.463 | 27.609 | 3.117% | 123.784 | 36.109% |
| FY2026-Q2 | 58.112 | 1.307 | 6.519 | 4.644 | 8.331 | 27.737 | 2.823% | 139.075 | 43.978% |
| FY2026-Q3 | 69.177 | 1.616 | 8.324 | 4.755 | 9.548 | 23.539 | 2.948% | 168.846 | 44.663% |
| FY2026-Q4 | 82.075 | 2.017 | 10.149 | 10.149 | 16.355 | 19.142 | 3.913% | 207.214 | 38.662% |
| FY2027-Q1 | 95.411 | 2.397 | 12.071 | 10.870 | 16.446 | 18.415 | 4.067% | 198.767 | 39.618% |
| FY2027-Q2 | 113.234 | 2.892 | 14.386 | 11.137 | 18.315 | 15.491 | 4.811% | 246.232 | 38.517% |

## 5. Guidance Accuracy

Surprise 採 Actual / Midpoint − 1；GM 為百分點差。未實現的下一季 guide 保留在 run metadata，actual／surprise 不補值。

| Metric | 已實現樣本 | Mean surprise | Median surprise | Dispersion |
|---|---:|---:|---:|---:|
| gross_margin | 25 | -1.171 | 0.176 | 5.014 |
| operating_expenses | 25 | -0.279 | -0.086 | 2.066 |
| revenue | 25 | 5.391 | 4.883 | 6.430 |

Revenue／OpEx 單位為百分比；GM 為 percentage points。逐筆 midpoint、actual、source hash、實現時間與樣本窗口在 accuracy.json 及各 forecast run 保存。

## 6. Forecast Accuracy

下表為 Model A；金額 MAE 為 USD、EPS 為評估日共同拆股基準的 USD/share。完整 A／B／C、mean/median bias、worst errors 與樣本在 accuracy.json。百分比誤差遇到零 actual 留空；GM 以 basis-point error 為主要解讀。

| Horizon | Metric | N | MAE | MAPE % | sMAPE % | Mean bias | GM MAE bps |
|---|---|---:|---:|---:|---:|---:|---:|
| 1Q | eps | 25 | 0.053 | 24.504 | 17.640 | -0.026 | — |
| 1Q | free_cash_flow | 25 | 3,230,685,916.146 | 70.526 | 40.681 | 362,090,579.028 | — |
| 1Q | gross_margin | 25 | 0.021 | 4.066 | 3.554 | 0.015 | 214.923 |
| 1Q | operating_income | 25 | 972,893,232.979 | 32.362 | 16.424 | 408,631,695.305 | — |
| 1Q | revenue | 25 | 860,564,321.173 | 5.134 | 5.113 | 193,132,978.096 | — |
| 2Q | eps | 24 | 0.109 | 49.268 | 36.393 | -0.055 | — |
| 2Q | free_cash_flow | 24 | 3,777,293,506.438 | 135.434 | 49.254 | -15,772,668.862 | — |
| 2Q | gross_margin | 24 | 0.037 | 6.394 | 5.857 | 0.006 | 370.952 |
| 2Q | operating_income | 24 | 2,073,767,774.266 | 59.388 | 32.828 | -193,651,431.541 | — |
| 2Q | revenue | 24 | 2,319,423,830.806 | 14.240 | 14.110 | -550,940,164.521 | — |
| 4Q | eps | 22 | 0.204 | 72.844 | 57.947 | -0.134 | — |
| 4Q | free_cash_flow | 22 | 5,305,188,167.117 | 166.070 | 61.164 | -1,011,566,932.536 | — |
| 4Q | gross_margin | 22 | 0.059 | 9.434 | 9.111 | -0.009 | 592.770 |
| 4Q | operating_income | 22 | 4,684,182,061.538 | 91.673 | 57.818 | -2,100,387,710.546 | — |
| 4Q | revenue | 22 | 5,831,023,178.203 | 29.269 | 30.282 | -3,142,805,480.276 | — |
| FY1 | eps | 23 | 0.180 | 23.328 | 21.060 | -0.130 | — |
| FY1 | free_cash_flow | 23 | 4,324,933,704.812 | 26.924 | 22.959 | -923,305,108.850 | — |
| FY1 | gross_margin | 23 | 0.021 | 3.171 | 3.146 | -0.001 | 206.413 |
| FY1 | operating_income | 23 | 4,336,667,063.399 | 26.447 | 20.749 | -1,326,951,005.505 | — |
| FY1 | revenue | 23 | 5,461,007,293.216 | 9.918 | 10.046 | -1,718,654,920.215 | — |
| FY2 | eps | 19 | 0.804 | 69.168 | 66.338 | -0.607 | — |
| FY2 | free_cash_flow | 19 | 16,103,869,229.311 | 69.944 | 62.813 | -10,202,187,203.390 | — |
| FY2 | gross_margin | 19 | 0.065 | 9.450 | 9.694 | -0.020 | 647.270 |
| FY2 | operating_income | 19 | 21,038,272,490.315 | 78.581 | 66.208 | -13,773,511,542.624 | — |
| FY2 | revenue | 19 | 26,627,564,704.070 | 27.917 | 32.279 | -20,454,260,903.278 | — |

A/B/C 的 1Q 收入比較（不據此改權重）：

| Model | N | Revenue MAPE % | Revenue sMAPE % |
|---|---:|---:|---:|
| Fixed Deterministic Ensemble | 25 | 7.292 | 7.293 |
| Guidance Anchored Baseline | 25 | 5.134 | 5.113 |
| Mechanical Historical Trend | 25 | 10.205 | 10.256 |

Empirical interval calibration（Model A，1Q）：

| Metric | 有歷史區間且已實現 N | P80 實際涵蓋率 % |
|---|---:|---:|
| eps | 17 | 70.588 |
| free_cash_flow | 17 | 70.588 |
| gross_margin | 17 | 52.941 |
| operating_income | 17 | 70.588 |
| revenue | 17 | 64.706 |

涵蓋率可能明顯偏離 80%；名稱是歷史 empirical band，並非校準保證。早期 insufficient_history 不製造區間。

## 7. Forecast Revision Results

同一 fiscal-year target 比較；跨 Q4 時新 FY1 對應前次 FY2，避免把年度切換當成營運修訂。

| Origin | Same target | Previous label | Old EPS (new basis) | New EPS | Revision % |
|---|---|---|---:|---:|---:|
| FY2021-Q2 | FY2021 | FY1 | 5.299 | 5.963 | 12.515 |
| FY2021-Q3 | FY2021 | FY1 | 5.963 | 6.516 | 9.277 |
| FY2021-Q4 | FY2022 | FY2 | 10.624 | 13.183 | 24.086 |
| FY2022-Q1 | FY2022 | FY1 | 13.183 | 15.268 | 15.820 |
| FY2022-Q2 | FY2022 | FY1 | 3.817 | 3.584 | -6.102 |
| FY2022-Q3 | FY2022 | FY1 | 3.584 | 3.723 | 3.872 |
| FY2022-Q4 | FY2023 | FY2 | 5.127 | 4.009 | -21.807 |
| FY2023-Q1 | FY2023 | FY1 | 4.009 | 4.266 | 6.426 |
| FY2023-Q2 | FY2023 | FY1 | 4.266 | 1.704 | -60.072 |
| FY2023-Q3 | FY2023 | FY1 | 1.704 | 1.657 | -2.731 |
| FY2023-Q4 | FY2024 | FY2 | 3.727 | 3.634 | -2.490 |
| FY2024-Q1 | FY2024 | FY1 | 3.634 | 6.766 | 86.199 |
| FY2024-Q2 | FY2024 | FY1 | 6.766 | 9.525 | 40.777 |
| FY2024-Q3 | FY2024 | FY1 | 9.525 | 11.215 | 17.736 |
| FY2024-Q4 | FY2025 | FY2 | 18.068 | 24.341 | 34.721 |
| FY2025-Q1 | FY2025 | FY1 | 24.341 | 27.367 | 12.432 |
| FY2025-Q2 | FY2025 | FY1 | 2.737 | 2.877 | 5.122 |
| FY2025-Q3 | FY2025 | FY1 | 2.877 | 2.931 | 1.895 |
| FY2025-Q4 | FY2026 | FY2 | 5.626 | 4.992 | -11.265 |
| FY2026-Q1 | FY2026 | FY1 | 4.992 | 4.343 | -13.007 |
| FY2026-Q2 | FY2026 | FY1 | 4.343 | 4.644 | 6.940 |
| FY2026-Q3 | FY2026 | FY1 | 4.644 | 4.755 | 2.397 |
| FY2026-Q4 | FY2027 | FY2 | 9.548 | 10.149 | 6.289 |
| FY2027-Q1 | FY2027 | FY1 | 10.149 | 10.870 | 7.105 |
| FY2027-Q2 | FY2027 | FY1 | 10.870 | 11.137 | 2.461 |

Revenue／FCF／GM／Operating Margin 的逐筆修訂與來源理由同時保存於 history.json 及 forecast_revisions。

## 8. Historical Forward Valuation Coverage

NTM P/E：26/26；Forward FCF Yield：26/26。NTM 為主分母，FY1/FY2 為補充。歷史 context 僅採 strictly earlier 的同模型觀測；前四個季度樣本不足，percentile／z-score unavailable。

## 9. DCF Results / Coverage

Model A DCF：24/26。採明示的 NOPAT cash-conversion FCFF proxy；Year 1–2 取未來八季，Year 3–5 使用固定 growth decay。WACC 8%–12%、terminal growth 2%／2.5%／3%，共 15 cells；base 為 10%／2.5%。低／高值是 sensitivity extremes，不是機率信賴區間。[VALUATION_METHOD.md](VALUATION_METHOD.md)。

## 10. Reverse DCF Results / Coverage

Model A converged reverse DCF：13/26。與 internal 5Y CAGR 使用相同 starting FCFF 與五年時序；正值 starting FCFF／EV、WACC > terminal growth、root bracket 與 residual 檢查均必要。失敗保留 NULL + reason。

## 11. PM Gate Results

完整每筆財務、guidance、forecast、revision、價格與 DCF provenance 保存於 gates.json。PIT 與數值完整度分開驗證：依 Task 34，缺少合格起點的歷史 DCF／Reverse DCF 可以保留 NULL。PARTIAL completeness 不表示使用了未來資料，也不宣稱 Reverse DCF 已有數值。

| Gate | Status | Price | NTM P/E | DCF low / base / high | Implied growth % |
|---|---|---:|---:|---|---:|
| FY2022-Q1 | PIT PASS / completeness PARTIAL | 627.990 | 39.069 | 196.103 / 262.560 / 395.076 | — |
| FY2023-Q3 | PIT PASS / completeness PARTIAL | 157.150 | 52.160 | 74.573 / 102.323 / 157.939 | — |
| FY2024-Q1 | PIT PASS / completeness PARTIAL | 385.230 | 44.759 | 199.114 / 270.017 / 412.020 | — |
| FY2025-Q2 | PIT PASS / completeness PASS | 121.360 | 32.462 | 53.050 / 70.719 / 106.003 | 44.421 |
| FY2027-Q2 | PIT PASS / completeness PASS | 222.860 | 15.491 | 183.600 / 246.232 / 371.447 | 38.517 |

## 12. Test Results

- SQLite：111 passed, 1 skipped in 12.51s
- PostgreSQL：112 passed in 27.77s；實際 server／migration：PostgreSQL 17.10 on aarch64-unknown-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit / 0005_research。
- 重跑 forecast／evaluation 完全相同，table counts 不增加：True。
- SQLite／PostgreSQL 所有正式財務預測與估值數字相同：True。
- 原始來源 SHA-256：120 份，全部通過：True。

## 13. Data Quality / Model Limitations

Reverse DCF 僅 13/26：V1 不把歷史負有效稅率（已知稅務利益）直接當成持續性 FCFF 稅率，亦不補一個正常化稅率，因此 trailing FCFF 起點可 unavailable。逐季組成、原始稅率及來源在 reverse-input-readiness.json；forward DCF 的預測稅率已有獨立穩健政策。保留 M1.1 的原始差異、未確認基準及 conditional missing；不為 forecast 表現改資料規則。早期股數變化樣本不足使用明示 flat baseline；不足八個已實現誤差不產生區間。Forecast nonoperating income、tax、WC／cash conversion 與 FCFF 均有近似性，DCF sensitivity 不是合理價位保證。

Model A warnings（事件數，不代表不同季度數）：`{'insufficient_history_flat_baseline': 2, 'missing_nonpositive_pretax_or_abnormal_rate': 26, 'unverified_share_basis': 12, 'working_capital_ratio_anomaly': 2, 'bounded': 3}`。

## 14. Model Stability

Model A 的 quarter-to-quarter rolling NTM change dispersion 與同年度 EPS/Revenue/FCF revision dispersion 分開衡量；EPS 先統一拆股基準。

| Metric | Forecast change dispersion | Same-target revision dispersion | Revision N | Missing forecast frequency |
|---|---:|---:|---:|---:|
| revenue | 0.161 | 0.120 | 25 | 0.000 |
| eps | 0.331 | 0.247 | 25 | 0.000 |
| free_cash_flow | 0.373 | 0.319 | 25 | 0.000 |

各模型／horizon 的 error dispersion、extreme miss frequency（absolute percentage error >50%）、worst errors 在 accuracy.json，A/B/C stability 在 stability.json。模型評估只針對財務誤差與穩定性，未計算或最大化策略報酬。

## 15. M2-AC1 至 M2-AC16

| Criterion | Result | Evidence |
|---|---|---|
| M2-AC1 | PASS | Immutable/versioned forecast records; database guards and repeat-run evidence |
| M2-AC2 | PASS | PIT cutoff, both checkpoints, future-filing and calibration boundary tests |
| M2-AC3 | PASS | GAAP guidance anchors with retained raw and bias-adjusted values |
| M2-AC4 | PASS | Deterministic NTM/FY1/FY2, fiscal-roll and common-share-basis tests |
| M2-AC5 | PASS | Full income statement derives EPS; forecast weighted shares remain distinct |
| M2-AC6 | PASS | Versioned OCF-capex forecast with explicit cash-conversion approximations |
| M2-AC7 | PASS | Same-target revisions and FY label roll handled explicitly |
| M2-AC8 | PASS | All 26 origin quarters reviewed; realized 1Q/2Q/4Q/FY1/FY2 accuracy and calibration reported |
| M2-AC9 | PASS | Historical forward valuation from internal forecasts |
| M2-AC10 | PASS | Strictly prior valuation distribution and unavailable early samples |
| M2-AC11 | PASS | DCF cash-flow compatibility, 15-cell sensitivity and monotonicity tests |
| M2-AC12 | PASS | Bounded Decimal root solver, convergence and explicit failure handling |
| M2-AC13 | PASS | Historical cash/debt/PIT shares provenance and future-data injection tests |
| M2-AC14 | PASS | Actual SQLite/PostgreSQL tests and numerical parity |
| M2-AC15 | PASS | Forecast SQL/import guard excludes evaluation outcomes, prices and returns |
| M2-AC16 | PASS | No trading decision, score, return optimization or subsequent milestone |

## 16. PM Decisions Required

沒有新增的必要 PM 決策。固定假設、FCFF proxy 與 sparse-history 限制完整揭露，供本里程碑驗收；不要求重開 M1.1 已接受決策。

## 17. Recommendation

建議 PM 給予 **Milestone 2 Final Pass**，並保留 DCF 24/26、Reverse DCF 13/26 與三個 gate 數值完整度 PARTIAL 的限制。此建議以 Task 34 允許不合格歷史輸入保留 NULL 為前提；PIT gate 全部通過。這是研究引擎功能與可重現性的驗收，不是投資績效保證。

Milestone 2 到此停止。未開始後續 milestone；沒有交易建議、Opportunity Score 或 return optimization。

重現：`uv run python scripts/run_m2.py --repeat`；PostgreSQL：`uv run python scripts/validate_m2_postgres.py`；原工作區稽核為 `uv run python scripts/audit_m2.py`（需要 pre-M2 backups 與 PostgreSQL）；最後執行 `uv run python scripts/report_m2.py`。原始稽核結果已包含在交付包，離線 replay 不需要重跑該稽核。
