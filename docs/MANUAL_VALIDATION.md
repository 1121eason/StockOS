# Latest available quarter — independent official-source check

Checked: FY2027 Q2, period ended July 26, 2026; announcement dated August 26, 2026. Review performed September 12, 2026 by separately reading the [official NVIDIA release](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027), then comparing these transcribed check values against the persisted parser output. This is not an independent human audit or an SEC reconciliation.

| Metric | Official figure | Persisted/derived result |
|---|---:|---|
| Revenue | $96,221m | Match |
| GAAP gross margin | 75.0% | Match to published rounded ratio |
| Operating income | $63,734m | Match |
| GAAP diluted EPS | $2.46 | Match |
| Operating cash flow, quarter | $24,077m | Match; not six-month YTD |
| Purchases CapEx, quarter | $2,677m | Match; normalized positive outflow |
| Engine FCF | $21,400m | OCF minus purchases CapEx |
| NVIDIA-reported FCF | $21,341m | Match; additionally deducts $59m principal payments |
| Accounts receivable | $63,059m | Match |
| Inventory | $31,575m | Match |
| Data Center revenue | $89.0bn | Match to rounded narrative source |
| Q3 revenue guidance | $108.0bn ±2% | $105.84bn / $108.0bn / $110.16bn |
| Q3 GAAP gross-margin guidance | 74.0% ±50bp | 73.5% / 74.0% / 74.5% |

Statement income rows, cash-flow rows, balance-sheet rows, market-platform highlights and management outlook were read separately. The release's tax range applies to the full fiscal year, so it is stored as annual guidance rather than misrepresented as quarterly guidance. Exact intraday publication time was not established.

Machine-readable check values: `tests/fixtures/nvda_fy2027q2_verified.json`. Reproduce the comparison with `uv run python scripts/verify_official_snapshot.py`; the generated evidence is `data/manual-validation.json`. All 18 numeric checks must pass.
