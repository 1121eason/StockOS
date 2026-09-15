"""Generate field inventory from the ORM, with shared and table-specific semantics."""

from pathlib import Path

from valuation_engine.db.schema import Base, LabelBase

descriptions = {
    "id": "Database-local immutable row identifier.",
    "created_at": "UTC system creation timestamp; not historical public availability.",
    "updated_at": "UTC last company-metadata update timestamp.",
    "company_id": "Company foreign key (labels use the matching ID without a cross-DB FK).",
    "ticker": "Exchange ticker; only NVDA is supported in M1.",
    "company_name": "Issuer legal name.",
    "cik": "Zero-padded 10-digit SEC issuer identifier.",
    "exchange": "Exchange identifier (NASDAQ).",
    "currency": "ISO 4217 reporting/trading currency (USD).",
    "gics_sector": "Traditional GICS sector; NULL without a verified classification source.",
    "gics_industry": "Traditional GICS industry; NULL without a verified classification source.",
    "gics_subindustry": "Traditional GICS subindustry; NULL without a verified classification source.",
    "valuation_archetype": "Stable economic business-model category, independent of quarterly regime.",
    "archetype_confidence": "Optional 0–1 evidence confidence; no fabricated numeric confidence seeded.",
    "filing_id": "SEC filing FK, NULL for independent IR announcements.",
    "accession_number": "Unique SEC accession; immutable filing identity.",
    "form_type": "SEC form, including amendment suffix (/A).",
    "fiscal_year": "NVIDIA fiscal year label; not calendar year.",
    "fiscal_quarter": "Economic fiscal quarter 1–4, not SEC filing-context fp.",
    "period_end": "Inclusive economic period-end date.",
    "period_start": "Inclusive duration start; NULL for instant balance facts.",
    "filing_date": "SEC filing calendar date; not exact availability.",
    "accepted_timestamp": "SEC acceptance instant, with timezone; may be NULL.",
    "is_amendment": "Whether SEC form ends in /A.",
    "source_url": "Official source locator, including per-accession extract fragment where applicable.",
    "document_type": "Earnings Release / submissions / companyfacts / accession extract; extensible to other documents.",
    "published_at": "Publication instant or explicitly documented proxy; consult precision/availability metadata. NULL when unknown.",
    "retrieved_at": "UTC time the system retrieved source/price data.",
    "content_hash": "SHA-256 of raw content or stable semantic payload.",
    "source_provider": "Origin provider: SEC or NVIDIA IR.",
    "raw_path": "Local path to exact content-hashed source bytes.",
    "metadata_json": "Versioned provenance, approximation, source precision, input IDs or operational context; table-specific.",
    "identity_key": "SHA-256 non-null semantic uniqueness key; avoids nullable SQL uniqueness ambiguity.",
    "metric_name": "Canonical metric name; see metric definitions below.",
    "taxonomy_name": "Original namespace:concept or IR:row label; never discarded after normalization.",
    "value": "Reported numeric amount in unit; source values, not forecasts.",
    "unit": "USD, shares, USD/shares or ratio (0.75 means 75%).",
    "duration_kind": "instant, quarter, ytd or annual; explicit, never inferred from value magnitude.",
    "frame": "Original SEC XBRL frame when present; not authoritative for fiscal labeling.",
    "reported_at": "Public-report proxy/upper bound with precision policy recorded.",
    "available_at": "Operational information_available_at cutoff; exact instant or documented conservative bound.",
    "earnings_release_timestamp": "Exact earnings-release instant if independently established; otherwise NULL.",
    "tradable_at": "First NASDAQ regular-session open at/after availability, stored UTC.",
    "source_document_id": "FK to source URL, hash, raw bytes, retrieval and publication metadata.",
    "source_priority": "Smaller wins equal-time source ties: SEC 10 + alias rank, NVIDIA IR 20.",
    "is_restated": "Changed later value candidate, including possible split/presentation revisions; not a proven accounting restatement.",
    "formula_version": "Version of normalization/derivation definition.",
    "segment_name": "Historical source spelling; never remapped to a current segment taxonomy.",
    "classification_kind": "market_platform versus reporting_segment; do not aggregate across these categories.",
    "guidance_for_period": "Target such as FY2027-Q3 or FY2027; distinct from reporting quarter.",
    "low_value": "Published/arithmetically implied low endpoint; NULL if no range.",
    "mid_value": "Published midpoint or midpoint of an explicit range.",
    "high_value": "Published/arithmetically implied high endpoint; NULL if no range.",
    "guidance_type": "Management outlook category; future qualitative guidance can use raw_text.",
    "basis": "GAAP versus non-GAAP basis; baseline uses GAAP only.",
    "raw_text": "Exact matched source guidance text; full original document also retained.",
    "confidence": "Evidence/parser confidence; shares use qualitative high/medium, other tables retain their declared numeric/null convention.",
    "timestamp": "Price bar opening timestamp; does not make its closing price available.",
    "price_type": "Timeframe and adjustment basis, e.g. daily_split_adjusted_current_vintage.",
    "open": "Bar opening price in declared basis and currency.",
    "high": "Bar high in declared basis and currency.",
    "low": "Bar low in declared basis and currency.",
    "close": "Bar closing price in declared basis and currency.",
    "adjusted_close": "Vendor current dividend/split-adjusted close; never conflated with raw close.",
    "volume": "Provider trading volume (shares, provider adjustment convention).",
    "provider": "Source/provider identity.",
    "as_of_timestamp": "UTC calculation cutoff, requiring all feature inputs available by this instant.",
    "model_version": "Deterministic model/version identifier; interfaces remain unpopulated in M1.",
    "selection_policy": "originally_reported or latest_restated after the PIT cutoff filter.",
    "payload": "Immutable quarter payload: metrics, units, fact IDs, formulas, metadata, missing values and cutoff.",
    "assumptions": "Content-addressed forecast assumptions, every method/value/input ID and version.",
    "forecast_as_of": "Information cutoff for forecasting; distinct from physical created_at.",
    "forecast_horizon": "next_quarter currently; fiscal_year required for annual forward P/E.",
    "fiscal_period": "Forecast/quality issue economic period label.",
    "revenue": "Forecast revenue in USD, clearly separate from reported financial_facts.",
    "gross_margin": "Forecast gross profit / forecast revenue, ratio.",
    "operating_margin": "Forecast operating income / forecast revenue, ratio.",
    "eps": "Forecast diluted USD per share in declared share basis.",
    "fcf": "Forecast free cash flow in USD; latest FCF margin times forecast revenue.",
    "assumption_set_id": "FK to immutable full assumption set.",
    "source_snapshot_id": "FK to immutable quarterly snapshot.",
    "generated_kind": "live or historical_replay; replays cannot become actual historical estimates.",
    "feature_name": "Deterministic or qualitative feature key; AI values never override reported facts.",
    "feature_value": "Numeric feature result; ratios, days or USD according to feature definition; NULL if unavailable.",
    "feature_version": "Formula/diagnostic rule version.",
    "market_price": "Eligible as-traded price; research reconstruction is explicitly labeled and accepted for M1.1.",
    "market_cap": "Eligible price times latest known eligible shares outstanding, with consistent split basis, USD.",
    "enterprise_value": "Market cap + current/noncurrent debt - cash equivalents, USD.",
    "trailing_pe": "Market price / eligible same-share-basis positive TTM diluted EPS.",
    "fy1_pe": "Price / eligible actual-vintage annual FY1 forecast EPS; NULL without annual forecast.",
    "fy2_pe": "Price / eligible actual-vintage annual FY2 forecast EPS; NULL without annual forecast.",
    "ev_ebit": "Enterprise value / positive TTM operating income.",
    "ev_ebitda": "Enterprise value / positive TTM (operating income + depreciation/amortization).",
    "fcf_yield": "TTM FCF / market cap, ratio.",
    "dcf_value": "Reserved deterministic DCF value; NULL in M1.",
    "reverse_dcf_growth": "Reserved implied growth rate; NULL in M1.",
    "bear_value": "Reserved scenario equity value; NULL in M1.",
    "base_value": "Reserved scenario equity value; NULL in M1.",
    "bull_value": "Reserved scenario equity value; NULL in M1.",
    "probability_weighted_value": "Reserved weighted scenario valuation; no arbitrary weights in M1.",
    "regime": "Time-varying regime label; classifier intentionally not implemented.",
    "model_name": "Future AI model identifier (qualitative features only).",
    "prompt_version": "Future qualitative extraction prompt version.",
    "anchor_timestamp": "First tradable regular-session open following the release availability bound.",
    "label_as_of": "Label observation/maturity cutoff, never a forecasting feature.",
    "max_drawdown_12m": "Worst daily-close peak-to-trough price decline; NULL until full window observed.",
    "max_upside_12m": "Highest daily close relative to entry open; NULL until full window observed.",
    "alignment_json": "Pre-announcement close, first open, 1/5/20 session closes, provider/basis, input IDs/hash and label formula version.",
    "started_at": "UTC ingestion start.",
    "completed_at": "UTC completion/failure; NULL while running.",
    "status": "running, completed, partial or failed.",
    "records_created": "New primary observations inserted by the provider run (financial facts or price bars).",
    "records_updated": "Zero for append-only ingestion; audit field reserved.",
    "records_skipped": "Identical observations skipped by identity checks.",
    "warnings": "Run-level structured warnings; individual warnings also persist as quality issues.",
    "errors": "Provider/parser exceptions, including fields/URL when available.",
    "code_version": "Ingestion application version.",
    "issue_type": "Missing, conflict, publication precision, source mismatch/failure, formula-definition discrepancy or unsupported parsing.",
    "severity": "warning or error; no silent failures.",
    "details": "Structured issue evidence and affected context.",
}
for regime in (
    "hypergrowth",
    "growth",
    "mature_growth",
    "cyclical_downturn",
    "structural_deterioration",
):
    descriptions[regime + "_probability"] = (
        "Reserved probability 0–1; NULL in M1; not an archetype."
    )
for n in (3, 6, 12, 24):
    descriptions[f"price_{n}m"] = (
        f"Close on first regular session at/after anchor + {n} calendar months; NULL if missing/immature."
    )
    descriptions[f"return_{n}m"] = (
        f"price_{n}m / entry open - 1, split-adjusted price return excluding dividends; label only."
    )

descriptions.update(
    {
        "evidence_document_id": "Hashed source that independently substantiates this assertion.",
        "scope": "Content scope: financial_fact, guidance, segment; never applied to every disclosure in a quarter.",
        "information_available_at": "UTC conservative information boundary; ET display. Minute evidence uses the end of its stated minute.",
        "timestamp_precision": "exact, minute, date_only, or explicitly inferred; no inferred time is called exact.",
        "timestamp_source": "Evidence URL supporting publication time or fallback.",
        "timestamp_confidence": "Qualitative high/medium/low confidence; precision remains separate.",
        "fallback_reason": "Why a conservative availability bound replaces unknown precision.",
        "timezone": "Source/display zone, America/New_York; storage is UTC.",
        "policy_version": "Version of the immutable evidence interpretation policy.",
        "action_type": "Corporate action type; split currently implemented.",
        "split_date": "First trading date on the new per-share basis.",
        "effective_date": "Legal split/distribution date, which may precede the trading date.",
        "ratio_numerator": "New shares in the split ratio.",
        "ratio_denominator": "Old shares in the split ratio.",
        "adjustment_factor": "New shares per old share; multiply shares and divide per-share values.",
        "announced_at": "Conservative announcement bound; date precision declared in metadata.",
        "market_price_id": "Original provider bar, including provider/retrieval/hash lineage.",
        "raw_origin": "provider_as_traded or research_reconstructed; never interchangeable observation claims.",
        "split_factor": "Subsequent split multiplier between the bar date and vendor anchor date.",
        "total_adjustment_factor": "Provider adjusted close divided by as-traded close; includes dividend adjustments when supplied.",
        "basis_date": "Date identifying the per-share denomination/adjustment anchor.",
        "left_fact_id": "IR fact retained verbatim during SEC/IR reconciliation.",
        "right_fact_id": "SEC fact retained verbatim during SEC/IR reconciliation.",
        "blocking": "Whether this unresolved issue blocks the stated acceptance/use case.",
        "canonical_rule": "Cutoff-aware priority policy; never an overwrite of source values.",
        "issue_id": "Original data-quality issue; reviews append without deleting history.",
        "classification": "Expected Missing, Source Limitation, Parser Defect, Timestamp Gap, Definition Difference, or Reconciliation Conflict.",
        "resolution": "Open, resolved with evidence, excluded context, or documented limitation.",
        "evidence": "Structured source IDs, observations and explanation supporting the review.",
        "share_class": "Mapped economic share class; current NVDA pipeline accepts unsegmented common shares only.",
        "share_count": "Absolute shares outstanding on the original reported basis, not weighted-average diluted shares.",
        "shares_as_of_date": "Economic instant described by the share count; distinct from its publication date.",
        "source_type": "sec_cover, sec_structured, or official_disclosure; used for same-date priority.",
        "taxonomy_concept": "Original share disclosure taxonomy and concept, when applicable.",
        "split_basis": "JSON with explicit original basis date, as_reported kind and shares unit.",
        "normalized_share_count": "Absolute share count on normalized_basis_date; current/valuation bases are resolved at query time.",
        "normalized_basis_date": "Original denomination date of stored normalized shares; never silently updated to today's basis.",
    }
)
for field in ("open", "high", "low", "close"):
    descriptions["raw_" + field] = (
        "As-traded OHLC basis; raw_origin explicitly distinguishes provider data from split reconstruction."
    )
    descriptions["split_adjusted_" + field] = (
        "Split-only comparable price at basis_date; no dividend adjustment in valuation."
    )
    descriptions["adjusted_" + field] = (
        "Total-return/vendor-adjusted field only when supplied; unavailable OHLC stays NULL."
    )

lines = [
    "# Data dictionary",
    "",
    "Generated from the SQLAlchemy field inventory. Dates are inclusive economic dates; all timestamps use explicit UTC storage and ET market interpretation. NULL means unavailable/reserved, never zero.",
    "",
    "## Storage and units",
    "",
    "Money: USD (IR millions expanded by 1,000,000); shares: actual shares (source scale expanded); EPS: USD/share; percentages: ratios; DSO/DIO/DPO: actual calendar days. The SQL types below are logical types: PostgreSQL uses native NUMERIC, while SQLite stores canonical decimal text and returns Python Decimal. Financial arithmetic uses Decimal, with declared scale and half-even storage rounding; raw SQLite arithmetic over decimal-text columns is not the calculation interface. Legacy approximations are preserved rather than silently rewritten.",
    "",
]
for metadata in (Base.metadata, LabelBase.metadata):
    for table in metadata.sorted_tables:
        lines += [
            f"## {table.name}",
            "",
            "| Field | SQL type | Nullable | Meaning |",
            "|---|---|---|---|",
        ]
        for col in table.columns:
            if col.name not in descriptions:
                raise ValueError(f"Missing field description: {table.name}.{col.name}")
            lines.append(
                f"| {col.name} | {col.type} | {'yes' if col.nullable else 'no'} | {descriptions[col.name]} |"
            )
        lines.append("")
lines += [
    "## Metric mapping and formulas",
    "",
    "`normalization/mapping.py` contains the ordered XBRL concept aliases. Source taxonomy, normalized name and formula version remain attached to every fact. IR aliases live only in the provider adapter.",
    "",
    "| Metric / feature | Definition |",
    "|---|---|",
    "| FCF | OCF minus positive purchases CapEx |",
    "| Debt | current plus noncurrent debt; NULL if either is absent |",
    "| Gross / operating / FCF margin | profit or FCF divided by revenue |",
    "| Revenue / EPS / FCF YoY, QoQ | current / previous - 1; NULL when previous <= 0 or missing |",
    "| AR / inventory YoY | same positive-base growth formula |",
    "| Margin YoY/QoQ change | current margin minus prior margin, ratio points |",
    "| CapEx / revenue; SBC / revenue | respective expense or cash-outflow amount divided by revenue |",
    "| DSO | average(beginning, ending AR) / quarterly revenue × actual period days |",
    "| Inventory days | average inventory / quarterly COGS × actual days |",
    "| DPO | average accounts payable / quarterly COGS × actual days (proxy for purchases) |",
    "| Cash conversion cycle | DSO + inventory days - DPO |",
    "| Missing beginning balance | ending balance fallback; approximation flag and method preserved |",
    "| Forecast revision | (new EPS - old EPS) / old EPS; NULL if old <= 0 |",
    "",
    "`cash_and_marketable_securities` preserves older combined balance-sheet presentation; it is never arbitrarily split. `company_reported_fcf` retains NVIDIA's additional equipment-payment deduction. `gross_margin_reported` is the rounded announced ratio; the feature gross margin uses underlying gross profit/revenue.",
    "",
    "Anomalies: revenue YoY >20% with FCF YoY <0; AR/inventory growth > revenue growth +20 percentage points; EPS YoY >20% with FCF YoY <0. These fixed diagnostic examples are versioned and are not buy/sell thresholds. EPS comparisons use formal corporate-action conversion when both source bases are verified; otherwise conservative NULL behavior remains.",
    "",
    "Segment observations preserve names and whether they are reporting segments or market platforms. Data Center/Gaming/etc. narrative values can be rounded to billions/millions as published; no implied extra precision. Exact Compute & Networking / Graphics reporting-segment extraction is not implemented.",
    "",
]
(Path(__file__).resolve().parents[1] / "docs/DATA_DICTIONARY.md").write_text("\n".join(lines))
