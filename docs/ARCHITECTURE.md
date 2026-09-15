# Architecture

Milestone 1, model family 0.1.0. One Python package and CLI; no server/UI.

## Flow and trust boundaries

1. `ingestion/http.py`: rate-limited HTTP, bounded retries, explicit errors. SEC identity is environment-only.
2. `ingestion/sec.py`: submissions history including archive pages, accession metadata, companyfacts per-accession extracts. Reporting context `fy/fp` is retained separately from the fact's economic period.
3. `ingestion/ir.py`: isolated, deterministic NVIDIA release adapter. It validates title, fiscal end, statement type, scale and current-quarter columns. It ignores later comparative values. Raw HTML is retained for future qualitative analysis.
4. `db`: PostgreSQL-compatible SQLAlchemy tables with frozen Alembic creation migrations. Monetary calculations use Decimal. Source facts, assumptions, forecasts and calculation snapshots have database-level mutation guards.
5. `normalization/quarterly.py`: allowlisted financial-fact queries filtered by availability, source selection, explicitly additive YTD differencing, lineage-preserving derivations and immutable snapshots.
6. `features/engine.py`: ratios, growth, cash conversion and diagnostic anomaly rules. Same cutoff for current/prior/year-ago periods; missing inputs remain NULL.
7. `forecasts/baseline.py`: management guidance or deterministic latest-quarter carry-forward. Every assumption/source ID is serialized and hashed. Every run appends a forecast.
8. `valuation/ratios.py`: market capitalization, enterprise value, trailing/forward ratios; missing vintage/basis/denominator inputs fail closed. DCF, scenarios and Opportunity Score are typed interfaces only.
9. `backtest/labels.py`: separate consumer of prices, writing only to the label database. No fitting or strategy simulation is implemented.

## Physical isolation

`qve.db` holds feature/source data. `labels.db` alone holds `future_outcomes`, with separate ORM metadata and migrations. A feature connection cannot select that table. Both DB URLs must differ. In production use separate PostgreSQL databases and roles: the feature role must have no credentials/CONNECT privilege on the labels database. A privileged operator with both credentials can bypass application separation; this is not an adversarial sandbox.

## Persistence and reproducibility

- Accession number is unique. Documents are unique by URL + SHA-256.
- Facts have a non-null SHA-256 identity of document, concept, normalized metric, value, unit and economic duration. Unlike nullable compound SQL keys, this behaves consistently in SQLite/PostgreSQL.
- Contradictory facts remain distinct and generate quality issues; no last-write-wins updates.
- Quarterly snapshot identity includes cutoff, selection policy, source fact IDs, numeric payload and normalization version. Features include snapshot ID and feature version.
- Forecast snapshots always append, including identical reruns. Their assumption sets are content-addressed and reusable.
- Ingestion is serial, auditable and atomic per IR release; later release failures do not destroy earlier progress. Concurrent multi-writer ingestion is not supported in M1 (uniqueness constraints remain a last defense).
- `uv.lock` pins the tested environment. Raw bytes and local SQLite databases are deliberately not Git artifacts.

## Sources

SEC contracts and access constraints follow the [official API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) and [fair-access policy](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data). Exchange sessions use the NASDAQ calendar from [pandas-market-calendars](https://pandas-market-calendars.readthedocs.io/en/latest/).


## Milestone 1.1 additions

Immutable availability_evidence assertions sit between source facts and the PIT repository. They have document/content scope and preserve precision, confidence, source and fallback reason. The repository resolves evidence before choosing facts; the guidance forecast path uses the same policy.

corporate_actions records legal and trading dates, share multipliers and official evidence. price_bases links each original provider bar to its original-response document, reconstructed as-traded OHLC, split-comparable OHLC, supplied adjusted values, factors and reconstruction label. No financial calculation uses dividend-adjusted prices with unadjusted EPS. Historical valuation checks both price-field timing and per-share basis, then stores all input lineage.

reconciliation_results preserves paired IR/SEC records; quality_reviews appends classification/resolution to existing issues. A missing SEC identity keeps live SEC acceptance open. Scope is research data hardening only.

ExactNumeric uses native NUMERIC on PostgreSQL and decimal text on SQLite; arithmetic runs in Python Decimal. Frozen core/label storage migrations preserve legacy rows, check semantic hashes and foreign keys, and reinstall immutability guards. See MILESTONE_1_1_REPORT.md for the current acceptance boundaries.

## M4 AI Analyst boundary

`quant/ai_context.py` exports a read-only whitelist from the accepted research/regime modules. `ai/` contains contracts, source/PDF parsing, prompts, provider abstraction, admission/confidence guards and append-only orchestration. No provider receives a DB handle or tools. Valuation is added only in the external `research-view` CLI after AI processing. Quant remains executable with no configured AI provider.

Formal AI consumption requires a completed `ai_analyst_snapshots` join; intermediate call/evidence/feature rows from a failed analysis are audit-only. All M4 tables are protected by SQLite/PostgreSQL immutability triggers. Management credibility is a combined research view, not an AI-generated authoritative score. Proposals remain proposed with NULL numeric ranges and no forecast application endpoint. See AI_ANALYST_METHOD.md for source, confidence and limitation contracts.
