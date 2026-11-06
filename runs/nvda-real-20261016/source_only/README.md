# Local NVDA reproduction

This directory contains source only. Do not include `../inputs/`, original databases,
model responses, private research data, or credentials in a source handoff.
The parent run directory holds a separate canonical Git checkout and local outputs.
No canonical tracked source files were changed.

Run from `/Users/eason/Documents/Coding/StockOS` with the existing local environment:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python runs/nvda-real-20261016/source_only/run_nvda.py --project /Users/eason/Documents/Coding/StockOS --run-dir /Users/eason/Documents/Coding/StockOS/runs/nvda-real-20261016
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python runs/nvda-real-20261016/source_only/verify_results.py runs/nvda-real-20261016/outputs
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python runs/nvda-real-20261016/source_only/build_report.py runs/nvda-real-20261016
```

`run_nvda.py` requires the separate `../backend` checkout to resolve exactly to
`cbb78db1ea0fe8fef8565d855605c7696cb13f3c`. It verifies the immutable
ForecastPolicyV1 assumption hash, first-tradable formal cohort and corrected
Regime lineage. It opens the original `data/qve.db` strictly with SQLite
`mode=ro` plus `query_only`, and uses SQLite backup to create `../inputs/qve.db`
only when the isolated copy does not already exist. All computation reads that
copy in the same read-only mode. No migrations, model calls, label reads,
Docker commands, network calls or orders are issued by these scripts.

`config.json` fixes the interval, historical checkpoint, costs, cash rate and
unchanged existing policies. Its results are retrospective diagnostics. The
formal cadence dry run is deliberately left without a revision target and must
withhold weights. This directory does not repair or bypass its admission guards.

The runner compares all used forecasts rebuilt from real financial inputs with
stored forecasts, then recomputes DCF using the canonical pure functions. The
source hashes and required issuer/SEC/vendor bytes are copied locally.
Financial amounts are USD, and market-value shares are period-date outstanding
shares. Execution uses prices normalized to the vendor's 2026-09-12 split basis.
Model signal valuation uses matched as-traded prices/shares. There are no dividends.

Supporting canonical checks, from the separate backend directory:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/eason/Documents/Coding/StockOS/.venv/bin/python -m pytest tests/unit/test_dcf_research.py tests/unit/test_walk_forward_backtest.py tests/unit/test_cadence_formal_regime.py tests/unit/test_cadence_input_integrity.py tests/unit/test_cadence_revision_context.py -q -p no:cacheprovider --basetemp /Users/eason/Documents/Coding/StockOS/runs/nvda-real-20261016/pytest-tmp
```

Package/runtime versions are saved in `../outputs/runtime.json`. All deliverables
and evidence stay local. The scripts' stdout is a small computed summary only.
