"""Independent output reconciliation using only exported local CSV/JSON files."""
import csv
import json
import math
import statistics
import sys
from decimal import Decimal as D
from pathlib import Path

p = Path(sys.argv[1])
def rows(name):
    return list(csv.DictReader((p/name).open(encoding="utf-8-sig")))
config = json.loads((p.parent/"source_only/config.json").read_text())
metrics = json.loads((p/"metrics.json").read_text())
prices = rows("prices.csv")
curves = rows("daily_nav.csv")
trades = rows("trade_ledger.csv")
rf = (1+config["annual_cash_rate"])**(1/252)-1
checks = []
for result in metrics:
    name, variant = result["strategy"], result["variant"]
    curve = [r for r in curves if (r["strategy"],r["variant"]) == (name,variant)]
    ledger = [r for r in trades if (r["strategy"],r["variant"]) == (name,variant)]
    lookup = {r["execution_timestamp"][:10]:r for r in ledger}
    cash, quantity, previous_nav, peak = config["initial_capital_usd"], 0., config["initial_capital_usd"], config["initial_capital_usd"]
    returns, drawdowns = [], []
    errors = []
    for bar, point in zip(prices,curve,strict=True):
        assert bar["date"] == point["date"]
        trade = lookup.get(bar["date"])
        if trade:
            assert trade["signal_timestamp"][:10] < bar["date"]
            assert math.isclose(cash,float(trade["cash_before_usd"]),abs_tol=1e-6)
            assert math.isclose(quantity,float(trade["normalized_shares_before"]),abs_tol=1e-8)
            q = float(trade["normalized_share_change"])
            cash -= q*float(trade["execution_split_adjusted_price"]) + float(trade["commission_usd"])
            quantity += q
        cash *= 1+rf
        nav = cash + quantity*float(bar["close"])
        errors.append(abs(nav-float(point["nav_usd"])))
        returns.append(nav/previous_nav-1)
        previous_nav = nav
        peak = max(peak,nav)
        drawdowns.append(nav/peak-1)
    assert max(errors) < 1e-6
    assert math.isclose(nav,result["final_nav_usd"],abs_tol=1e-6)
    assert math.isclose(min(drawdowns),result["max_drawdown"],abs_tol=1e-10)
    assert math.isclose(statistics.mean([r-rf for r in returns])/statistics.stdev(returns)*math.sqrt(252),result["sharpe"],abs_tol=1e-9)
    if name == "BuyAndHoldPolicy":
        k = (config["commission_bps"]+config["slippage_bps"])/10000 if variant == "net" else 0
        closed_form = config["initial_capital_usd"] * float(prices[-1]["close"]) / float(prices[0]["open"]) / (1+k)
        assert math.isclose(closed_form,nav,abs_tol=1e-6)
    checks.append(dict(strategy=name,variant=variant,max_daily_nav_error_usd=max(errors),passed=True))
value = json.loads((p/"valuation.json").read_text())
flows = [D(r["fcff_proxy_usd"]) for r in rows("dcf_cashflows.csv")]
w,g = D("0.10"),D("0.025")
pv = sum(f/(1+w)**i for i,f in enumerate(flows,1))
terminal_pv = flows[-1]*(1+g)/(w-g)/(1+w)**5
ev = pv+terminal_pv
equity = ev+D(value["balance_cash"])-D(value["balance_debt"])
share_value = equity/D(value["shares"]["share_count"])
assert abs(share_value-D(value["base"]["per_share"])) < D("0.00000001")
assert all(r["passed"] for r in json.loads((p/"forecast_rebuild_verification.json").read_text()))
result = dict(csv_accounting_checks=checks,independent_dcf_per_share=str(share_value),
              independent_dcf_ev=str(ev),all_passed=True)
(p/"independent_verification.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result,indent=2))
