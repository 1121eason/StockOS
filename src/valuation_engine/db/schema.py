from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from valuation_engine.time import aware, now


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        return aware(value) if value is not None else None

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        from datetime import UTC

        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class ExactNumeric(TypeDecorator[Decimal]):
    """Exact decimal text on SQLite, native NUMERIC on PostgreSQL.

    Financial arithmetic occurs in Python Decimal; SQLite raw-SQL arithmetic is
    intentionally not an authoritative financial calculation interface.
    """

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int, scale: int):
        self.precision, self.scale = precision, scale
        super().__init__(precision, scale)

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(128))
        return dialect.type_descriptor(Numeric(self.precision, self.scale))

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        with localcontext() as context:
            context.prec = self.precision + self.scale + 4
            result = Decimal(str(value)).quantize(
                Decimal(1).scaleb(-self.scale), rounding=ROUND_HALF_EVEN
            )
            if not result.is_finite() or abs(result) >= Decimal(10) ** (
                self.precision - self.scale
            ):
                raise ValueError("Decimal exceeds declared precision")
        return format(result, "f") if dialect.name == "sqlite" else result

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        return Decimal(str(value)) if value is not None else None


NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class LabelBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Row:
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class AvailabilityEvidence(Row, Base):
    """Append-only evidence; applies only to content actually in the linked document."""

    __tablename__ = "availability_evidence"
    identity_key: Mapped[str] = mapped_column(unique=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"), index=True)
    evidence_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    scope: Mapped[str]  # financial_fact / guidance / segment / filing
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    information_available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    timestamp_precision: Mapped[str]
    timestamp_source: Mapped[str]
    timestamp_confidence: Mapped[str]
    fallback_reason: Mapped[str | None]
    timezone: Mapped[str] = mapped_column(default="America/New_York")
    policy_version: Mapped[str]


class CorporateAction(Row, Base):
    __tablename__ = "corporate_actions"
    identity_key: Mapped[str] = mapped_column(unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    action_type: Mapped[str]
    split_date = mapped_column(Date, nullable=False)  # first trading date on new basis
    effective_date = mapped_column(Date, nullable=False)  # legal distribution date
    ratio_numerator: Mapped[Decimal] = mapped_column(ExactNumeric(18, 8))
    ratio_denominator: Mapped[Decimal] = mapped_column(ExactNumeric(18, 8))
    adjustment_factor: Mapped[Decimal] = mapped_column(ExactNumeric(18, 8))  # shares multiplier
    announced_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class PriceBasis(Row, Base):
    __tablename__ = "price_bases"
    identity_key: Mapped[str] = mapped_column(unique=True)
    market_price_id: Mapped[int] = mapped_column(ForeignKey("market_prices.id"), index=True)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    raw_open: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    raw_high: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    raw_low: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    raw_close: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    raw_origin: Mapped[str]  # provider_as_traded / research_reconstructed
    split_adjusted_open: Mapped[Decimal] = mapped_column(ExactNumeric(24, 8))
    split_adjusted_high: Mapped[Decimal] = mapped_column(ExactNumeric(24, 8))
    split_adjusted_low: Mapped[Decimal] = mapped_column(ExactNumeric(24, 8))
    split_adjusted_close: Mapped[Decimal] = mapped_column(ExactNumeric(24, 8))
    adjusted_open: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    adjusted_high: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    adjusted_low: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    adjusted_close: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    split_factor: Mapped[Decimal] = mapped_column(ExactNumeric(18, 8))
    total_adjustment_factor: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 12))
    basis_date = mapped_column(Date, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ReconciliationResult(Row, Base):
    __tablename__ = "reconciliation_results"
    identity_key: Mapped[str] = mapped_column(unique=True)
    left_fact_id: Mapped[int] = mapped_column(ForeignKey("financial_facts.id"))
    right_fact_id: Mapped[int] = mapped_column(ForeignKey("financial_facts.id"))
    status: Mapped[str]
    blocking: Mapped[bool]
    canonical_rule: Mapped[str]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class QualityReview(Row, Base):
    __tablename__ = "quality_reviews"
    identity_key: Mapped[str] = mapped_column(unique=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("data_quality_issues.id"), index=True)
    classification: Mapped[str]
    blocking: Mapped[bool]
    resolution: Mapped[str]
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)


class Company(Row, Base):
    __tablename__ = "companies"
    ticker: Mapped[str] = mapped_column(String(16), unique=True)
    company_name: Mapped[str]
    cik: Mapped[str] = mapped_column(String(10), unique=True)
    exchange: Mapped[str]
    currency: Mapped[str] = mapped_column(String(3))
    gics_sector: Mapped[str | None]
    gics_industry: Mapped[str | None]
    gics_subindustry: Mapped[str | None]
    valuation_archetype: Mapped[str]
    archetype_confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric(8, 6))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now, onupdate=now)


class ShareCountObservation(Row, Base):
    __tablename__ = "share_count_observations"
    __table_args__ = (CheckConstraint("available_at >= published_at", name="share_availability"),)
    identity_key: Mapped[str] = mapped_column(String(64), unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    share_class: Mapped[str]
    share_count: Mapped[Decimal] = mapped_column(ExactNumeric(30, 8))
    shares_as_of_date = mapped_column(Date, nullable=False, index=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    source_type: Mapped[str]
    taxonomy_concept: Mapped[str | None]
    split_basis: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized_share_count: Mapped[Decimal] = mapped_column(ExactNumeric(30, 8))
    normalized_basis_date = mapped_column(Date, nullable=False)
    confidence: Mapped[str]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class Filing(Row, Base):
    __tablename__ = "filings"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    accession_number: Mapped[str] = mapped_column(String(32), unique=True)
    form_type: Mapped[str]
    fiscal_year: Mapped[int | None]
    fiscal_quarter: Mapped[int | None]
    period_end = mapped_column(Date)
    filing_date = mapped_column(Date, nullable=False)
    accepted_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_url: Mapped[str] = mapped_column(Text)
    is_amendment: Mapped[bool] = mapped_column(default=False)


class SourceDocument(Row, Base):
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("source_url", "content_hash"),)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"))
    document_type: Mapped[str]
    source_url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_hash: Mapped[str] = mapped_column(String(64))
    source_provider: Mapped[str]
    raw_path: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FinancialFact(Row, Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        CheckConstraint("fiscal_quarter BETWEEN 1 AND 4", name="quarter"),
        CheckConstraint("available_at >= reported_at", name="availability"),
    )
    identity_key: Mapped[str] = mapped_column(String(64), unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"))
    metric_name: Mapped[str] = mapped_column(index=True)
    taxonomy_name: Mapped[str]
    value: Mapped[Decimal] = mapped_column(ExactNumeric(30, 8))
    unit: Mapped[str]
    period_start = mapped_column(Date)
    period_end = mapped_column(Date, nullable=False, index=True)
    fiscal_year: Mapped[int]
    fiscal_quarter: Mapped[int]
    duration_kind: Mapped[str]  # instant / quarter / ytd / annual
    frame: Mapped[str | None]
    reported_at: Mapped[datetime] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    earnings_release_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime())
    tradable_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    source_priority: Mapped[int]
    is_restated: Mapped[bool] = mapped_column(default=False)
    formula_version: Mapped[str]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SegmentFact(Row, Base):
    __tablename__ = "segment_facts"
    identity_key: Mapped[str] = mapped_column(unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    fiscal_year: Mapped[int]
    fiscal_quarter: Mapped[int]
    segment_name: Mapped[str]
    classification_kind: Mapped[str]  # reporting_segment or market_platform
    metric_name: Mapped[str]
    value: Mapped[Decimal] = mapped_column(ExactNumeric(30, 8))
    unit: Mapped[str]
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))


class GuidanceItem(Row, Base):
    __tablename__ = "guidance_items"
    identity_key: Mapped[str] = mapped_column(unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    fiscal_year: Mapped[int]
    fiscal_quarter: Mapped[int]
    guidance_for_period: Mapped[str]
    metric_name: Mapped[str]
    low_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    mid_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    high_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    unit: Mapped[str]
    guidance_type: Mapped[str]
    basis: Mapped[str] = mapped_column(default="GAAP")
    raw_text: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric(8, 6))


class MarketPrice(Row, Base):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("company_id", "timestamp", "price_type", "provider", "content_hash"),
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    ticker: Mapped[str]
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)  # bar open
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())  # bar close
    price_type: Mapped[str]  # daily_unadjusted; never pretend adjusted is PIT
    open: Mapped[Decimal] = mapped_column(ExactNumeric(24, 8))
    high: Mapped[Decimal] = mapped_column(ExactNumeric(24, 8))
    low: Mapped[Decimal] = mapped_column(ExactNumeric(24, 8))
    close: Mapped[Decimal] = mapped_column(ExactNumeric(24, 8))
    adjusted_close: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    volume: Mapped[int]
    currency: Mapped[str]
    provider: Mapped[str]
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime())
    content_hash: Mapped[str]


class QuarterlySnapshot(Row, Base):
    __tablename__ = "quarterly_snapshots"
    identity_key: Mapped[str] = mapped_column(unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    fiscal_year: Mapped[int]
    fiscal_quarter: Mapped[int]
    as_of_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    tradable_at: Mapped[datetime] = mapped_column(UTCDateTime())
    model_version: Mapped[str]
    selection_policy: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class AssumptionSet(Row, Base):
    __tablename__ = "assumption_sets"
    content_hash: Mapped[str] = mapped_column(unique=True)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON)


class ForecastSnapshot(Row, Base):
    __tablename__ = "forecast_snapshots"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    forecast_as_of: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    model_version: Mapped[str]
    forecast_horizon: Mapped[str]
    fiscal_period: Mapped[str]
    revenue: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    gross_margin: Mapped[Decimal | None] = mapped_column(ExactNumeric(16, 8))
    operating_margin: Mapped[Decimal | None] = mapped_column(ExactNumeric(16, 8))
    eps: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    fcf: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    assumption_set_id: Mapped[int] = mapped_column(ForeignKey("assumption_sets.id"))
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("quarterly_snapshots.id"))
    generated_kind: Mapped[str]  # live / historical_replay (not a real historical estimate)


class ForecastRun(Row, Base):
    __tablename__ = "forecast_runs"
    identity_key: Mapped[str] = mapped_column(unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    forecast_as_of: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    information_cutoff: Mapped[datetime] = mapped_column(UTCDateTime())
    tradable_at: Mapped[datetime] = mapped_column(UTCDateTime())
    forecast_type: Mapped[str]
    forecast_basis: Mapped[str]
    generated_kind: Mapped[str]
    model_name: Mapped[str]
    model_version: Mapped[str]
    assumption_set_id: Mapped[int] = mapped_column(ForeignKey("assumption_sets.id"))
    input_snapshot_id: Mapped[int] = mapped_column(ForeignKey("quarterly_snapshots.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ForecastPeriod(Row, Base):
    __tablename__ = "forecast_periods"
    __table_args__ = (
        UniqueConstraint("forecast_run_id", "period_type", "fiscal_year", "fiscal_quarter"),
    )
    forecast_run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id"), index=True)
    fiscal_year: Mapped[int]
    fiscal_quarter: Mapped[int]  # 0 for multi-quarter aggregates
    period_type: Mapped[str]  # quarter / NTM / FY1 / FY2
    revenue: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    gross_margin: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    gross_profit: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    operating_expenses: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    operating_income: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    non_operating_income: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    pre_tax_income: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    tax_rate: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    net_income: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    diluted_weighted_shares: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    eps: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    operating_cash_flow: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    capex: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    free_cash_flow: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ForecastAssumption(Row, Base):
    __tablename__ = "forecast_assumptions"
    __table_args__ = (UniqueConstraint("assumption_set_id", "parameter_name"),)
    assumption_set_id: Mapped[int] = mapped_column(ForeignKey("assumption_sets.id"))
    parameter_name: Mapped[str]
    parameter_value: Mapped[Any] = mapped_column(JSON)
    unit: Mapped[str]
    source_type: Mapped[str]
    source_reference: Mapped[str]
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime())
    model_version: Mapped[str]


class ForecastRevision(Row, Base):
    __tablename__ = "forecast_revisions"
    identity_key: Mapped[str] = mapped_column(unique=True)
    previous_run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id"))
    forecast_run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ResearchValuation(Row, Base):
    __tablename__ = "research_valuations"
    identity_key: Mapped[str] = mapped_column(unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    forecast_run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id"))
    source_valuation_id: Mapped[int] = mapped_column(ForeignKey("valuation_snapshots.id"))
    as_of_timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    valuation_model_version: Mapped[str]
    ntm_pe: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    fy1_pe: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    fy2_pe: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    forward_fcf_yield: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    forward_ev_ebit: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    historical_ntm_pe_percentile: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    historical_ntm_pe_zscore: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    dcf_base: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    dcf_low: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    dcf_high: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    reverse_dcf_implied_fcf_cagr: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    internal_fcf_cagr: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    expectations_gap: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class DCFScenario(Row, Base):
    __tablename__ = "dcf_scenarios"
    __table_args__ = (UniqueConstraint("valuation_id", "wacc", "terminal_growth"),)
    valuation_id: Mapped[int] = mapped_column(ForeignKey("research_valuations.id"))
    wacc: Mapped[Decimal] = mapped_column(ExactNumeric(16, 8))
    terminal_growth: Mapped[Decimal] = mapped_column(ExactNumeric(16, 8))
    enterprise_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    equity_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    per_share: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ForecastOutcome(Row, LabelBase):
    __tablename__ = "forecast_outcomes"
    identity_key: Mapped[str] = mapped_column(unique=True)
    forecast_run_key: Mapped[str]  # Content reference; no cross-database FK.
    evaluation_as_of: Mapped[datetime] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    model_version: Mapped[str]
    horizon: Mapped[str]
    fiscal_period: Mapped[str]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class QuantFeature(Row, Base):
    __tablename__ = "quant_features"
    __table_args__ = (UniqueConstraint("source_snapshot_id", "feature_name", "feature_version"),)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    as_of_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    fiscal_year: Mapped[int]
    fiscal_quarter: Mapped[int]
    feature_name: Mapped[str]
    feature_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    feature_version: Mapped[str]
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("quarterly_snapshots.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ValuationSnapshot(Row, Base):
    __tablename__ = "valuation_snapshots"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    as_of_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    market_price: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    market_cap: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    enterprise_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    trailing_pe: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    fy1_pe: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    fy2_pe: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    ev_ebit: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    ev_ebitda: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    fcf_yield: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    dcf_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    reverse_dcf_growth: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    bear_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    base_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    bull_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    probability_weighted_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(30, 8))
    model_version: Mapped[str]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class RegimeSnapshot(Row, Base):
    __tablename__ = "regime_snapshots"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    as_of_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    regime: Mapped[str | None]
    hypergrowth_probability: Mapped[Decimal | None] = mapped_column(ExactNumeric(8, 6))
    growth_probability: Mapped[Decimal | None] = mapped_column(ExactNumeric(8, 6))
    mature_growth_probability: Mapped[Decimal | None] = mapped_column(ExactNumeric(8, 6))
    cyclical_downturn_probability: Mapped[Decimal | None] = mapped_column(ExactNumeric(8, 6))
    structural_deterioration_probability: Mapped[Decimal | None] = mapped_column(ExactNumeric(8, 6))
    model_version: Mapped[str]
    identity_key: Mapped[str | None] = mapped_column(unique=True)
    primary_regime: Mapped[str | None]
    policy_version: Mapped[str | None]
    assumption_set_id: Mapped[int | None] = mapped_column(ForeignKey("assumption_sets.id"))
    input_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("quarterly_snapshots.id"))
    forecast_run_id: Mapped[int | None] = mapped_column(ForeignKey("forecast_runs.id"))
    previous_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("regime_snapshots.id"))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    growth_score: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    revision_score: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    profitability_score: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    cash_quality_score: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    deterioration_score: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    cycle_score: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    data_quality_score: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))

    confirmed_regime: Mapped[str | None]
    candidate_regime: Mapped[str | None]
    transition_status: Mapped[str | None]
    evidence_confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    data_quality_confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    history_sufficiency: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    composite_confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    candidate_probability: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    probability_gap_to_second_candidate: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))


class RegimeTransition(Row, Base):
    __tablename__ = "regime_transitions"
    identity_key: Mapped[str] = mapped_column(unique=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    from_regime: Mapped[str]
    to_regime: Mapped[str]
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime())
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    previous_snapshot_id: Mapped[int] = mapped_column(ForeignKey("regime_snapshots.id"))
    new_snapshot_id: Mapped[int] = mapped_column(ForeignKey("regime_snapshots.id"), unique=True)
    transition_strength: Mapped[Decimal] = mapped_column(ExactNumeric(20, 8))
    reason_codes: Mapped[list] = mapped_column(JSON)
    policy_version: Mapped[str]


class AIFeature(Row, Base):
    __tablename__ = "ai_features"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    as_of_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    feature_name: Mapped[str]
    feature_value: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric(8, 6))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    model_name: Mapped[str]
    prompt_version: Mapped[str]


class IngestionRun(Row, Base):
    __tablename__ = "ingestion_runs"
    provider: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str]
    records_created: Mapped[int] = mapped_column(default=0)
    records_updated: Mapped[int] = mapped_column(default=0)
    records_skipped: Mapped[int] = mapped_column(default=0)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    errors: Mapped[list[Any]] = mapped_column(JSON, default=list)
    code_version: Mapped[str]


class DataQualityIssue(Row, Base):
    __tablename__ = "data_quality_issues"
    identity_key: Mapped[str] = mapped_column(unique=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    issue_type: Mapped[str]
    severity: Mapped[str]
    metric_name: Mapped[str | None]
    fiscal_period: Mapped[str | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


class FutureOutcome(Row, LabelBase):
    """Separate database, no cross-database FK, inaccessible to feature connection."""

    __tablename__ = "future_outcomes"
    __table_args__ = (UniqueConstraint("company_id", "anchor_timestamp", "label_as_of"),)
    company_id: Mapped[int]
    anchor_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    label_as_of: Mapped[datetime] = mapped_column(UTCDateTime())
    price_3m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    price_6m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    price_12m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    price_24m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    return_3m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    return_6m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    return_12m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    return_24m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    max_drawdown_12m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    max_upside_12m: Mapped[Decimal | None] = mapped_column(ExactNumeric(24, 8))
    alignment_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class AIAnalysisRun(Row, Base):
    __tablename__ = "ai_analysis_runs"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    quarter: Mapped[str]
    as_of_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    information_cutoff: Mapped[datetime] = mapped_column(UTCDateTime())
    source_document_ids: Mapped[list] = mapped_column(JSON)
    model_provider: Mapped[str]
    model_name: Mapped[str]
    model_version: Mapped[str]
    prompt_version: Mapped[str]
    schema_version: Mapped[str]
    policy_version: Mapped[str]
    request_hash: Mapped[str] = mapped_column(index=True)
    context_json: Mapped[dict] = mapped_column(JSON)
    settings_json: Mapped[dict] = mapped_column(JSON)


class AIAnalysisEvent(Row, Base):
    __tablename__ = "ai_analysis_events"
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    status: Mapped[str]
    details: Mapped[dict] = mapped_column(JSON)


class AIProviderCall(Row, Base):
    __tablename__ = "ai_provider_calls"
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    stage: Mapped[str]
    attempt: Mapped[int]
    exact_prompt: Mapped[dict] = mapped_column(JSON)
    request_hash: Mapped[str]
    response_hash: Mapped[str | None]
    raw_output: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str]


class AIEvidence(Row, Base):
    __tablename__ = "ai_evidence"
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    evidence_key: Mapped[str]
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    source_hash: Mapped[str]
    section: Mapped[str]
    block_id: Mapped[str]
    span: Mapped[str] = mapped_column(Text)
    span_hash: Mapped[str]
    speaker: Mapped[str | None]
    topic: Mapped[str]
    implication: Mapped[str]
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    metadata_json: Mapped[dict] = mapped_column(JSON)


class AIAnalystFeature(Row, Base):
    __tablename__ = "ai_analyst_features"
    __table_args__ = (UniqueConstraint("analysis_run_id", "feature_name"),)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    feature_name: Mapped[str]
    feature_value: Mapped[Decimal] = mapped_column(ExactNumeric(20, 8))
    confidence: Mapped[Decimal] = mapped_column(ExactNumeric(20, 8))
    direction: Mapped[str]
    time_horizon: Mapped[str]
    evidence_count: Mapped[int]
    source_document_ids: Mapped[list] = mapped_column(JSON)
    prompt_version: Mapped[str]
    model_version: Mapped[str]
    rationale: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON)


class AIFeatureEvidence(Row, Base):
    __tablename__ = "ai_feature_evidence"
    feature_id: Mapped[int] = mapped_column(ForeignKey("ai_analyst_features.id"))
    evidence_id: Mapped[int] = mapped_column(ForeignKey("ai_evidence.id"))
    role: Mapped[str]


class AIAnalystSnapshot(Row, Base):
    __tablename__ = "ai_analyst_snapshots"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    as_of_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"), unique=True)
    demand_momentum: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    pricing_power: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    supply_constraint: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    product_cycle_strength: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    competition_outlook: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    customer_financing_quality: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    working_capital_quality: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    regulatory_outlook: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    management_confidence: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    guidance_visibility: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    structural_outlook: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    overall_qualitative_confidence: Mapped[Decimal] = mapped_column(ExactNumeric(20, 8))
    prompt_version: Mapped[str]
    model_version: Mapped[str]
    metadata_json: Mapped[dict] = mapped_column(JSON)


class AIChallenge(Row, Base):
    __tablename__ = "ai_challenges"
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    kind: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    direction: Mapped[str]
    target_variable: Mapped[str]
    time_horizon: Mapped[str]
    evidence_ids: Mapped[list] = mapped_column(JSON)
    confidence: Mapped[Decimal] = mapped_column(ExactNumeric(20, 8))
    metadata_json: Mapped[dict] = mapped_column(JSON)


class ModelAdjustmentProposal(Row, Base):
    __tablename__ = "model_adjustment_proposals"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    target_model: Mapped[str]
    target_variable: Mapped[str]
    direction: Mapped[str]
    suggested_range_low: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    suggested_range_high: Mapped[Decimal | None] = mapped_column(ExactNumeric(20, 8))
    confidence: Mapped[Decimal] = mapped_column(ExactNumeric(20, 8))
    rationale: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON)
    status: Mapped[str]


class AIUnsupportedClaim(Row, Base):
    __tablename__ = "ai_unsupported_claims"
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    stage: Mapped[str]
    reason: Mapped[str]
    raw_claim: Mapped[dict] = mapped_column(JSON)


class AIHumanReview(Row, Base):
    __tablename__ = "ai_human_reviews"
    analysis_run_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    category: Mapped[str]
    verdict: Mapped[str]
    reviewer: Mapped[str]
    notes: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON)
