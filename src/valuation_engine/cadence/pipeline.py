"""
StockOS read-only quarterly cadence pipeline.

Missing or invalid valuation inputs fail before bridge/fusion; zero or negative DCF
values remain valid. Snapshot persistence is not implemented, so only dry runs work.
Revisions require an explicit fiscal target and exact formal-run lineage. Legacy
candidate AI rows remain quarantined until their admission/approval contract exists.
"""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from valuation_engine.cadence.formal_context import load_formal_context
from valuation_engine.cadence.revision_context import load_revision_context
from valuation_engine.decision.signal_fusion import SignalFusionEngine
from valuation_engine.valuation.bridge import ValuationBridgeV2


def _finite_number(value: Any, name: str) -> float:
    """Read a numeric input without turning absent or malformed data into a baseline."""
    message = f"{name} must be a finite number"
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(message)
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(message) from exc
    if not math.isfinite(number):
        raise ValueError(message)
    return number


@dataclass
class CadencePipelineConfig:
    ticker: str = "NVDA"
    fiscal_year: int = 2027
    fiscal_quarter: int = 2
    as_of_date: str = "2026-08-27"
    dry_run: bool = True
    require_human_review: bool = True
    qve_db_path: Path | None = None
    candidate_db_path: Path | None = None
    checkpoint_timestamp: str | datetime | None = None
    revision_target: str | None = None


@dataclass
class CadencePipelineResult:
    quarter: str
    as_of_date: str
    pipeline_status: str  # "SUCCESS_DOWNGRADED_QUANT_ONLY", "INCOMPLETE_REVISION_CONTEXT"
    market_price: float
    quant_baseline_dcf: float
    quant_expectations_gap: float
    market_implied_growth_rate: float | None
    ai_fair_value_base: float | None
    ai_expectations_gap: float | None
    recommended_action: str | None
    recommended_equity_weight: float | None
    recommended_cash_weight: float | None
    human_review_status: str  # "APPROVED", "PENDING", "REJECTED"
    stages_executed: list[str]
    audit_log: list[str]
    receipt_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QuarterlyCadencePipeline:
    """
    Reads a stored quarterly formal cohort and emits a conditional quant-only decision.
    Missing revision context withholds the decision; unbound AI remains quarantined.
    """

    def __init__(self, config: CadencePipelineConfig | None = None):
        self.config = config or CadencePipelineConfig()
        root = Path(__file__).resolve().parent.parent.parent.parent
        self.qve_db_path = self.config.qve_db_path or (root / "data/qve.db")
        self.candidate_db_path = self.config.candidate_db_path or (
            root / "data/m41/fsi/cohort/candidate.db"
        )
        self.bridge = ValuationBridgeV2()
        self.fusion = SignalFusionEngine()

    def run(self) -> CadencePipelineResult:
        if not self.config.dry_run:
            raise NotImplementedError(
                "dry_run=False is unsupported: snapshot persistence is not implemented"
            )

        audit_log: list[str] = []
        stages_executed: list[str] = []
        quarter_str = f"FY{self.config.fiscal_year}-Q{self.config.fiscal_quarter}"
        as_of_dt = self.config.as_of_date

        audit_log.append(
            f"Starting Quarterly Cadence Pipeline for {self.config.ticker} {quarter_str} (As of {as_of_dt})"
        )
        audit_log.append("Mode: DRY-RUN (No database mutations will be committed).")

        # -------------------------------------------------------------
        # Stage 1: Verify Ingestion & Filing Existence
        # -------------------------------------------------------------
        stages_executed.append("1_INGESTION_VERIFICATION")
        if not self.qve_db_path.exists():
            raise FileNotFoundError(f"Formal database not found at {self.qve_db_path}")
        audit_log.append("Stage 1: Formal database exists; no new filing ingestion was performed.")

        # -------------------------------------------------------------
        # Stage 2 & 3: Normalization & Quant Features Extraction
        # -------------------------------------------------------------
        stages_executed.append("2_NORMALIZATION_AND_FEATURES")
        # In a live runtime, queries PointInTimeRepository
        audit_log.append(
            "Stage 2: Reading stored formal inputs; normalization and YTD differencing were not rerun."
        )

        # -------------------------------------------------------------
        # Stage 4 & 5: Baseline Forecast & Quant Valuation
        # -------------------------------------------------------------
        stages_executed.append("3_QUANT_VALUATION_BASELINE")
        implied_growth = None

        formal = load_formal_context(
            self.qve_db_path,
            self.config.ticker,
            quarter_str,
            as_of_dt,
            self.config.checkpoint_timestamp,
        )
        quant_dcf = _finite_number(formal.dcf_base, "dcf_base")
        try:
            meta = json.loads(formal.metadata_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata_json must be a JSON object") from exc
        if not isinstance(meta, dict):
            raise ValueError("metadata_json must be a JSON object")
        market_price = _finite_number(meta.get("price"), "price")
        if market_price <= 0.0:
            raise ValueError("price must be greater than zero")

        rdcf = meta.get("reverse_dcf")
        if rdcf is not None:
            if not isinstance(rdcf, dict):
                raise ValueError("reverse_dcf must be a JSON object or null")
            if rdcf.get("status") != "unavailable" and rdcf.get("implied_growth") is not None:
                implied_growth = _finite_number(
                    rdcf["implied_growth"], "reverse_dcf.implied_growth"
                )

        revision = load_revision_context(self.qve_db_path, formal, self.config.revision_target)
        audit_log.append(
            f"Forecast revision: {revision.receipt['status']}; target={self.config.revision_target}; "
            f"reason={revision.receipt['reason']}"
        )

        quant_gap = (quant_dcf - market_price) / market_price if market_price > 0 else 0.0
        audit_log.append(
            f"Stage 3 PASS: Quant Baseline DCF = ${quant_dcf:.2f}, Market Price = ${market_price:.2f}, Quant Gap = {quant_gap:+.1%}"
        )
        if implied_growth is not None:
            audit_log.append(f"Reverse DCF Implied Growth: {implied_growth * 100:.1f}%")

        # -------------------------------------------------------------
        # Stage 6: AI Evidence & Challenge Extraction
        # -------------------------------------------------------------
        stages_executed.append("4_AI_EVIDENCE_EXTRACTION")
        # The legacy cohort schema has no verified formal-run/admission binding.
        # A review-count or require_human_review=False cannot supply that provenance.
        candidate_present = self.candidate_db_path.exists()
        audit_log.append(
            "Stage 4: Legacy AI candidate inputs quarantined; exact-run admission and approval "
            "contracts are unavailable."
        )

        stages_executed.append("5_HUMAN_REVIEW_GATE")
        human_review_status = "PENDING"
        review_receipt = {
            "status": human_review_status,
            "reason": "candidate_lineage_and_approval_contract_missing",
            "candidate_database_present": candidate_present,
            "require_human_review": self.config.require_human_review,
            "ai_inputs_admitted": False,
        }
        audit_log.append(
            "Human Review Gate: PENDING. Global review counts do not approve this candidate."
        )

        stages_executed.append("6_VALUATION_BRIDGE_AND_DECISION")
        bridge_res = self.bridge.evaluate(
            quarter=quarter_str,
            as_of_date=as_of_dt,
            market_price=market_price,
            quant_dcf_base=quant_dcf,
            features={},
            challenges=[],
            market_implied_growth_rate=implied_growth,
            guidance_revenue_revision=0.0,  # No AI growth channel to dampen.
        )
        fused = None
        if revision.signal is None:
            pipeline_status = "INCOMPLETE_REVISION_CONTEXT"
            audit_log.append(
                "Decision withheld: a complete, explicitly selected same-target forecast revision "
                "is unavailable. Missing revisions are not zero-change signals."
            )
        else:
            pipeline_status = "SUCCESS_DOWNGRADED_QUANT_ONLY"
            fused = self.fusion.fuse_formal(bridge_res, formal.regime, revision.signal)
            audit_log.append(
                f"Quant-only decision: Action = {fused.action}, Equity = {fused.equity_weight * 100:.0f}%, "
                f"Cash = {fused.cash_weight * 100:.0f}%"
            )

        # -------------------------------------------------------------
        # Stage 9: Snapshot Commit or Quarantine
        # -------------------------------------------------------------
        stages_executed.append("7_COMMIT_OR_QUARANTINE")
        audit_log.append(
            "Stage 7: DRY-RUN complete. Execution receipt generated without database mutation."
        )

        receipt_data = {
            "quarter": quarter_str,
            "as_of_date": as_of_dt,
            "pipeline_status": pipeline_status,
            "human_review_status": human_review_status,
            "formal_context": {
                "valuation_id": formal.valuation_id,
                "company_id": formal.regime["company_id"],
                "forecast_run_id": formal.regime["forecast_run_id"],
                "regime_snapshot_id": formal.regime["snapshot_id"],
                "checkpoint_timestamp": formal.regime["checkpoint_timestamp"],
            },
            "regime_context": formal.regime,
            "forecast_revision": revision.receipt,
            "human_review": review_receipt,
            "valuation": bridge_res.to_dict(),
            "decision": fused.to_dict() if fused is not None else None,
            "audit_log": audit_log,
        }

        return CadencePipelineResult(
            quarter=quarter_str,
            as_of_date=as_of_dt,
            pipeline_status=pipeline_status,
            market_price=round(market_price, 2),
            quant_baseline_dcf=round(quant_dcf, 2),
            quant_expectations_gap=round(quant_gap, 4),
            market_implied_growth_rate=round(implied_growth, 4)
            if implied_growth is not None
            else None,
            ai_fair_value_base=None,
            ai_expectations_gap=None,
            recommended_action=fused.action if fused is not None else None,
            recommended_equity_weight=fused.equity_weight if fused is not None else None,
            recommended_cash_weight=fused.cash_weight if fused is not None else None,
            human_review_status=human_review_status,
            stages_executed=stages_executed,
            audit_log=audit_log,
            receipt_data=receipt_data,
        )
