# Isolated offline research workspace

This workflow imports a researcher-prepared JSON bundle, uses the canonical
`valuation_engine.research.dcf.DCFModel`, and stores an immutable result in a separately
specified SQLite file. It never reads the formal application database, writes formal
forecasts or decisions, reads credentials, fetches sources, or calls live services.

Every result is explicitly:

- `mode: research`
- `classification: research_reconstructed_not_historical_oos`
- `formal_decision: withheld`
- `source_verification: asserted_unverified`

`data_kind: real` describes the importer's assertion about the economic data. It is not
verification by this application. URLs, publication times, availability times, and SHA-256
values are supplied assertions. No remote page or file is downloaded or authenticated.
A digest records the asserted source identity, not proof that its contents or publication
time were checked. Nothing here is evidence of an original forecast vintage, a historical
out-of-sample result, or investment advice.

## Commands

Run from the repository with its Python environment installed:

```sh
python scripts/import_research_workspace.py \
  --db /absolute/path/to/research.sqlite import /absolute/path/to/bundle.json
python scripts/import_research_workspace.py \
  --db /absolute/path/to/research.sqlite list
python scripts/import_research_workspace.py \
  --db /absolute/path/to/research.sqlite show rw1_<64-character-input-hash>
```

The database path is always required. Its parent directory must already exist. A new file
is initialized; an unrelated preexisting database, including an empty file, is rejected.
Never point this command at the formal database. JSON is printed to stdout. Invalid input,
unknown runs, or invalid databases produce an error on stderr and exit code 2. The tool
does not print a success receipt for a failed import.

Python APIs:

```python
from valuation_engine.research.workspace import import_bundle, list_runs, load_run

result = import_bundle("/absolute/path/to/research.sqlite", bundle)
results = list_runs("/absolute/path/to/research.sqlite")
result = load_run("/absolute/path/to/research.sqlite", result["run_id"])
```

`list_runs` returns full result objects, newest first, with top-level `ticker`, `name`,
`as_of`, `data_kind`, and `run_id`. It returns an empty list for an absent database without
creating the file or its parent. `load_run` raises `ValueError` for an invalid or absent
run. SQLite errors are exposed as `ValueError`, rather than leaking backend tracebacks to
HTTP callers. Read calls use SQLite read-only mode.

## Exact JSON contract, version 1

Every object has exactly the keys shown below. All are required. Unknown keys, duplicate
JSON keys, unsupported schema versions, malformed identifiers, nonfinite values, invalid
URLs, and timezone-naive timestamps are rejected. Structural omissions are errors. Missing
economic data must be represented by a `null` value, not a fabricated zero.

```json
{
  "schema_version": 1,
  "ticker": "DEMO",
  "name": "Synthetic Company",
  "as_of": "2024-06-02T00:00:00Z",
  "data_kind": "synthetic",
  "sources": [
    {
      "id": "issuer_2024",
      "url": "https://example.com/filing",
      "published_at": "2024-06-01T00:00:00Z",
      "retrieved_at": "2025-01-01T00:00:00Z",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ],
  "inputs": {
    "cash": {"value": "100", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
    "debt": {"value": "200", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
    "shares": {"value": "100", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
    "wacc": {"value": "0.10", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
    "terminal_growth": {"value": "0.02", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
    "forecast_cashflows": [
      {"value": "100", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
      {"value": "110", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
      {"value": "120", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
      {"value": "130", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"},
      {"value": "140", "source_ids": ["issuer_2024"], "available_at": "2024-06-01T00:00:00Z"}
    ]
  },
  "assumptions": {
    "classification": "research_reconstructed_not_historical_oos",
    "rationale": "Reconstructed annual FCFF assumptions supported by the cited source; not an original historical forecast."
  }
}
```

This example is wholly synthetic. Its URL and digest are illustrative assertions.

Field rules:

- `schema_version` is the integer `1`, not a boolean or string.
- `ticker` begins with an uppercase ASCII letter and contains at most 16 uppercase
  letters, digits, dots, or hyphens. `name` is nonempty text of at most 200 characters.
- `data_kind` is exactly `real` or `synthetic`.
- Dates are full ISO datetimes with seconds, optional 1–6 fractional digits, and `Z` or a
  `±HH:MM` offset. Comparisons use actual UTC instants. `as_of` cannot be in the future.
- `sources` has at most 1,000 entries. IDs begin with an ASCII letter, contain only
  letters, digits, underscores, dots, or hyphens, and are at most 64 characters. IDs are
  unique. URLs use HTTP(S), have a hostname, contain no whitespace or embedded credentials,
  and are at most 2,048 characters. SHA-256 values contain exactly 64 lowercase hex digits.
- Every source publication is on or before `as_of`. Retrieval must be on or after
  publication and on or before import time. Retrieval **may be after `as_of`** because this
  is a present-day reconstruction. Retrieval is never substituted for original vintage.
- `inputs` has five named scalar entries plus exactly five annual FCFF entries, ordered
  from year 1 through year 5. Forecast support references mean evidence for a reconstruction
  assumption; they do not claim that future realized cashflows were already published.
- Every input has exactly `value`, `source_ids`, and `available_at`. A non-null value needs
  one or more unique known source IDs and a non-null availability timestamp. Availability
  cannot precede the publications it references, and cannot exceed `as_of`.
- A missing value can be `{"value": null, "source_ids": [], "available_at": null}`. It can
  also retain known supporting provenance; all supplied references and dates are checked.
- Values are finite JSON numbers or decimal strings. Decimal strings are preferable to
  binary floating-point numbers for exact input provenance. Strings follow JSON numeric
  spelling, with no whitespace, leading `+`, or separators. Maximum representation length
  is 128 characters; nonzero decimal magnitudes must be at least `1e-100` and below `1e101`.
  The stored Decimal exponent must be between -100 and 100 for all values, including zero.
  Fixed-point result serialization is additionally bounded before allocation (4,096 characters
  per number), so short extreme-exponent strings cannot expand into huge stored results.
- `assumptions.classification` must exactly equal the research classification above.
  `rationale` is nonempty text, at most 5,000 characters, explaining the reconstruction.

### Fixed units and conventions

Cash, debt, and all five annual FCFF values are absolute **USD**. Shares are actual shares,
not millions or weighted-average EPS shares. Rates are fractions (`0.10` means 10%). No
implicit unit conversion, million scaling, market-price lookup, or currency conversion is
performed. `per_share` is USD per actual share. Cashflows are the researcher's annual FCFF
forecasts and must be coherent with enterprise valuation; unadjusted CFO minus capex is
not automatically asserted to be FCFF. Corporate-action basis and economic assumptions
remain the researcher's responsibility and should be stated in the rationale.

## Calculation and result contract

The base valuation and three fixed WACC sensitivity cases all call `DCFModel.value`.
Cash, debt, shares, and terminal growth are held fixed for sensitivity analysis:

1. `higher_wacc`: base WACC + 0.01 (one percentage point)
2. `base`: base WACC
3. `lower_wacc`: base WACC − 0.01

The sensitivity cases are mechanical assumptions, not probability-weighted forecasts,
recommendations, or formal decisions. No rates are silently clamped. Each case can be
unavailable independently if canonical DCF conditions fail. Calculation uses a fixed
48-digit Decimal context, independent of the caller's Decimal settings.

Each full result contains:

- `schema_version`, `run_id`, `input_hash`, `generated_at`
- `ticker`, `name`, `as_of`, `data_kind`
- `mode`, `classification`, `formal_decision`, `source_verification` as specified above
- `units`: `{"monetary":"USD","shares":"actual_shares","rates":"fraction","cashflows":"annual_fcff_USD"}`
- `bundle`: the entire validated original JSON bundle, preserving supplied timestamps,
  numeric representation, provenance, and assumptions
- `valuation`: canonical DCF status and, when available, `enterprise_value`, `equity_value`,
  `per_share`, `wacc`, `terminal_growth`, `version`, and `negative_equity_warning`; plus
  `cashflows`, `parameters`, `scenarios`, and `model_version`

`parameters` contains `cash`, `debt`, `shares`, `wacc`, and `terminal_growth`. Calculated and
parameter numbers serialize as decimal strings; missing numbers remain null. `cashflows`
is the five-element list. Each scenario has `name`, `wacc`, `terminal_growth`, and its
canonical status/results. Unavailable valuations have a `reason` and no fabricated
`per_share`. Missing data also produces `missing_inputs`.

Zero cash or debt is legitimate. Zero equity is legitimate and remains available. Negative
equity and per-share values are preserved with the canonical warning. Negative interim
cashflows are allowed. Nonpositive shares, negative cash/debt, nonpositive terminal cashflow,
nonpositive WACC, or WACC at/below terminal growth produce explicit unavailable results.
These economic-domain failures are distinct from malformed JSON, which is rejected.

## Storage, identity, and limitations

`input_hash` is SHA-256 of the raw validated bundle serialized with sorted keys, compact
separators, ASCII escapes, and finite JSON values. Object-key ordering does not change the
hash; different numeric spelling, source order, or timestamps can. `run_id` is
`rw1_` followed by that hash. Identical imports return the original complete result and its
original `generated_at`; different contents append a new run. `generated_at` is current
import time, never an asserted historical creation date.

Initialization records a distinct SQLite application ID, schema version, and singleton
workspace identity. Opening an existing file requires an exact expected table/trigger
schema, identity, and integrity check. Writes use a transaction and preserve all prior
runs. Triggers reject update, delete, and replacement of runs and workspace identity.
Each stored result has an independent content hash, and reads reconstruct the expected
result to verify the bundle identity and valuation. Imports validate all prior records
before appending, so corrupt history is not silently extended. This deliberately simple
store is suitable for modest local research collections; validation reads the full history.

These checks detect accidental modification and ordinary SQL writes. They are not signed
attestation, a hostile filesystem security boundary, or a backup system. A process with
write access to the database can still drop triggers or replace the entire file. Keep
normal filesystem permissions and backups appropriate to the data. The database is never
converted to the application's formal schema, and research runs never become formal
trading decisions through this workflow.

Schema 2 supports narrowly typed internal policy artifacts for current reconstruction; see [the internal-policy contract and storage compatibility notes](INTERNAL_POLICY_RECONSTRUCTION.md). Schema 1 remains unchanged.
