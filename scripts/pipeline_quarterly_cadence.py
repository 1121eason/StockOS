#!/usr/bin/env python3
"""
StockOS Production Quarterly Cadence Pipeline CLI.
Usage:
    python scripts/pipeline_quarterly_cadence.py --fiscal-year 2027 --fiscal-quarter 2 --dry-run
    python scripts/pipeline_quarterly_cadence.py --fiscal-year 2027 --fiscal-quarter 2 --apply
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from valuation_engine.cadence.pipeline import CadencePipelineConfig, QuarterlyCadencePipeline

DEFAULT_RECEIPT_DIR = ROOT / "data/m41/fsi/cohort/receipts"


def main():
    parser = argparse.ArgumentParser(description="StockOS Quarterly Cadence Pipeline CLI")
    parser.add_argument("--ticker", default="NVDA", help="Company ticker symbol")
    parser.add_argument("--fiscal-year", type=int, default=2027, help="Fiscal year (e.g. 2027)")
    parser.add_argument("--fiscal-quarter", type=int, default=2, help="Fiscal quarter (1-4)")
    parser.add_argument("--as-of-date", default="2026-08-27", help="As of date (YYYY-MM-DD)")
    parser.add_argument("--apply", action="store_true", help="Commit snapshot to database (default is dry-run)")
    parser.add_argument("--no-human-review", action="store_true", help="Skip human review requirement (downgrade to quant)")
    parser.add_argument("--output-receipt", default=None, help="Custom output receipt JSON path")

    args = parser.parse_args()
    is_dry_run = not args.apply

    config = CadencePipelineConfig(
        ticker=args.ticker,
        fiscal_year=args.fiscal_year,
        fiscal_quarter=args.fiscal_quarter,
        as_of_date=args.as_of_date,
        dry_run=is_dry_run,
        require_human_review=not args.no_human_review,
    )

    print("==========================================================================")
    print(f" StockOS Quarterly Cadence Pipeline — {args.ticker} FY{args.fiscal_year}-Q{args.fiscal_quarter}")
    print(f" Execution Mode: {'DRY-RUN (Safe Preflight)' if is_dry_run else 'APPLY (Commit Mode)'}")
    print("==========================================================================")

    pipeline = QuarterlyCadencePipeline(config=config)
    result = pipeline.run()

    print(f"\n[Status] Pipeline Status: {result.pipeline_status}")
    print(f"[Status] Human Review Gate: {result.human_review_status}")
    print(f"[Market] Current Price: ${result.market_price:.2f}")
    print(f"[Quant]  Quant Baseline DCF: ${result.quant_baseline_dcf:.2f} (Gap: {result.quant_expectations_gap:+.1%})")
    if result.market_implied_growth_rate is not None:
        print(f"[Quant]  Reverse DCF Implied Growth: {result.market_implied_growth_rate*100:.1f}%")
    if result.ai_fair_value_base is not None:
        print(f"[AI]     AI Fair Value Base: ${result.ai_fair_value_base:.2f} (Gap: {result.ai_expectations_gap:+.1%})")
    print(f"[Policy] Recommended Action: {result.recommended_action} (Equity: {result.recommended_equity_weight*100:.0f}%, Cash: {result.recommended_cash_weight*100:.0f}%)")

    print("\n--- Pipeline Execution Audit Log ---")
    for log in result.audit_log:
        print(f"  • {log}")

    # Output receipt
    receipt_dir = DEFAULT_RECEIPT_DIR
    receipt_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output_receipt) if args.output_receipt else receipt_dir / f"cadence_receipt_FY{args.fiscal_year}Q{args.fiscal_quarter}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

    print("==========================================================================")
    print(f"✓ Cadence execution receipt written to: {out_path}")
    print("==========================================================================")


if __name__ == "__main__":
    main()
