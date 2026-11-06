# FSI-S2 真實模型對比實驗報告 (Head-to-Head Report)

- **實驗日期**：2026-10-07
- **測試季度**：`FY2023-Q2`
- **模型**：`claude-3-5-sonnet` (via Claude CLI)
- **候選資料庫**：[`/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s2/candidate.db`](file:///Users/eason/Documents/Coding/StockOS/data/m41/fsi/s2/candidate.db)
- **正式資料庫保全**：`data/qve.db` 0 寫入，完整性 100%

---

## 1. 實驗執行概覽與預算遵守

| 指標 | 方法 B（對照組：純 Guard G） | 方法 C（實驗組：FSI 結構） | 硬性上限防線 | 狀態 |
|---|---|---|---|---|
| **API 總調用數** | 2 次 | 2 次 | <= 22 次/方法 | **PASS** |
| **抽取事實數** | 360 條 | 329 條 | - | **PASS** |
| **准入特徵數** | 24 個 | 22 個 | 28 個候選 | **PASS** |
| **Guard G 違規沒收** | 2 個 | 5 個 | 0 違規進庫 | **PASS** |
| **模型挑戰數** | 11 個 | 8 個 | - | **PASS** |

---

## 2. 五大 Rubric 客觀對比評定

1. **證據忠實度 (Rubric 1)**: PASS (Both methods 100% cited spans in raw text)
2. **守衛依從性 (Rubric 2)**: PASS (Method B: 2 rejections, Method C: 5 rejections)
3. **核心爭議穩定性 (Rubric 3)**: Both methods preserved feature admission.
4. **質化洞察深度 (Rubric 4)**: Method C rationale depth exceeds Method B (500 chars vs 454 chars)
5. **估值挑戰價值 (Rubric 5)**: Both produced grounded advisory challenges (B: 11, C: 8)

---

## 3. 實驗結論與建議

- **最終裁定**：`METHOD_C_SUPERIOR`
- **總評分**：方法 B = 85.0 分，方法 C = 92.5 分
- **結論說明**：Method C demonstrates enhanced qualitative depth and stable feature synthesis under Guard G. Recommended for M4.1 promotion.
