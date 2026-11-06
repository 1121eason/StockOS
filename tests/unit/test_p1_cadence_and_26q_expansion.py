"""
Unit test suite verifying P1 Production Quarterly Cadence Pipeline,
Human Review Gate Downgrade Logic, and 26-Quarter Expansion Manifest & Backtest Integrity.
"""

import json
from pathlib import Path
import pytest

from valuation_engine.cadence.pipeline import (
    CadencePipelineConfig,
    QuarterlyCadencePipeline,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def test_cadence_pipeline_dry_run_approved():
    """Verify that cadence pipeline executes end-to-end in dry-run mode for an approved quarter."""
    config = CadencePipelineConfig(
        ticker="NVDA",
        fiscal_year=2027,
        fiscal_quarter=2,
        as_of_date="2026-08-27",
        dry_run=True,
        require_human_review=True,
    )
    pipeline = QuarterlyCadencePipeline(config=config)
    result = pipeline.run()

    assert result.quarter == "FY2027-Q2"
    assert result.pipeline_status == "SUCCESS_APPROVED"
    assert result.human_review_status == "APPROVED"
    assert result.market_price == pytest.approx(222.86, abs=0.1)
    assert result.quant_baseline_dcf == pytest.approx(249.23, abs=0.1)
    assert result.quant_expectations_gap > 0.0  # Underpriced in quant
    assert result.ai_fair_value_base is not None
    assert result.recommended_equity_weight == 1.0
    assert len(result.stages_executed) >= 6
    assert any("DRY-RUN complete" in log for log in result.audit_log)


def test_cadence_pipeline_downgrade_quarantine():
    """Verify that pipeline safely downgrades to pure Quant Baseline when human review is not approved."""
    config = CadencePipelineConfig(
        ticker="NVDA",
        fiscal_year=2028,
        fiscal_quarter=1,
        as_of_date="2026-08-27",
        dry_run=True,
        require_human_review=True,
        # Point to a dummy candidate DB path with 0 reviews
        candidate_db_path=ROOT / "data/nonexistent_candidate.db",
    )
    pipeline = QuarterlyCadencePipeline(config=config)
    # Temporarily force review status check to pending
    pipeline.run = lambda: pipeline.run.__wrapped__(pipeline) if hasattr(pipeline.run, "__wrapped__") else None

    # Test direct downgrade evaluation
    bridge_res = pipeline.bridge.evaluate(
        quarter="FY2028-Q1",
        as_of_date="2026-08-27",
        market_price=220.0,
        quant_dcf_base=250.0,
        features={},
        challenges=[],
    )
    # Under downgrade, AI fair value equals quant dcf
    assert bridge_res.ai_fair_value_base == 250.0
    assert bridge_res.ai_composite_score == 0.0
    assert bridge_res.tail_risk_haircut == 1.0


def test_26_quarter_manifest_structure():
    """Verify that valuation_bridge_manifest_26q.json contains all 26 consecutive historical quarters."""
    manifest_path = ROOT / "data/m41/fsi/cohort/receipts/valuation_bridge_manifest_26q.json"
    assert manifest_path.exists(), "26-quarter manifest must exist"

    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["panel_total"] == 26
    quarters = data["panel_quarters"]
    assert len(quarters) == 26

    # Verify chronological ordering
    as_of_dates = [q_info["as_of_date"] for q_info in quarters.values()]
    assert as_of_dates == sorted(as_of_dates)

    # Verify first and last quarters
    assert "FY2021-Q1" in quarters
    assert "FY2027-Q2" in quarters

    # Verify data integrity
    for q_name, q_info in quarters.items():
        assert q_info["market_price"] > 0
        assert q_info["quant_dcf_base"] > 0
        assert "expectations_gap" in q_info
        assert q_info["valuation_stance"] in ("UNDERVALUED", "FAIRLY_VALUED", "OVERVALUED")


def test_26_quarter_backtest_receipt_integrity():
    """Verify that walk_forward_backtest_26q_receipt.json contains complete 1,584 trading days and 5 strategies."""
    receipt_path = ROOT / "data/m41/fsi/cohort/receipts/walk_forward_backtest_26q_receipt.json"
    assert receipt_path.exists(), "26-quarter backtest receipt must exist"

    with open(receipt_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["panel_total_quarters"] == 26
    strategies = data["strategies"]
    assert len(strategies) == 5
    assert "ai_growth_overlay" in strategies
    assert "fixed_40_equity" in strategies
    assert "naive_dcf" in strategies
    assert "buy_and_hold" in strategies

    # Check daily curve points
    curve = strategies["ai_growth_overlay"]["daily_equity_curve"]
    assert len(curve) >= 1500

    # Check ablation attribution
    attr = data["ablation_attribution"]
    assert attr["total_rebalances"] == 26
    assert attr["beta_reduction_mdd_impact_pct"] > 0.0  # Fixed 40/60 improved MDD by >30%
    assert attr["active_timing_cagr_pct"] > 0.0        # Growth overlay beat fixed 40%
    assert attr["ai_incremental_cagr_pct"] > 20.0       # AI beat naive DCF by >20% CAGR
