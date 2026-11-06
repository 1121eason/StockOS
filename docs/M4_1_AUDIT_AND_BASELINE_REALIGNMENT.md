# StockOS M4.1 審計與基線對齊總帳 (Audit & Baseline Realignment Ledger)

> **建立時間**：2026-10-09  
> **版本**：v1.0.0  
> **性質**：產品治理與研究契約正式基線文檔（取代誤導性現況摘要）

---

## 一、驗收狀態正式更正 (Correction of Status)

針對 2026-10-09 產品簡報中關於「M4.1 全面驗收、25/25 測試通過」之表述，經由 PM 與架構師獨立審核，正式更正如下：

| 領域 | 宣稱狀態 | 真實客觀狀態 | 差距與待辦事項 |
|---|---|---|---|
| **工程管線與代碼** | 通過 | **通過** | `src/valuation_engine/` 之 Valuation Bridge V2、Walk-Forward 回測模組與 16/16 單元測試通過。 |
| **7 季 Pilot 資料庫** | 完成 | **完成 (Pilot 範圍)** | `data/m41/fsi/cohort/candidate.db` 包含 7 個代表季度之特徵與挑戰。 |
| **電話會議逐字稿 (Transcripts)** | 包含於分析 | **全部缺失** | 7 季官方電話會議逐字稿尚未納入，目前僅依據 SEC 10-Q/10-K 及 IR 新聞稿。 |
| **真人語意審查卡 (Human Review)** | 全面驗收 | **已填答 35/35，待結算** | 2026-10-07 已由 eason 填答 35 卡並匯入 `qve.db`（25 correct, 10 partially_correct）；尚未完成 Final Pass 正式簽核。 |
| **語意穩定性 (Semantic Stability)** | 默認穩定 | **具保留意見 (10 項待決)** | 10 張 `partially_correct` 審查卡明確指出競爭展望跑分與外部權衡存在波動（如 Q2 特徵數由 27 降至 17，競爭展望由 -0.20 轉為 +0.10），語意穩定性尚未簽核。 |
| **產品整體狀態** | 產品完成 | **研究與策略原型階段** | 核心「每季自動更新管線」與「全歷史 26 季覆蓋」尚未交付。 |

**結論：工程測試通過 $\neq$ 研究品質合格 $\neq$ 產品正式驗收。**  
M4.1 正式 Final Pass 必須在 10 項 `partially_correct` 語意波動處理完畢、電話會議逐字稿補齊後方得宣告完成。

---

## 二、估值架構雙軌契約 (Dual Valuation Contract)

系統廢止「AI 單一修改公允價值」的黑盒子設計，確立雙軌契約：

```
+-----------------------------------------------------------------------------------------+
|                                    1. Quant Baseline                                    |
|   - 依據經審計 SEC 財務數據與 Quant Forecast (Guidance/Carry-forward)                        |
|   - 依據固定 WACC (如 9.0%) 與固定 Terminal Growth (如 3.5%)                                 |
|   - 產出純量化公允價值: quant_baseline_dcf                                                 |
|   - 整合 Reverse DCF 反推市場隱含增長率: market_implied_growth                               |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                           2. AI-Informed Scenarios (Bridge V2)                          |
|   - 依據 Guard G 質化證據與 Advisory Challenges                                          |
|   - 設有 DoubleCountingGuard: 檢驗 Guidance 是否已包含該項樂觀預期                           |
|   - 結構性參數映射 (折現率調整 / 成長率調整)，而非單一黑盒子乘數                              |
|   - 產出多情境區間: Bull / Base / Bear / Stress                                          |
|   - 產出結構性預期差: expectations_gap (模型價值 vs 市場價格)                                |
+-----------------------------------------------------------------------------------------+
```

### 防止雙重計入規則 (Double-Counting Mitigation Rule)
若財務預測引擎之 `guidance_revenue_revision > 0`（即管理層已在財測中上修營收）：
- AI 特徵 `demand_momentum` 與 `product_cycle_strength` 需扣除財測已反映之幅度，或設定正向加成上限（$Cap = 0.5 \times \text{Feature}$）。
- 嚴禁同一項業務增長在財務數字與 AI 定性特徵中重複加成。

---

## 三、回測會計與消融對照規範 (Backtest Accounting & Ablation Standard)

### 1. 換倉會計精確性
- **信號生成時點**：財報公布日盤後（`as_of_date` 23:59:59），完全杜絕未來資訊（Zero Lookahead Bias）。
- **成交執行時點**：次一交易日開盤價（`Next Day Open`）。
- **隔夜價差處理**：
  - 前期持倉在換倉日早晨先以 `Open` 價格評估總淨值（NAV），計入前一交易日收盤至當日開盤之隔夜漲跌（Overnight Price Return）。
  - 計算權重變動之換手率，扣除 10 bps 交易摩擦費用。
  - 以扣除手續費後之淨資產重新配置目標持倉股數與現金。
  - 當日（換倉日）繼續累積 `Open` ➔ `Close` 之日間報酬。

### 2. 強制性 4 軌消融基準 (Mandatory 4-Way Ablation)
任何策略績效報告必須同時提供以下 4 組對照：
1. **Benchmark A (`Buy & Hold NVDA`)**：100% 權益曝險被動持有。
2. **Benchmark B (`Fixed 40/60 Allocation`)**：40% 權益 / 60% 現金固定配置，同等換倉摩擦與 SOFR 現金利息。**（用以分離純降低 Beta 帶來的回撤下降貢獻）**
3. **Benchmark C (`Naive DCF Policy`)**：完全基於 `Quant Baseline DCF` 與市價差距調倉，移除所有 AI 質化特徵。
4. **Strategy (`AI-Informed Valuation Bridge Policy`)**：結合 AI 雙軌預期差與尾部風險調倉。

### 3. Alpha 拆解公式
$$\text{Beta / Allocation Effect} = \text{MDD}(\text{Fixed 40/60}) - \text{MDD}(\text{Buy & Hold})$$
$$\text{Timing / Active Alpha} = \text{CAGR}(\text{Strategy}) - \text{CAGR}(\text{Fixed 40/60})$$
$$\text{AI Incremental Alpha} = \text{Sharpe}(\text{Strategy}) - \text{Sharpe}(\text{Naive DCF})$$

---

## 四、產品優先級路標重整 (Roadmap Realignment)

- **P0（基線對齊與架構治理）**：
  - 實作 Valuation Bridge V2（雙軌輸出、防雙重計入、Reverse DCF 連結）。
  - 修復 Walk-Forward 回測會計（隔夜價差）並實作 4 軌消融基準。
  - 接合既有 `Forecast Revision` 與 `Regime` 判定模組至 `SignalFusion`。
  - 編寫單元測試覆蓋所有上述變更。
- **P1（核心產品主線）**：
  - 建立 SEC 10-Q/10-K 自動化 Ingestion ➔ Snapshot ➔ 人工審查檢核點之可持續運轉管線。
  - 歷史 26 季度逐季覆蓋驗證。
- **P2（多標的遷移驗證）**：
  - TSMC（晶圓代工 Archetype）與 AMD（無晶圓廠競品 Archetype）適配。
- **降級獨立專題 (Deferred to Portfolio Lab)**：
  - 配對交易（Pairs Arbitrage）、波動度目標（Volatility Targeting）、動態風險預算等組合最佳化功能。
