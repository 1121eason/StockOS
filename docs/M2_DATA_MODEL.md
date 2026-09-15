# M2 additive data model

Core migration `0005_research` creates six append-only tables, without changing any M1.1 selection or normalization rules:

| Table | Responsibility |
|---|---|
| forecast_runs | Cutoff, first-tradable checkpoint, GAAP basis, reconstructed classification, model/version, immutable assumption and input-snapshot references, raw guidance, bias and complete provenance |
| forecast_periods | Eight quarterly full financial models and NTM/FY1/FY2 aggregates; Decimal values, common share basis, missing fields and empirical intervals |
| forecast_assumptions | Every frozen parameter, value, concrete unit, source/reference, effective-from and policy version |
| forecast_revisions | Same-fiscal-target comparisons, original/new model run IDs, old/new values, relative and percentage-point changes, explicit roll reasons |
| research_valuations | Forward multiples/yields, strictly prior distribution context, DCF sensitivity summary, reverse implied growth and expectations gap; linked M1.1 valuation and M2 forecast |
| dcf_scenarios | Fifteen WACC/terminal-growth cells with explicit FCFF proxy flows and PIT equity share provenance |

Labels migration `0003_forecast_outcomes` creates `forecast_outcomes` in the **separate label database**, with an immutable forecast content reference (no cross-database foreign key), actual-availability timestamp, evaluation timestamp and financial errors. Existing stock-return labels remain intact and are never read by the forecast engine.

All new tables reject UPDATE and DELETE at the database level on SQLite and PostgreSQL. Identity hashes and unique run/period/scenario constraints prevent duplicates. SQLite uses exact decimal text and PostgreSQL uses NUMERIC, continuing M1.1's storage contract. Existing legacy snapshots and the initial development-only M2 records remain available; the final benchmark cohort is identified by the typed frozen assumption hash and history manifest. New versions must coexist.
