"""Bounded offline NVDA diagnostic. Never migrates or writes a research database.

Only canonical policy/formula implementations are imported. Model/provider APIs,
AI tables, outcome/label DBs, PostgreSQL and Docker are not used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def csv_write(path, rows):
    rows = list(rows)
    if not rows:
        return
    with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def dt(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def ro(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def document_ids(value, result):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("source_document_id", "evidence_document_id") and isinstance(item, int):
                result.add(item)
            document_ids(item, result)
    elif isinstance(value, list):
        for item in value:
            document_ids(item, result)


def temporal_audit(run, periods, valuation):
    cutoff = run.information_cutoff
    records = []
    def check(name, value, strict=False):
        passed = dt(value) < cutoff if strict else dt(value) <= cutoff
        records.append(dict(check=name, timestamp=str(value), cutoff=str(cutoff), passed=passed))
    meta = run.metadata_json
    for name, obs in meta["provenance"]["observations"].items():
        check("financial:" + name, obs["available_at"])
    for name, guidance in meta["raw_guidance"].items():
        check("guidance:" + name, guidance["available_at"])
    for name, bias in meta["guidance_bias"].items():
        for sample in bias["samples"]:
            check("guidance_actual:" + name, sample["actual_available_at"])
            check("guidance_origin:" + name, sample["guidance"]["available_at"])
    for period in periods:
        for name, interval in period["metadata_json"].get("intervals", {}).items():
            for sample in interval.get("samples", []):
                check("interval_actual:" + name, sample["actual_available_at"])
                check("interval_origin:" + name, sample["origin_as_of"], strict=True)
    base = valuation.metadata_json["source_valuation"]
    for name, obs in base["inputs"].items():
        check("valuation:" + name, obs["available_at"])
    check("shares", base["shares"]["available_at"])
    check("price", base["price"]["available_at"])
    for i, earlier in enumerate(valuation.metadata_json["context_prior_timestamps"]):
        check(f"prior_context:{i}", earlier, strict=True)
    assert run.forecast_as_of == run.information_cutoff == run.tradable_at
    assert all(r["passed"] for r in records), "Future-dated input detected"
    return records


def simulate(bars, signals, policy, cfg, net):
    initial = cfg["initial_capital_usd"]
    daily_rf = (1 + cfg["annual_cash_rate"]) ** (1 / 252) - 1
    cost = cfg["commission_bps"] / 10000 if net else 0
    slip = cfg["slippage_bps"] / 10000 if net else 0
    friction = cost + slip
    cash, quantity, previous_nav, peak = initial, 0.0, initial, initial
    curve, ledger, returns, exposures, turnovers = [], [], [], [], []
    fees = slippage_total = 0.0
    name = type(policy).__name__
    for index, bar in enumerate(bars):
        date = bar["date"]
        signal = signals.get(date)
        # Passive and fixed controls enter at the same first permitted execution.
        rebalance = signal is not None and (name != "BuyAndHoldPolicy" or index == 0)
        if rebalance:
            decision = policy.decide(signal)
            w = decision.equity_weight
            open_price = bar["open"]
            equity = quantity * open_price
            before = cash + equity
            difference = w * before - equity
            side = 1 if difference > 0 else -1
            # Solve E + delta = w * (NAV - friction*abs(delta)).
            delta = difference / (1 + w * friction * side)
            if abs(delta) < 1e-8:
                delta = 0.0
            delta_shares = delta / open_price
            execution_price = open_price * (1 + side * slip)
            commission = abs(delta) * cost
            slip_paid = abs(delta) * slip
            cash_before, qty_before = cash, quantity
            quantity += delta_shares
            if abs(quantity) < 1e-8:
                quantity = 0.0
            cash -= delta_shares * execution_price + commission
            if abs(cash) < 1e-8:
                cash = 0.0
            post_nav = cash + quantity * open_price
            assert cash >= -1e-7 and quantity >= -1e-8
            assert abs(post_nav - before + commission + slip_paid) < 1e-7
            assert abs(quantity * open_price / post_nav - w) < 1e-9
            turnover = abs(delta) / before
            turnovers.append(turnover)
            fees += commission
            slippage_total += slip_paid
            ledger.append(dict(
                strategy=name, variant="net" if net else "gross", quarter=signal["quarter"],
                signal_timestamp=signal["signal_timestamp"], execution_timestamp=bar["timestamp"],
                model_checkpoint_timestamp=signal["model_checkpoint_timestamp"],
                price_data_available_at=signal["price_data_available_at"],
                forecast_run_id=signal["forecast_run_id"], valuation_id=signal["valuation_id"],
                signal_market_price_as_traded=signal["market_price"], dcf_as_traded=signal["quant_dcf_base"],
                policy_action=decision.action, target_weight=w,
                trade_side="BUY" if delta > 0 else "SELL" if delta < 0 else "NO_TRADE",
                mid_split_adjusted_open=open_price, execution_split_adjusted_price=execution_price,
                normalized_shares_before=qty_before, normalized_share_change=delta_shares,
                normalized_shares_after=quantity, mid_notional_usd=delta,
                commission_usd=commission, slippage_usd=slip_paid, turnover=turnover,
                cash_before_usd=cash_before, cash_after_usd=cash,
                nav_before_usd=before, nav_after_usd=post_nav,
                economic_basis="shares normalized to 2026-09-12 split basis; no dividends"))
        cash *= 1 + daily_rf
        nav = cash + quantity * bar["close"]
        ret = nav / previous_nav - 1
        previous_nav = nav
        peak = max(peak, nav)
        exposure = quantity * bar["close"] / nav
        returns.append(ret)
        exposures.append(exposure)
        curve.append(dict(strategy=name, variant="net" if net else "gross", date=date,
                          nav_usd=nav, equity_usd=quantity * bar["close"], cash_usd=cash,
                          daily_return=ret, equity_exposure=exposure, drawdown=nav / peak - 1))
    start = dt(bars[0]["timestamp"])
    # All chosen days have a regular 6.5h session. Prices are terminal marks, no forced sale.
    end = dt(bars[-1]["timestamp"]).replace(hour=20, minute=0)
    years = (end - start).total_seconds() / (365.25 * 86400)
    volatility = statistics.stdev(returns) * math.sqrt(252)
    sharpe = statistics.mean([r - daily_rf for r in returns]) / statistics.stdev(returns) * math.sqrt(252)
    metrics = dict(strategy=name, variant="net" if net else "gross", start=bars[0]["date"],
                   end=bars[-1]["date"], sessions=len(bars), final_nav_usd=previous_nav,
                   cumulative_return=previous_nav / initial - 1,
                   cagr=(previous_nav / initial) ** (1 / years) - 1,
                   max_drawdown=min(r["drawdown"] for r in curve), annual_volatility=volatility,
                   sharpe=sharpe, one_way_turnover=sum(turnovers),
                   trade_count=sum(r["trade_side"] != "NO_TRADE" for r in ledger),
                   rebalance_decisions=len(ledger), mean_equity_exposure=statistics.mean(exposures),
                   commission_usd=fees, slippage_usd=slippage_total,
                   terminal_equity_usd=quantity * bars[-1]["close"], terminal_cash_usd=cash)
    return metrics, curve, ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    root, run_dir = args.project.resolve(), args.run_dir.resolve()
    cfg = json.loads((run_dir / "source_only/config.json").read_text())
    backend = run_dir / "backend"
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=backend, text=True).strip()
    assert commit == cfg["canonical_commit"]
    sys.path.insert(0, str(backend / "src"))
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from valuation_engine.backtest.walk_forward import NaiveDCFPolicy, FixedAllocationPolicy, BuyAndHoldPolicy
    from valuation_engine.cadence.formal_context import load_formal_context
    from valuation_engine.cadence.pipeline import CadencePipelineConfig, QuarterlyCadencePipeline
    from valuation_engine.db.schema import ForecastRun, ResearchValuation, AssumptionSet
    from valuation_engine.db.store import digest
    from valuation_engine.research.service import stored_periods, policy_payload
    from valuation_engine.research.dcf import explicit_fcff, DCFModel, ReverseDCFModel
    from valuation_engine.research.numbers import D, POLICY, MarketEquityShares, p, canonical

    inputs, outputs = run_dir / "inputs", run_dir / "outputs"
    inputs.mkdir(exist_ok=True)
    outputs.mkdir(exist_ok=True)
    original = root / "data/qve.db"
    original_hash = sha(original)
    isolated = inputs / "qve.db"
    if not isolated.exists():
        with ro(original) as source, sqlite3.connect(isolated) as dest:
            source.backup(dest)
    isolated_hash = sha(isolated)
    conn = ro(isolated)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    engine = create_engine("sqlite://", creator=lambda: ro(isolated))
    checks, audit, ids, info_rows, summaries, forecasts = [], [], {53, 54, 55}, [], [], []
    with Session(engine, autoflush=False) as db:
        runs = list(db.scalars(select(ForecastRun).join(AssumptionSet).where(
            ForecastRun.company_id == 1, ForecastRun.forecast_type == "first_tradable",
            ForecastRun.model_name == "Guidance Anchored Baseline",
            AssumptionSet.content_hash == digest(policy_payload())
        ).order_by(ForecastRun.forecast_as_of)))
        assert len(runs) == len({r.forecast_as_of for r in runs}) == 26
        chosen = [r for r in runs if r.metadata_json["anchor"] == cfg["valuation_quarter"]]
        assert len(chosen) == 1
        needed = [r for r in runs if cfg["backtest_start"][:4] <= str(r.forecast_as_of.year)
                  and r.forecast_as_of.date().isoformat() <= cfg["backtest_end"]
                  and r.forecast_as_of.date().isoformat() >= "2022-08-25"]
        if chosen[0] not in needed:
            needed.append(chosen[0])
        for run in needed:
            quarter = run.metadata_json["anchor"]
            values = list(db.scalars(select(ResearchValuation).where(
                ResearchValuation.forecast_run_id == run.id,
                ResearchValuation.valuation_model_version == POLICY["valuation_version"])))
            assert len(values) == 1
            value = values[0]
            formal = load_formal_context(isolated, cfg["ticker"], quarter,
                                         run.forecast_as_of.date().isoformat())
            assert formal.valuation_id == value.id
            periods = stored_periods(db, run.id)
            tests = temporal_audit(run, periods, value)
            audit += [dict(quarter=quarter, forecast_run_id=run.id, **t) for t in tests]
            document_ids(run.metadata_json, ids)
            document_ids(value.metadata_json, ids)
            base = value.metadata_json["source_valuation"]
            cash, debt = [D(base["inputs"]["balance:" + k]["value"]) for k in ("cash", "debt")]
            shares = MarketEquityShares(D(base["shares"]["share_count"]))
            projection = explicit_fcff(periods)
            assert projection["status"] == "available"
            scenarios = [DCFModel().value(projection["cashflows"], cash, debt, shares, D(w), D(g))
                         for w in POLICY["wacc_grid"] for g in POLICY["terminal_growth_grid"]]
            computed = next(s for s in scenarios if s["wacc"] == p("wacc_base") and s["terminal_growth"] == p("terminal_growth_base"))
            error = abs(computed["per_share"] - value.dcf_base)
            assert error < D("0.000001"), (quarter, error)
            checks.append(dict(quarter=quarter, forecast_run_id=run.id, valuation_id=value.id,
                               dcf_computed=computed["per_share"], dcf_stored=value.dcf_base,
                               absolute_difference=error, temporal_checks=len(tests), passed=True))
            price_available = conn.execute("SELECT available_at FROM market_prices WHERE id=?", (base["price"]["market_price_id"],)).fetchone()[0]
            signal = dict(quarter=quarter, as_of_date=run.forecast_as_of.date().isoformat(),
                          signal_timestamp=str(max(run.forecast_as_of, dt(price_available))),
                          model_checkpoint_timestamp=str(run.forecast_as_of),
                          price_data_available_at=price_available,
                          market_price=float(value.metadata_json["price"]),
                          quant_dcf_base=float(computed["per_share"]), forecast_run_id=run.id, valuation_id=value.id,
                          issuer_information_available_at=run.metadata_json["raw_guidance"]["revenue"]["available_at"],
                          share_available_at=base["shares"]["available_at"],
                          share_source_document_id=base["shares"]["source_document_id"],
                          price_market_id=base["price"]["market_price_id"],
                          price_basis_id=base["price"]["price_basis_id"],
                          diagnostic_policy="NaiveDCFPolicy; retrospective only")
            decision = NaiveDCFPolicy().decide(signal)
            signal.update(diagnostic_target_weight=decision.equity_weight,
                          diagnostic_price_to_dcf_gap=decision.expectations_gap)
            info_rows.append(signal)
            summaries.append(dict(quarter=quarter, forecast_run_id=run.id, valuation_id=value.id,
                                  forecast_key=run.identity_key, forecast_created_at=str(run.created_at),
                                  forecast_as_of=str(run.forecast_as_of), information_cutoff=str(run.information_cutoff),
                                  assumption_set_id=run.assumption_set_id, assumption_hash=digest(policy_payload()),
                                  classification=run.generated_kind))
            if quarter == cfg["valuation_quarter"]:
                for row in periods:
                    forecasts.append({k: row[k] for k in row if k != "metadata_json"})
                starting = D(run.metadata_json["starting_fcff"])
                reverse = ReverseDCFModel().solve(D(value.metadata_json["enterprise_value"]), starting, p("wacc_base"), p("terminal_growth_base"))
                flows = projection["cashflows"]
                cashflow_table = [dict(year=i, fcff_proxy_usd=v, discount_factor=(1 + p("wacc_base")) ** i,
                                      present_value_usd=v / (1 + p("wacc_base")) ** i)
                                  for i, v in enumerate(flows, 1)]
                terminal = flows[-1] * (1 + p("terminal_growth_base")) / (p("wacc_base") - p("terminal_growth_base"))
                chosen_result = dict(quarter=quarter, checkpoint=str(run.forecast_as_of),
                    forecast_run_id=run.id, valuation_id=value.id, currency="USD", financial_unit="USD (not millions)",
                    market_price=value.metadata_json["price"], balance_cash=cash, balance_debt=debt,
                    shares=base["shares"], source_price=base["price"], balance_inputs={k:v for k,v in base["inputs"].items() if k.startswith("balance:")},
                    formula=projection["formula"], parameters=run.metadata_json["parameters"],
                    raw_guidance=run.metadata_json["raw_guidance"], bias_adjusted_guidance=run.metadata_json["bias_adjusted_guidance"],
                    explicit_cashflows=cashflow_table, terminal_value_year5=terminal,
                    present_terminal_value=terminal/(1+p("wacc_base"))**5,
                    terminal_fraction_of_ev=(terminal/(1+p("wacc_base"))**5)/computed["enterprise_value"],
                    base=computed, sensitivity=scenarios, reverse_dcf=reverse,
                    internal_five_year_fcff_cagr=(flows[-1]/starting)**(D(1)/5)-1,
                    ratios={k:getattr(value,k) for k in ("ntm_pe","fy1_pe","fy2_pe","forward_fcf_yield","forward_ev_ebit")},
                    model_classification=cfg["classification"])
                dump(outputs / "valuation.json", canonical(chosen_result))
                dump(outputs / "valuation_provenance.json", {"forecast":run.metadata_json, "valuation":value.metadata_json})
                csv_write(outputs / "dcf_cashflows.csv", cashflow_table)
                csv_write(outputs / "dcf_sensitivity.csv", scenarios)
    engine.dispose()

    # Freeze only the source documents referenced by the selected NVDA vintages.
    sources = []
    for doc_id in sorted(ids):
        row = conn.execute("SELECT * FROM source_documents WHERE id=?", (doc_id,)).fetchone()
        assert row is not None and row["company_id"] == 1
        digest_value = row["content_hash"]
        path = root / "data/raw" / digest_value
        assert path.exists() and sha(path) == digest_value
        (inputs / "raw").mkdir(exist_ok=True)
        target = inputs / "raw" / digest_value
        if not target.exists():
            shutil.copyfile(path, target)
        assert sha(target) == digest_value
        sources.append(dict(document_id=doc_id, type=row["document_type"], url=row["source_url"],
                            retrieved_at=row["retrieved_at"], sha256=digest_value, local_path=str(target)))
    dump(outputs / "source_manifest.json", sources)
    # Rebuild the financial forecasts from eligible real facts using the canonical
    # pure forecast function. This cannot persist a forecast or migrate the DB.
    from valuation_engine.research.inputs import FinancialInputs
    from valuation_engine.research.forecast import ForecastPolicyV1, FIELDS, produce
    os.environ["QVE_RAW_DIR"] = str(inputs / "raw")
    rebuilds = []
    replay_engine = create_engine("sqlite://", creator=lambda: ro(isolated))
    with Session(replay_engine, autoflush=False) as db:
        for summary in summaries:
            run = db.get(ForecastRun, summary["forecast_run_id"])
            rebuilt = produce(FinancialInputs(db, 1, run.information_cutoff), ForecastPolicyV1("A"))
            persisted = stored_periods(db, run.id)
            assert len(rebuilt["periods"]) == len(persisted)
            errors = []
            for current, old in zip(rebuilt["periods"], persisted, strict=True):
                assert (current["fiscal_year"], current["fiscal_quarter"], current["period_type"]) == (old["fiscal_year"], old["fiscal_quarter"], old["period_type"])
                for field in FIELDS:
                    if current[field] is None or old[field] is None:
                        assert current[field] == old[field]
                    else:
                        errors.append(abs(current[field] - old[field]))
            assert max(errors) < D("0.00000002"), (summary["quarter"], max(errors))
            rebuilds.append(dict(quarter=summary["quarter"], forecast_run_id=run.id,
                                 numeric_fields_compared=len(errors), maximum_absolute_error=str(max(errors)), passed=True))
    replay_engine.dispose()
    dump(outputs / "forecast_rebuild_verification.json", rebuilds)
    # Auditable data coverage, including later data deliberately outside this test.
    dump(outputs / "coverage.json", dict(
        price_coverage=dict(conn.execute("SELECT min(timestamp) start,max(timestamp) end,count(*) rows FROM market_prices WHERE ticker='NVDA'").fetchone()),
        compatible_formal_quarters=len(runs), tested_formal_quarters=len(needed),
        copied_documents=len(sources), schema_version=conn.execute("SELECT version_num FROM alembic_version").fetchone()[0],
        canonical_commit=commit, assumption_hash=digest(policy_payload()),
        db_mode="isolated SQLite copy opened mode=ro + query_only; no migrations", config=cfg))
    rows = list(conn.execute("""SELECT p.timestamp,p.id,p.open,p.close,p.available_at,p.currency,
          b.split_adjusted_open,b.split_adjusted_close,b.basis_date,b.raw_open,b.split_factor
          FROM market_prices p JOIN price_bases b ON p.id=b.market_price_id
          WHERE p.ticker='NVDA' AND substr(p.timestamp,1,10)>=? AND substr(p.timestamp,1,10)<=?
          ORDER BY p.timestamp""", ("2022-08-25", cfg["backtest_end"])))
    raw_response = json.loads((inputs / "raw/95061f2842275691749f73737b8d26dd5c5409e5c9790ea27b61370dd8b32cee").read_bytes())["chart"]["result"][0]
    vendor = dict(zip(raw_response["timestamp"], zip(raw_response["indicators"]["quote"][0]["open"], raw_response["indicators"]["quote"][0]["close"])))
    bars = []
    for row in rows:
        assert row["currency"] == "USD"
        op, cl = float(row["split_adjusted_open"]), float(row["split_adjusted_close"])
        observed = vendor[int(dt(row["timestamp"]).timestamp())]
        assert op > 0 and cl > 0
        assert abs(op-observed[0]) < 1e-6 and abs(cl-observed[1]) < 1e-6
        bars.append(dict(date=row["timestamp"][:10], timestamp=row["timestamp"], open=op, close=cl,
                         market_price_id=row["id"], vendor_bar_available_at=row["available_at"], split_basis_date=row["basis_date"]))
    assert len(bars) == len({b["date"] for b in bars})
    # An open-price-dependent signal is executed strictly on the NEXT session.
    schedule = {}
    for signal in info_rows:
        matches = [b for b in bars if b["date"] > signal["as_of_date"]]
        if matches:
            execution = matches[cfg["execution_delay_sessions"]-1]
            assert dt(signal["signal_timestamp"]) < dt(execution["timestamp"])
            signal["execution_timestamp"] = execution["timestamp"]
            schedule[execution["date"]] = signal
    test_bars = [b for b in bars if cfg["backtest_start"] <= b["date"] <= cfg["backtest_end"]]
    assert test_bars[0]["date"] == cfg["backtest_start"] and test_bars[-1]["date"] == cfg["backtest_end"]
    assert test_bars[0]["date"] in schedule
    metrics, curves, ledger = [], [], []
    for policy in (NaiveDCFPolicy(), FixedAllocationPolicy(), BuyAndHoldPolicy()):
        for net in (False, True):
            m, curve, trades = simulate(test_bars, schedule, policy, cfg, net)
            metrics.append(m); curves += curve; ledger += trades
    # Preserve guard behavior: no revision target => no formal weights.
    guard = QuarterlyCadencePipeline(CadencePipelineConfig(
        fiscal_year=2025, fiscal_quarter=2, as_of_date=cfg["valuation_date"],
        qve_db_path=isolated, candidate_db_path=inputs/"absent_candidate.db")).run()
    assert guard.recommended_equity_weight is None and guard.recommended_cash_weight is None
    dump(outputs / "formal_cadence_guard.json", {"status":guard.pipeline_status,
        "recommended_equity_weight":guard.recommended_equity_weight,
        "recommended_cash_weight":guard.recommended_cash_weight,
        "revision_context":guard.receipt_data.get("revision_context"), "audit_log":guard.audit_log})
    dump(outputs / "valuation_reconciliation.json", canonical(checks))
    csv_write(outputs / "temporal_audit.csv", audit)
    csv_write(outputs / "forecast_lineage.csv", summaries)
    csv_write(outputs / "forecast_periods.csv", forecasts)
    csv_write(outputs / "prices.csv", test_bars)
    csv_write(outputs / "signals.csv", sorted(schedule.values(), key=lambda s:s["signal_timestamp"]))
    csv_write(outputs / "metrics.csv", metrics)
    csv_write(outputs / "trade_ledger.csv", ledger)
    csv_write(outputs / "daily_nav.csv", curves)
    dump(outputs / "metrics.json", metrics)
    conn.close()
    assert sha(original) == original_hash and sha(isolated) == isolated_hash
    dump(outputs / "execution_receipt.json", dict(canonical_commit=commit,
        original_db_sha256=original_hash, isolated_db_sha256=isolated_hash,
        databases_unchanged=True, temporal_checks=len(audit), dcf_recalculations=len(checks),
        financial_forecasts_rebuilt=len(rebuilds),
        price_bars_verified_against_original_vendor_json=len(test_bars),
        actual_orders=0, model_calls=0, label_database_reads=0, docker_calls=0,
        metrics=metrics))
    print(json.dumps({"valuation_per_share":str(chosen_result["base"]["per_share"]),
                      "sessions":len(test_bars), "temporal_checks":len(audit), "metrics":metrics},indent=2))


if __name__ == "__main__":
    main()
