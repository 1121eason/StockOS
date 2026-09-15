# Data dictionary

Generated from the SQLAlchemy field inventory. Dates are inclusive economic dates; all timestamps use explicit UTC storage and ET market interpretation. NULL means unavailable/reserved, never zero.

## Storage and units

Money: USD (IR millions expanded by 1,000,000); shares: actual shares (source scale expanded); EPS: USD/share; percentages: ratios; DSO/DIO/DPO: actual calendar days. The SQL types below are logical types: PostgreSQL uses native NUMERIC, while SQLite stores canonical decimal text and returns Python Decimal. Financial arithmetic uses Decimal, with declared scale and half-even storage rounding; raw SQLite arithmetic over decimal-text columns is not the calculation interface. Legacy approximations are preserved rather than silently rewritten.

## assumption_sets

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| content_hash | VARCHAR | no | SHA-256 of raw content or stable semantic payload. |
| assumptions | JSON | no | Content-addressed forecast assumptions, every method/value/input ID and version. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## companies

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| ticker | VARCHAR(16) | no | Exchange ticker; only NVDA is supported in M1. |
| company_name | VARCHAR | no | Issuer legal name. |
| cik | VARCHAR(10) | no | Zero-padded 10-digit SEC issuer identifier. |
| exchange | VARCHAR | no | Exchange identifier (NASDAQ). |
| currency | VARCHAR(3) | no | ISO 4217 reporting/trading currency (USD). |
| gics_sector | VARCHAR | yes | Traditional GICS sector; NULL without a verified classification source. |
| gics_industry | VARCHAR | yes | Traditional GICS industry; NULL without a verified classification source. |
| gics_subindustry | VARCHAR | yes | Traditional GICS subindustry; NULL without a verified classification source. |
| valuation_archetype | VARCHAR | no | Stable economic business-model category, independent of quarterly regime. |
| archetype_confidence | NUMERIC(8, 6) | yes | Optional 0–1 evidence confidence; no fabricated numeric confidence seeded. |
| updated_at | DATETIME | no | UTC last company-metadata update timestamp. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## ingestion_runs

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| provider | VARCHAR | no | Source/provider identity. |
| started_at | DATETIME | no | UTC ingestion start. |
| completed_at | DATETIME | yes | UTC completion/failure; NULL while running. |
| status | VARCHAR | no | running, completed, partial or failed. |
| records_created | INTEGER | no | New primary observations inserted by the provider run (financial facts or price bars). |
| records_updated | INTEGER | no | Zero for append-only ingestion; audit field reserved. |
| records_skipped | INTEGER | no | Identical observations skipped by identity checks. |
| warnings | JSON | no | Run-level structured warnings; individual warnings also persist as quality issues. |
| errors | JSON | no | Provider/parser exceptions, including fields/URL when available. |
| code_version | VARCHAR | no | Ingestion application version. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## filings

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| accession_number | VARCHAR(32) | no | Unique SEC accession; immutable filing identity. |
| period_end | DATE | yes | Inclusive economic period-end date. |
| filing_date | DATE | no | SEC filing calendar date; not exact availability. |
| form_type | VARCHAR | no | SEC form, including amendment suffix (/A). |
| fiscal_year | INTEGER | yes | NVIDIA fiscal year label; not calendar year. |
| fiscal_quarter | INTEGER | yes | Economic fiscal quarter 1–4, not SEC filing-context fp. |
| accepted_timestamp | DATETIME | yes | SEC acceptance instant, with timezone; may be NULL. |
| source_url | TEXT | no | Official source locator, including per-accession extract fragment where applicable. |
| is_amendment | BOOLEAN | no | Whether SEC form ends in /A. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## market_prices

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| ticker | VARCHAR | no | Exchange ticker; only NVDA is supported in M1. |
| timestamp | DATETIME | no | Price bar opening timestamp; does not make its closing price available. |
| available_at | DATETIME | no | Operational information_available_at cutoff; exact instant or documented conservative bound. |
| price_type | VARCHAR | no | Timeframe and adjustment basis, e.g. daily_split_adjusted_current_vintage. |
| open | NUMERIC(24, 8) | no | Bar opening price in declared basis and currency. |
| high | NUMERIC(24, 8) | no | Bar high in declared basis and currency. |
| low | NUMERIC(24, 8) | no | Bar low in declared basis and currency. |
| close | NUMERIC(24, 8) | no | Bar closing price in declared basis and currency. |
| adjusted_close | NUMERIC(24, 8) | yes | Total-return/vendor-adjusted field only when supplied; unavailable OHLC stays NULL. |
| volume | INTEGER | no | Provider trading volume (shares, provider adjustment convention). |
| currency | VARCHAR | no | ISO 4217 reporting/trading currency (USD). |
| provider | VARCHAR | no | Source/provider identity. |
| retrieved_at | DATETIME | no | UTC time the system retrieved source/price data. |
| content_hash | VARCHAR | no | SHA-256 of raw content or stable semantic payload. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## quarterly_snapshots

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| fiscal_year | INTEGER | no | NVIDIA fiscal year label; not calendar year. |
| fiscal_quarter | INTEGER | no | Economic fiscal quarter 1–4, not SEC filing-context fp. |
| as_of_timestamp | DATETIME | no | UTC calculation cutoff, requiring all feature inputs available by this instant. |
| available_at | DATETIME | no | Operational information_available_at cutoff; exact instant or documented conservative bound. |
| tradable_at | DATETIME | no | First NASDAQ regular-session open at/after availability, stored UTC. |
| model_version | VARCHAR | no | Deterministic model/version identifier; interfaces remain unpopulated in M1. |
| selection_policy | VARCHAR | no | originally_reported or latest_restated after the PIT cutoff filter. |
| payload | JSON | no | Immutable quarter payload: metrics, units, fact IDs, formulas, metadata, missing values and cutoff. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## regime_snapshots

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| as_of_timestamp | DATETIME | no | UTC calculation cutoff, requiring all feature inputs available by this instant. |
| regime | VARCHAR | yes | Time-varying regime label; classifier intentionally not implemented. |
| hypergrowth_probability | NUMERIC(8, 6) | yes | Reserved probability 0–1; NULL in M1; not an archetype. |
| growth_probability | NUMERIC(8, 6) | yes | Reserved probability 0–1; NULL in M1; not an archetype. |
| mature_growth_probability | NUMERIC(8, 6) | yes | Reserved probability 0–1; NULL in M1; not an archetype. |
| cyclical_downturn_probability | NUMERIC(8, 6) | yes | Reserved probability 0–1; NULL in M1; not an archetype. |
| structural_deterioration_probability | NUMERIC(8, 6) | yes | Reserved probability 0–1; NULL in M1; not an archetype. |
| model_version | VARCHAR | no | Deterministic model/version identifier; interfaces remain unpopulated in M1. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## valuation_snapshots

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| as_of_timestamp | DATETIME | no | UTC calculation cutoff, requiring all feature inputs available by this instant. |
| market_price | NUMERIC(30, 8) | yes | Eligible as-traded price; research reconstruction is explicitly labeled and accepted for M1.1. |
| market_cap | NUMERIC(30, 8) | yes | Eligible price times latest known eligible shares outstanding, with consistent split basis, USD. |
| enterprise_value | NUMERIC(30, 8) | yes | Market cap + current/noncurrent debt - cash equivalents, USD. |
| trailing_pe | NUMERIC(30, 8) | yes | Market price / eligible same-share-basis positive TTM diluted EPS. |
| fy1_pe | NUMERIC(30, 8) | yes | Price / eligible actual-vintage annual FY1 forecast EPS; NULL without annual forecast. |
| fy2_pe | NUMERIC(30, 8) | yes | Price / eligible actual-vintage annual FY2 forecast EPS; NULL without annual forecast. |
| ev_ebit | NUMERIC(30, 8) | yes | Enterprise value / positive TTM operating income. |
| ev_ebitda | NUMERIC(30, 8) | yes | Enterprise value / positive TTM (operating income + depreciation/amortization). |
| fcf_yield | NUMERIC(30, 8) | yes | TTM FCF / market cap, ratio. |
| dcf_value | NUMERIC(30, 8) | yes | Reserved deterministic DCF value; NULL in M1. |
| reverse_dcf_growth | NUMERIC(30, 8) | yes | Reserved implied growth rate; NULL in M1. |
| bear_value | NUMERIC(30, 8) | yes | Reserved scenario equity value; NULL in M1. |
| base_value | NUMERIC(30, 8) | yes | Reserved scenario equity value; NULL in M1. |
| bull_value | NUMERIC(30, 8) | yes | Reserved scenario equity value; NULL in M1. |
| probability_weighted_value | NUMERIC(30, 8) | yes | Reserved weighted scenario valuation; no arbitrary weights in M1. |
| model_version | VARCHAR | no | Deterministic model/version identifier; interfaces remain unpopulated in M1. |
| metadata_json | JSON | no | Versioned provenance, approximation, source precision, input IDs or operational context; table-specific. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## forecast_snapshots

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| forecast_as_of | DATETIME | no | Information cutoff for forecasting; distinct from physical created_at. |
| model_version | VARCHAR | no | Deterministic model/version identifier; interfaces remain unpopulated in M1. |
| forecast_horizon | VARCHAR | no | next_quarter currently; fiscal_year required for annual forward P/E. |
| fiscal_period | VARCHAR | no | Forecast/quality issue economic period label. |
| revenue | NUMERIC(30, 8) | yes | Forecast revenue in USD, clearly separate from reported financial_facts. |
| gross_margin | NUMERIC(16, 8) | yes | Forecast gross profit / forecast revenue, ratio. |
| operating_margin | NUMERIC(16, 8) | yes | Forecast operating income / forecast revenue, ratio. |
| eps | NUMERIC(24, 8) | yes | Forecast diluted USD per share in declared share basis. |
| fcf | NUMERIC(30, 8) | yes | Forecast free cash flow in USD; latest FCF margin times forecast revenue. |
| assumption_set_id | INTEGER | no | FK to immutable full assumption set. |
| source_snapshot_id | INTEGER | no | FK to immutable quarterly snapshot. |
| generated_kind | VARCHAR | no | live or historical_replay; replays cannot become actual historical estimates. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## quant_features

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| as_of_timestamp | DATETIME | no | UTC calculation cutoff, requiring all feature inputs available by this instant. |
| fiscal_year | INTEGER | no | NVIDIA fiscal year label; not calendar year. |
| fiscal_quarter | INTEGER | no | Economic fiscal quarter 1–4, not SEC filing-context fp. |
| feature_name | VARCHAR | no | Deterministic or qualitative feature key; AI values never override reported facts. |
| feature_value | NUMERIC(30, 8) | yes | Numeric feature result; ratios, days or USD according to feature definition; NULL if unavailable. |
| feature_version | VARCHAR | no | Formula/diagnostic rule version. |
| source_snapshot_id | INTEGER | no | FK to immutable quarterly snapshot. |
| metadata_json | JSON | no | Versioned provenance, approximation, source precision, input IDs or operational context; table-specific. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## source_documents

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| filing_id | INTEGER | yes | SEC filing FK, NULL for independent IR announcements. |
| document_type | VARCHAR | no | Earnings Release / submissions / companyfacts / accession extract; extensible to other documents. |
| source_url | TEXT | no | Official source locator, including per-accession extract fragment where applicable. |
| published_at | DATETIME | yes | Publication instant or explicitly documented proxy; consult precision/availability metadata. NULL when unknown. |
| retrieved_at | DATETIME | no | UTC time the system retrieved source/price data. |
| content_hash | VARCHAR(64) | no | SHA-256 of raw content or stable semantic payload. |
| source_provider | VARCHAR | no | Origin provider: SEC or NVIDIA IR. |
| raw_path | TEXT | no | Local path to exact content-hashed source bytes. |
| metadata_json | JSON | no | Versioned provenance, approximation, source precision, input IDs or operational context; table-specific. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## ai_features

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| as_of_timestamp | DATETIME | no | UTC calculation cutoff, requiring all feature inputs available by this instant. |
| feature_name | VARCHAR | no | Deterministic or qualitative feature key; AI values never override reported facts. |
| feature_value | NUMERIC(20, 8) | yes | Numeric feature result; ratios, days or USD according to feature definition; NULL if unavailable. |
| confidence | NUMERIC(8, 6) | yes | Evidence/parser confidence; shares use qualitative high/medium, other tables retain their declared numeric/null convention. |
| source_document_id | INTEGER | no | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| model_name | VARCHAR | no | Future AI model identifier (qualitative features only). |
| prompt_version | VARCHAR | no | Future qualitative extraction prompt version. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## availability_evidence

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| source_document_id | INTEGER | no | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| evidence_document_id | INTEGER | no | Hashed source that independently substantiates this assertion. |
| scope | VARCHAR | no | Content scope: financial_fact, guidance, segment; never applied to every disclosure in a quarter. |
| published_at | DATETIME | yes | Publication instant or explicitly documented proxy; consult precision/availability metadata. NULL when unknown. |
| information_available_at | DATETIME | no | UTC conservative information boundary; ET display. Minute evidence uses the end of its stated minute. |
| timestamp_precision | VARCHAR | no | exact, minute, date_only, or explicitly inferred; no inferred time is called exact. |
| timestamp_source | VARCHAR | no | Evidence URL supporting publication time or fallback. |
| timestamp_confidence | VARCHAR | no | Qualitative high/medium/low confidence; precision remains separate. |
| fallback_reason | VARCHAR | yes | Why a conservative availability bound replaces unknown precision. |
| timezone | VARCHAR | no | Source/display zone, America/New_York; storage is UTC. |
| policy_version | VARCHAR | no | Version of the immutable evidence interpretation policy. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## corporate_actions

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| split_date | DATE | no | First trading date on the new per-share basis. |
| effective_date | DATE | no | Legal split/distribution date, which may precede the trading date. |
| action_type | VARCHAR | no | Corporate action type; split currently implemented. |
| ratio_numerator | NUMERIC(18, 8) | no | New shares in the split ratio. |
| ratio_denominator | NUMERIC(18, 8) | no | Old shares in the split ratio. |
| adjustment_factor | NUMERIC(18, 8) | no | New shares per old share; multiply shares and divide per-share values. |
| announced_at | DATETIME | no | Conservative announcement bound; date precision declared in metadata. |
| source_document_id | INTEGER | no | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| metadata_json | JSON | no | Versioned provenance, approximation, source precision, input IDs or operational context; table-specific. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## data_quality_issues

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| company_id | INTEGER | yes | Company foreign key (labels use the matching ID without a cross-DB FK). |
| source_document_id | INTEGER | yes | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| issue_type | VARCHAR | no | Missing, conflict, publication precision, source mismatch/failure, formula-definition discrepancy or unsupported parsing. |
| severity | VARCHAR | no | warning or error; no silent failures. |
| metric_name | VARCHAR | yes | Canonical metric name; see metric definitions below. |
| fiscal_period | VARCHAR | yes | Forecast/quality issue economic period label. |
| details | JSON | no | Structured issue evidence and affected context. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## financial_facts

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR(64) | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| filing_id | INTEGER | yes | SEC filing FK, NULL for independent IR announcements. |
| metric_name | VARCHAR | no | Canonical metric name; see metric definitions below. |
| taxonomy_name | VARCHAR | no | Original namespace:concept or IR:row label; never discarded after normalization. |
| value | NUMERIC(30, 8) | no | Reported numeric amount in unit; source values, not forecasts. |
| unit | VARCHAR | no | USD, shares, USD/shares or ratio (0.75 means 75%). |
| fiscal_year | INTEGER | no | NVIDIA fiscal year label; not calendar year. |
| fiscal_quarter | INTEGER | no | Economic fiscal quarter 1–4, not SEC filing-context fp. |
| duration_kind | VARCHAR | no | instant, quarter, ytd or annual; explicit, never inferred from value magnitude. |
| frame | VARCHAR | yes | Original SEC XBRL frame when present; not authoritative for fiscal labeling. |
| period_start | DATE | yes | Inclusive duration start; NULL for instant balance facts. |
| period_end | DATE | no | Inclusive economic period-end date. |
| reported_at | DATETIME | no | Public-report proxy/upper bound with precision policy recorded. |
| available_at | DATETIME | no | Operational information_available_at cutoff; exact instant or documented conservative bound. |
| earnings_release_timestamp | DATETIME | yes | Exact earnings-release instant if independently established; otherwise NULL. |
| tradable_at | DATETIME | no | First NASDAQ regular-session open at/after availability, stored UTC. |
| source_document_id | INTEGER | no | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| source_priority | INTEGER | no | Smaller wins equal-time source ties: SEC 10 + alias rank, NVIDIA IR 20. |
| is_restated | BOOLEAN | no | Changed later value candidate, including possible split/presentation revisions; not a proven accounting restatement. |
| formula_version | VARCHAR | no | Version of normalization/derivation definition. |
| metadata_json | JSON | no | Versioned provenance, approximation, source precision, input IDs or operational context; table-specific. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## guidance_items

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| fiscal_year | INTEGER | no | NVIDIA fiscal year label; not calendar year. |
| fiscal_quarter | INTEGER | no | Economic fiscal quarter 1–4, not SEC filing-context fp. |
| guidance_for_period | VARCHAR | no | Target such as FY2027-Q3 or FY2027; distinct from reporting quarter. |
| metric_name | VARCHAR | no | Canonical metric name; see metric definitions below. |
| low_value | NUMERIC(30, 8) | yes | Published/arithmetically implied low endpoint; NULL if no range. |
| mid_value | NUMERIC(30, 8) | yes | Published midpoint or midpoint of an explicit range. |
| high_value | NUMERIC(30, 8) | yes | Published/arithmetically implied high endpoint; NULL if no range. |
| unit | VARCHAR | no | USD, shares, USD/shares or ratio (0.75 means 75%). |
| guidance_type | VARCHAR | no | Management outlook category; future qualitative guidance can use raw_text. |
| basis | VARCHAR | no | GAAP versus non-GAAP basis; baseline uses GAAP only. |
| raw_text | TEXT | no | Exact matched source guidance text; full original document also retained. |
| published_at | DATETIME | yes | Publication instant or explicitly documented proxy; consult precision/availability metadata. NULL when unknown. |
| available_at | DATETIME | no | Operational information_available_at cutoff; exact instant or documented conservative bound. |
| source_document_id | INTEGER | no | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| confidence | NUMERIC(8, 6) | yes | Evidence/parser confidence; shares use qualitative high/medium, other tables retain their declared numeric/null convention. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## price_bases

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| market_price_id | INTEGER | no | Original provider bar, including provider/retrieval/hash lineage. |
| source_document_id | INTEGER | yes | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| raw_open | NUMERIC(24, 8) | yes | As-traded OHLC basis; raw_origin explicitly distinguishes provider data from split reconstruction. |
| raw_high | NUMERIC(24, 8) | yes | As-traded OHLC basis; raw_origin explicitly distinguishes provider data from split reconstruction. |
| raw_low | NUMERIC(24, 8) | yes | As-traded OHLC basis; raw_origin explicitly distinguishes provider data from split reconstruction. |
| raw_close | NUMERIC(24, 8) | yes | As-traded OHLC basis; raw_origin explicitly distinguishes provider data from split reconstruction. |
| raw_origin | VARCHAR | no | provider_as_traded or research_reconstructed; never interchangeable observation claims. |
| split_adjusted_open | NUMERIC(24, 8) | no | Split-only comparable price at basis_date; no dividend adjustment in valuation. |
| split_adjusted_high | NUMERIC(24, 8) | no | Split-only comparable price at basis_date; no dividend adjustment in valuation. |
| split_adjusted_low | NUMERIC(24, 8) | no | Split-only comparable price at basis_date; no dividend adjustment in valuation. |
| split_adjusted_close | NUMERIC(24, 8) | no | Split-only comparable price at basis_date; no dividend adjustment in valuation. |
| adjusted_open | NUMERIC(24, 8) | yes | Total-return/vendor-adjusted field only when supplied; unavailable OHLC stays NULL. |
| adjusted_high | NUMERIC(24, 8) | yes | Total-return/vendor-adjusted field only when supplied; unavailable OHLC stays NULL. |
| adjusted_low | NUMERIC(24, 8) | yes | Total-return/vendor-adjusted field only when supplied; unavailable OHLC stays NULL. |
| adjusted_close | NUMERIC(24, 8) | yes | Total-return/vendor-adjusted field only when supplied; unavailable OHLC stays NULL. |
| split_factor | NUMERIC(18, 8) | no | Subsequent split multiplier between the bar date and vendor anchor date. |
| total_adjustment_factor | NUMERIC(24, 12) | yes | Provider adjusted close divided by as-traded close; includes dividend adjustments when supplied. |
| basis_date | DATE | no | Date identifying the per-share denomination/adjustment anchor. |
| metadata_json | JSON | no | Versioned provenance, approximation, source precision, input IDs or operational context; table-specific. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## segment_facts

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| fiscal_year | INTEGER | no | NVIDIA fiscal year label; not calendar year. |
| fiscal_quarter | INTEGER | no | Economic fiscal quarter 1–4, not SEC filing-context fp. |
| segment_name | VARCHAR | no | Historical source spelling; never remapped to a current segment taxonomy. |
| classification_kind | VARCHAR | no | market_platform versus reporting_segment; do not aggregate across these categories. |
| metric_name | VARCHAR | no | Canonical metric name; see metric definitions below. |
| value | NUMERIC(30, 8) | no | Reported numeric amount in unit; source values, not forecasts. |
| unit | VARCHAR | no | USD, shares, USD/shares or ratio (0.75 means 75%). |
| available_at | DATETIME | no | Operational information_available_at cutoff; exact instant or documented conservative bound. |
| source_document_id | INTEGER | no | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## share_count_observations

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR(64) | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| share_class | VARCHAR | no | Mapped economic share class; current NVDA pipeline accepts unsegmented common shares only. |
| share_count | NUMERIC(30, 8) | no | Absolute shares outstanding on the original reported basis, not weighted-average diluted shares. |
| shares_as_of_date | DATE | no | Economic instant described by the share count; distinct from its publication date. |
| published_at | DATETIME | no | Publication instant or explicitly documented proxy; consult precision/availability metadata. NULL when unknown. |
| available_at | DATETIME | no | Operational information_available_at cutoff; exact instant or documented conservative bound. |
| source_document_id | INTEGER | no | FK to source URL, hash, raw bytes, retrieval and publication metadata. |
| source_type | VARCHAR | no | sec_cover, sec_structured, or official_disclosure; used for same-date priority. |
| taxonomy_concept | VARCHAR | yes | Original share disclosure taxonomy and concept, when applicable. |
| split_basis | JSON | no | JSON with explicit original basis date, as_reported kind and shares unit. |
| normalized_share_count | NUMERIC(30, 8) | no | Absolute share count on normalized_basis_date; current/valuation bases are resolved at query time. |
| normalized_basis_date | DATE | no | Original denomination date of stored normalized shares; never silently updated to today's basis. |
| confidence | VARCHAR | no | Evidence/parser confidence; shares use qualitative high/medium, other tables retain their declared numeric/null convention. |
| metadata_json | JSON | no | Versioned provenance, approximation, source precision, input IDs or operational context; table-specific. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## quality_reviews

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| issue_id | INTEGER | no | Original data-quality issue; reviews append without deleting history. |
| classification | VARCHAR | no | Expected Missing, Source Limitation, Parser Defect, Timestamp Gap, Definition Difference, or Reconciliation Conflict. |
| blocking | BOOLEAN | no | Whether this unresolved issue blocks the stated acceptance/use case. |
| resolution | VARCHAR | no | Open, resolved with evidence, excluded context, or documented limitation. |
| evidence | JSON | no | Structured source IDs, observations and explanation supporting the review. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## reconciliation_results

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| identity_key | VARCHAR | no | SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity. |
| left_fact_id | INTEGER | no | IR fact retained verbatim during SEC/IR reconciliation. |
| right_fact_id | INTEGER | no | SEC fact retained verbatim during SEC/IR reconciliation. |
| status | VARCHAR | no | running, completed, partial or failed. |
| blocking | BOOLEAN | no | Whether this unresolved issue blocks the stated acceptance/use case. |
| canonical_rule | VARCHAR | no | Cutoff-aware priority policy; never an overwrite of source values. |
| metadata_json | JSON | no | Versioned provenance, approximation, source precision, input IDs or operational context; table-specific. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## future_outcomes

| Field | SQL type | Nullable | Meaning |
|---|---|---|---|
| company_id | INTEGER | no | Company foreign key (labels use the matching ID without a cross-DB FK). |
| anchor_timestamp | DATETIME | no | First tradable regular-session open following the release availability bound. |
| label_as_of | DATETIME | no | Label observation/maturity cutoff, never a forecasting feature. |
| price_3m | NUMERIC(24, 8) | yes | Close on first regular session at/after anchor + 3 calendar months; NULL if missing/immature. |
| price_6m | NUMERIC(24, 8) | yes | Close on first regular session at/after anchor + 6 calendar months; NULL if missing/immature. |
| price_12m | NUMERIC(24, 8) | yes | Close on first regular session at/after anchor + 12 calendar months; NULL if missing/immature. |
| price_24m | NUMERIC(24, 8) | yes | Close on first regular session at/after anchor + 24 calendar months; NULL if missing/immature. |
| return_3m | NUMERIC(24, 8) | yes | price_3m / entry open - 1, split-adjusted price return excluding dividends; label only. |
| return_6m | NUMERIC(24, 8) | yes | price_6m / entry open - 1, split-adjusted price return excluding dividends; label only. |
| return_12m | NUMERIC(24, 8) | yes | price_12m / entry open - 1, split-adjusted price return excluding dividends; label only. |
| return_24m | NUMERIC(24, 8) | yes | price_24m / entry open - 1, split-adjusted price return excluding dividends; label only. |
| max_drawdown_12m | NUMERIC(24, 8) | yes | Worst daily-close peak-to-trough price decline; NULL until full window observed. |
| max_upside_12m | NUMERIC(24, 8) | yes | Highest daily close relative to entry open; NULL until full window observed. |
| alignment_json | JSON | no | Pre-announcement close, first open, 1/5/20 session closes, provider/basis, input IDs/hash and label formula version. |
| id | INTEGER | no | Database-local immutable row identifier. |
| created_at | DATETIME | no | UTC system creation timestamp; not historical public availability. |

## Metric mapping and formulas

`normalization/mapping.py` contains the ordered XBRL concept aliases. Source taxonomy, normalized name and formula version remain attached to every fact. IR aliases live only in the provider adapter.

| Metric / feature | Definition |
|---|---|
| FCF | OCF minus positive purchases CapEx |
| Debt | current plus noncurrent debt; NULL if either is absent |
| Gross / operating / FCF margin | profit or FCF divided by revenue |
| Revenue / EPS / FCF YoY, QoQ | current / previous - 1; NULL when previous <= 0 or missing |
| AR / inventory YoY | same positive-base growth formula |
| Margin YoY/QoQ change | current margin minus prior margin, ratio points |
| CapEx / revenue; SBC / revenue | respective expense or cash-outflow amount divided by revenue |
| DSO | average(beginning, ending AR) / quarterly revenue × actual period days |
| Inventory days | average inventory / quarterly COGS × actual days |
| DPO | average accounts payable / quarterly COGS × actual days (proxy for purchases) |
| Cash conversion cycle | DSO + inventory days - DPO |
| Missing beginning balance | ending balance fallback; approximation flag and method preserved |
| Forecast revision | (new EPS - old EPS) / old EPS; NULL if old <= 0 |

`cash_and_marketable_securities` preserves older combined balance-sheet presentation; it is never arbitrarily split. `company_reported_fcf` retains NVIDIA's additional equipment-payment deduction. `gross_margin_reported` is the rounded announced ratio; the feature gross margin uses underlying gross profit/revenue.

Anomalies: revenue YoY >20% with FCF YoY <0; AR/inventory growth > revenue growth +20 percentage points; EPS YoY >20% with FCF YoY <0. These fixed diagnostic examples are versioned and are not buy/sell thresholds. EPS comparisons use formal corporate-action conversion when both source bases are verified; otherwise conservative NULL behavior remains.

Segment observations preserve names and whether they are reporting segments or market platforms. Data Center/Gaming/etc. narrative values can be rounded to billions/millions as published; no implied extra precision. Exact Compute & Networking / Graphics reporting-segment extraction is not implemented.

## M3.1 regime_snapshots additions

Migration `0007_regime_confidence`. New fields are nullable only for preserved legacy V1 rows. Corrected snapshots populate all fields and remain append-only.

| Field | Meaning |
|---|---|
| confirmed_regime | Persistence-approved economic regime; primary_regime compatibility alias |
| candidate_regime | Strongest eligible current prototype evidence |
| transition_status | STABLE / PENDING_CONFIRMATION / LOW_CONFIDENCE / STRONG_OVERRIDE_PENDING_GUARD |
| evidence_confidence | Current prototype separation, support, consistency and strength, fraction |
| data_quality_confidence | Active observation completeness with relevant quality penalties, fraction |
| history_sufficiency | Minimum explicit rolling/revision/error history coverage, fraction |
| composite_confidence | Evidence × DQ × explicit history multiplier; confidence compatibility alias |
| candidate_probability | Candidate's final normalized probability |
| probability_gap_to_second_candidate | Final candidate probability minus runner-up |
| metadata_json.inputs | Complete feature_lineage, input_observations, active/excluded quality graph |
| metadata_json.state | Full probabilities, scores, confidence components, counter, structural guard and reasons |

See REGIME_METHOD.md and REGIME_OUTPUT_CONTRACT.md for formulas and mandatory atomic downstream semantics.

## M4 AI Analyst tables

All tables below are append-only. created_at is execution time; information_cutoff and as_of_timestamp carry historical semantics. Formal features require a completed AIAnalystSnapshot; intermediate failed-run rows are audit-only. Legacy ai_features is preserved and not promoted into M4.

### ai_analysis_runs

| Column | Storage | Nullable |
|---|---|---|
| company_id | INTEGER | False |
| quarter | VARCHAR | False |
| as_of_timestamp | DATETIME | False |
| information_cutoff | DATETIME | False |
| source_document_ids | JSON | False |
| model_provider | VARCHAR | False |
| model_name | VARCHAR | False |
| model_version | VARCHAR | False |
| prompt_version | VARCHAR | False |
| schema_version | VARCHAR | False |
| policy_version | VARCHAR | False |
| request_hash | VARCHAR | False |
| context_json | JSON | False |
| settings_json | JSON | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_analysis_events

| Column | Storage | Nullable |
|---|---|---|
| analysis_run_id | INTEGER | False |
| status | VARCHAR | False |
| details | JSON | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_analyst_features

| Column | Storage | Nullable |
|---|---|---|
| company_id | INTEGER | False |
| analysis_run_id | INTEGER | False |
| feature_name | VARCHAR | False |
| feature_value | NUMERIC(20, 8) | False |
| confidence | NUMERIC(20, 8) | False |
| direction | VARCHAR | False |
| time_horizon | VARCHAR | False |
| evidence_count | INTEGER | False |
| source_document_ids | JSON | False |
| prompt_version | VARCHAR | False |
| model_version | VARCHAR | False |
| rationale | TEXT | False |
| metadata_json | JSON | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_analyst_snapshots

| Column | Storage | Nullable |
|---|---|---|
| company_id | INTEGER | False |
| as_of_timestamp | DATETIME | False |
| analysis_run_id | INTEGER | False |
| demand_momentum | NUMERIC(20, 8) | True |
| pricing_power | NUMERIC(20, 8) | True |
| supply_constraint | NUMERIC(20, 8) | True |
| product_cycle_strength | NUMERIC(20, 8) | True |
| competition_outlook | NUMERIC(20, 8) | True |
| customer_financing_quality | NUMERIC(20, 8) | True |
| working_capital_quality | NUMERIC(20, 8) | True |
| regulatory_outlook | NUMERIC(20, 8) | True |
| management_confidence | NUMERIC(20, 8) | True |
| guidance_visibility | NUMERIC(20, 8) | True |
| structural_outlook | NUMERIC(20, 8) | True |
| overall_qualitative_confidence | NUMERIC(20, 8) | False |
| prompt_version | VARCHAR | False |
| model_version | VARCHAR | False |
| metadata_json | JSON | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_challenges

| Column | Storage | Nullable |
|---|---|---|
| analysis_run_id | INTEGER | False |
| kind | VARCHAR | False |
| description | TEXT | False |
| direction | VARCHAR | False |
| target_variable | VARCHAR | False |
| time_horizon | VARCHAR | False |
| evidence_ids | JSON | False |
| confidence | NUMERIC(20, 8) | False |
| metadata_json | JSON | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_human_reviews

| Column | Storage | Nullable |
|---|---|---|
| analysis_run_id | INTEGER | False |
| category | VARCHAR | False |
| verdict | VARCHAR | False |
| reviewer | VARCHAR | False |
| notes | TEXT | False |
| evidence_ids | JSON | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_provider_calls

| Column | Storage | Nullable |
|---|---|---|
| analysis_run_id | INTEGER | False |
| stage | VARCHAR | False |
| attempt | INTEGER | False |
| exact_prompt | JSON | False |
| request_hash | VARCHAR | False |
| response_hash | VARCHAR | True |
| raw_output | JSON | False |
| status | VARCHAR | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_unsupported_claims

| Column | Storage | Nullable |
|---|---|---|
| analysis_run_id | INTEGER | False |
| stage | VARCHAR | False |
| reason | VARCHAR | False |
| raw_claim | JSON | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### model_adjustment_proposals

| Column | Storage | Nullable |
|---|---|---|
| company_id | INTEGER | False |
| analysis_run_id | INTEGER | False |
| target_model | VARCHAR | False |
| target_variable | VARCHAR | False |
| direction | VARCHAR | False |
| suggested_range_low | NUMERIC(20, 8) | True |
| suggested_range_high | NUMERIC(20, 8) | True |
| confidence | NUMERIC(20, 8) | False |
| rationale | TEXT | False |
| evidence_ids | JSON | False |
| status | VARCHAR | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_evidence

| Column | Storage | Nullable |
|---|---|---|
| analysis_run_id | INTEGER | False |
| evidence_key | VARCHAR | False |
| source_document_id | INTEGER | False |
| source_hash | VARCHAR | False |
| section | VARCHAR | False |
| block_id | VARCHAR | False |
| span | TEXT | False |
| span_hash | VARCHAR | False |
| speaker | VARCHAR | True |
| topic | VARCHAR | False |
| implication | VARCHAR | False |
| published_at | DATETIME | True |
| available_at | DATETIME | False |
| metadata_json | JSON | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

### ai_feature_evidence

| Column | Storage | Nullable |
|---|---|---|
| feature_id | INTEGER | False |
| evidence_id | INTEGER | False |
| role | VARCHAR | False |
| id | INTEGER | False |
| created_at | DATETIME | False |

Feature confidence/direction, source/quote hashes, supporting/contradicting evidence roles and source-window semantics are specified in AI_ANALYST_METHOD.md. Proposals are advisory only; numeric ranges are NULL in V1. Human review verdicts require actual reviewer identity and same-run evidence IDs.
