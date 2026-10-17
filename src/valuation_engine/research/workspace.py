"""Offline, evidence-asserted research imports in an isolated append-only SQLite store.

This module deliberately never imports the formal database, decision engine, providers,
credentials, or live services. Timestamps and digests are assertions supplied by the
researcher, not authenticated source data or proof of an original historical vintage.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import UTC, datetime
from decimal import Context, Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from valuation_engine.research.dcf import DCFModel
from valuation_engine.research.numbers import MarketEquityShares

CLASSIFICATION = "research_reconstructed_not_historical_oos"
SCHEMA_VERSION = 1
MAX_DECIMAL_EXPONENT = 100
MAX_SERIALIZED_NUMBER_CHARS = 4096
APPLICATION_ID = 0x53525731
SCALAR_INPUTS = ("cash", "debt", "shares", "wacc", "terminal_growth")
UNITS = {
    "monetary": "USD",
    "shares": "actual_shares",
    "rates": "fraction",
    "cashflows": "annual_fcff_USD",
}
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,15}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"rw1_[0-9a-f]{64}\Z")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
_SCHEMA = (
    "CREATE TABLE workspace_meta (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
    "identity TEXT NOT NULL)",
    "CREATE TABLE research_runs (run_id TEXT PRIMARY KEY, input_hash TEXT NOT NULL UNIQUE, "
    "generated_at TEXT NOT NULL, result_json TEXT NOT NULL, result_hash TEXT NOT NULL)",
    "CREATE TRIGGER research_runs_no_replace BEFORE INSERT ON research_runs "
    "WHEN EXISTS (SELECT 1 FROM research_runs WHERE run_id = NEW.run_id "
    "OR input_hash = NEW.input_hash) "
    "BEGIN SELECT RAISE(ABORT, 'research runs are immutable'); END",
    "CREATE TRIGGER workspace_meta_no_replace BEFORE INSERT ON workspace_meta "
    "WHEN EXISTS (SELECT 1 FROM workspace_meta) "
    "BEGIN SELECT RAISE(ABORT, 'workspace identity is immutable'); END",
    "CREATE TRIGGER research_runs_no_update BEFORE UPDATE ON research_runs "
    "BEGIN SELECT RAISE(ABORT, 'research runs are immutable'); END",
    "CREATE TRIGGER research_runs_no_delete BEFORE DELETE ON research_runs "
    "BEGIN SELECT RAISE(ABORT, 'research runs are immutable'); END",
    "CREATE TRIGGER workspace_meta_no_update BEFORE UPDATE ON workspace_meta "
    "BEGIN SELECT RAISE(ABORT, 'workspace identity is immutable'); END",
    "CREATE TRIGGER workspace_meta_no_delete BEFORE DELETE ON workspace_meta "
    "BEGIN SELECT RAISE(ABORT, 'workspace identity is immutable'); END",
)
_IDENTITY = "stockos-isolated-research-workspace-v1"


def _object(value: Any, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label}: expected exactly keys {', '.join(sorted(keys))}")
    return value


def _text(value: Any, label: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise ValueError(f"{label}: nonempty text of at most {limit} characters required")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise ValueError(f"{label}: timezone-aware ISO timestamp required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone missing")
        return result.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label}: invalid timezone-aware ISO timestamp") from exc


def _decimal(value: Any, label: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{label}: finite JSON number, decimal string, or null required")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label}: nonfinite numbers are forbidden")
    raw = str(value)
    if len(raw) > 128 or not _NUMBER.fullmatch(raw):
        raise ValueError(f"{label}: invalid finite decimal representation")
    try:
        result = Decimal(raw)
    except DecimalException as exc:
        raise ValueError(f"{label}: invalid decimal") from exc
    if not result.is_finite() or (result and not -100 <= result.adjusted() <= 100):
        raise ValueError(f"{label}: finite decimal magnitude must be between 1e-100 and 1e101")
    # Magnitude alone does not bound zero: 0e-1000000 has no nonzero magnitude,
    # but fixed-point formatting would allocate over a million characters.
    exponent = result.as_tuple().exponent
    if not isinstance(exponent, int) or abs(exponent) > MAX_DECIMAL_EXPONENT:
        raise ValueError(f"{label}: decimal exponent must be between -100 and 100, including zero")
    return result


def _json(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("Bundle must be finite JSON data") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_bundle_json(value: str) -> dict:
    """Parse JSON without silently accepting duplicate keys or NaN/Infinity."""

    def invalid_constant(token: str):
        raise ValueError(f"Nonfinite JSON constant: {token}")

    try:
        result = json.loads(
            value, object_pairs_hook=_no_duplicates, parse_constant=invalid_constant
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError(f"Invalid research bundle JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError("Research bundle must be a JSON object")
    return result


def _validate(bundle: Any, now: datetime) -> tuple[dict, dict]:
    _object(
        bundle,
        {
            "schema_version",
            "ticker",
            "name",
            "as_of",
            "data_kind",
            "sources",
            "inputs",
            "assumptions",
        },
        "bundle",
    )
    if type(bundle["schema_version"]) is not int or bundle["schema_version"] != SCHEMA_VERSION:
        raise ValueError("schema_version must be integer 1")
    if not isinstance(bundle["ticker"], str) or not _TICKER.fullmatch(bundle["ticker"]):
        raise ValueError("ticker: expected uppercase market identifier, at most 16 characters")
    _text(bundle["name"], "name", 200)
    as_of = _timestamp(bundle["as_of"], "as_of")
    if as_of > now:
        raise ValueError("as_of must not be in the future")
    if bundle["data_kind"] not in ("real", "synthetic"):
        raise ValueError("data_kind must be real or synthetic")
    assumptions = _object(bundle["assumptions"], {"classification", "rationale"}, "assumptions")
    if assumptions["classification"] != CLASSIFICATION:
        raise ValueError(f"assumptions.classification must be {CLASSIFICATION}")
    _text(assumptions["rationale"], "assumptions.rationale", 5000)
    sources = bundle["sources"]
    if not isinstance(sources, list) or len(sources) > 1000:
        raise ValueError("sources must be a list with at most 1000 entries")
    source_times = {}
    for index, source in enumerate(sources):
        label = f"sources[{index}]"
        _object(source, {"id", "url", "published_at", "retrieved_at", "sha256"}, label)
        sid = source["id"]
        if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid in source_times:
            raise ValueError(f"{label}.id: unique source identifier required")
        url = source["url"]
        if (
            not isinstance(url, str)
            or len(url) > 2048
            or any(c.isspace() or ord(c) < 32 for c in url)
        ):
            raise ValueError(f"{label}.url: HTTP(S) source URL required")
        try:
            parts = urlsplit(url)
            if (
                parts.scheme not in ("https", "http")
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
            ):
                raise ValueError("invalid URL or embedded credentials")
            _ = parts.port
        except ValueError as exc:
            raise ValueError(f"{label}.url: HTTP(S) URL without credentials required") from exc
        if not isinstance(source["sha256"], str) or not _HASH.fullmatch(source["sha256"]):
            raise ValueError(f"{label}.sha256: lowercase 64-character digest required")
        published = _timestamp(source["published_at"], f"{label}.published_at")
        retrieved = _timestamp(source["retrieved_at"], f"{label}.retrieved_at")
        if published > as_of:
            raise ValueError(f"{label}: publication is after as_of (temporal leakage)")
        if retrieved < published or retrieved > now:
            raise ValueError(f"{label}: retrieval must be between publication and import time")
        source_times[sid] = published

    raw_inputs = _object(bundle["inputs"], {*SCALAR_INPUTS, "forecast_cashflows"}, "inputs")

    def evidence(raw: Any, label: str) -> Decimal | None:
        _object(raw, {"value", "source_ids", "available_at"}, label)
        result = _decimal(raw["value"], f"{label}.value")
        ids = raw["source_ids"]
        if (
            not isinstance(ids, list)
            or any(not isinstance(sid, str) for sid in ids)
            or len(ids) != len(set(ids))
            or any(sid not in source_times for sid in ids)
        ):
            raise ValueError(f"{label}.source_ids: unique known source IDs required")
        available = (
            None
            if raw["available_at"] is None
            else _timestamp(raw["available_at"], f"{label}.available_at")
        )
        if result is not None and (not ids or available is None):
            raise ValueError(f"{label}: non-null values require source_ids and available_at")
        if available is not None:
            if available > as_of:
                raise ValueError(f"{label}: availability is after as_of (temporal leakage)")
            if any(source_times[sid] > available for sid in ids):
                raise ValueError(f"{label}: availability cannot precede referenced publication")
        return result

    values: dict[str, Any] = {
        key: evidence(raw_inputs[key], f"inputs.{key}") for key in SCALAR_INPUTS
    }
    cashflows = raw_inputs["forecast_cashflows"]
    if not isinstance(cashflows, list) or len(cashflows) != 5:
        raise ValueError("inputs.forecast_cashflows must contain exactly five annual FCFF entries")
    values["forecast_cashflows"] = [
        evidence(value, f"inputs.forecast_cashflows[{index}]")
        for index, value in enumerate(cashflows)
    ]
    # Preserve supplied values and timestamps, while taking ownership of all mutable data.
    return parse_bundle_json(_json(bundle)), values


def _serial(value: Any) -> Any:
    if isinstance(value, Decimal):
        parts = value.as_tuple()
        exponent = parts.exponent
        if not value.is_finite() or not isinstance(exponent, int):
            raise ValueError("Cannot serialize a nonfinite research number")
        # Check an upper bound before formatting, including computed values and zeros.
        characters = max(len(parts.digits) + exponent, 1) + max(-exponent, 0) + 2
        if characters > MAX_SERIALIZED_NUMBER_CHARS:
            raise ValueError("Research number exceeds bounded serialization size")
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _serial(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serial(item) for item in value]
    return value


def _valuation(values: dict) -> dict:
    model = DCFModel()
    flows = values["forecast_cashflows"]
    missing = [key for key in SCALAR_INPUTS if values[key] is None]
    missing.extend(
        f"forecast_cashflows[{index}]" for index, value in enumerate(flows) if value is None
    )

    def evaluate(wacc: Decimal | None) -> dict:
        if missing:
            return {
                "status": "unavailable",
                "reason": "missing_required_inputs",
                "missing_inputs": missing,
                "version": model.version,
            }
        try:
            return model.value(
                flows,
                values["cash"],
                values["debt"],
                MarketEquityShares(values["shares"]),
                wacc,
                values["terminal_growth"],
            )
        except DecimalException:
            return {
                "status": "unavailable",
                "reason": "decimal_calculation_out_of_range",
                "version": model.version,
            }

    # Fixed precision is independent of caller Decimal settings and input display units.
    with localcontext(Context(prec=48)):
        base = evaluate(values["wacc"])
        scenarios = []
        for name, delta in (("higher_wacc", "0.01"), ("base", "0"), ("lower_wacc", "-0.01")):
            wacc = None if values["wacc"] is None else values["wacc"] + Decimal(delta)
            scenarios.append(
                {
                    "name": name,
                    "wacc": wacc,
                    "terminal_growth": values["terminal_growth"],
                    **evaluate(wacc),
                }
            )
    return _serial(
        {
            **base,
            "cashflows": flows,
            "parameters": {key: values[key] for key in SCALAR_INPUTS},
            "scenarios": scenarios,
            "model_version": model.version,
        }
    )


def _result(bundle: dict, values: dict, generated_at: str) -> dict:
    input_hash = _digest(_json(bundle))
    return {
        "run_id": f"rw1_{input_hash}",
        "input_hash": input_hash,
        "generated_at": generated_at,
        "mode": "research",
        "classification": CLASSIFICATION,
        "formal_decision": "withheld",
        "source_verification": "asserted_unverified",
        "schema_version": SCHEMA_VERSION,
        "units": dict(UNITS),
        **{key: bundle[key] for key in ("ticker", "name", "as_of", "data_kind")},
        "bundle": bundle,
        "valuation": _valuation(values),
    }


def _path(path: str | Path) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).strip() or str(path) == ":memory:":
        raise ValueError("An explicit separate SQLite file path is required")
    if isinstance(path, str) and path.startswith("file:"):
        raise ValueError("Supply a filesystem path, not a SQLite URI")
    result = Path(path).expanduser().absolute()
    if result.is_symlink():
        raise ValueError("Research database path must not be a symbolic link")
    if result.exists() and not result.is_file():
        raise ValueError("Research database path must identify a regular file")
    return result


def _connect(path: Path, mode: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize(connection: sqlite3.Connection) -> None:
    # Never adopt even an empty preexisting database: initialization is for a new file only.
    if connection.execute("SELECT name FROM sqlite_master").fetchone():
        raise ValueError("Refusing to initialize a nonempty database")
    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    for statement in _SCHEMA:
        connection.execute(statement)
    connection.execute("INSERT INTO workspace_meta VALUES (1, ?)", (_IDENTITY,))


def _check_database(connection: sqlite3.Connection) -> None:
    if (
        connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
        or connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
    ):
        raise ValueError("Not an isolated StockOS research workspace database")
    actual = {
        row[0]
        for row in connection.execute(
            "SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    if actual != set(_SCHEMA):
        raise ValueError("Research database schema is unexpected or corrupted")
    if [tuple(row) for row in connection.execute("SELECT * FROM workspace_meta")] != [
        (1, _IDENTITY)
    ]:
        raise ValueError("Research database identity is missing or corrupted")
    if connection.execute("PRAGMA quick_check").fetchall()[0][0] != "ok":
        raise ValueError("Research database integrity check failed")


def _decode(row: sqlite3.Row) -> dict:
    if any(not isinstance(row[key], str) for key in row.keys()):
        raise ValueError("Stored research result has invalid column types (corruption)")
    if _digest(row["result_json"]) != row["result_hash"]:
        raise ValueError("Stored research result hash mismatch (corruption)")
    try:
        result = parse_bundle_json(row["result_json"])
        generated = _timestamp(result["generated_at"], "stored generated_at")
        if generated > datetime.now(UTC):
            raise ValueError("Stored generation time is in the future")
        bundle, values = _validate(result["bundle"], generated)
        expected = _result(bundle, values, result["generated_at"])
        if (
            _json(expected) != row["result_json"]
            or result["run_id"] != row["run_id"]
            or result["input_hash"] != row["input_hash"]
            or result["generated_at"] != row["generated_at"]
        ):
            raise ValueError("Stored research result content or identity mismatch (corruption)")
        return result
    except (KeyError, TypeError, UnicodeError) as exc:
        raise ValueError("Stored research result is malformed or corrupted") from exc


def import_bundle(path: str | Path, bundle: dict) -> dict:
    """Validate, value, and atomically append a bundle; identical inputs return the first run.

    The explicit path must be a new file or a verified research workspace database. No
    directories are created, unrelated databases are rejected, and no data is fetched.
    """
    now = datetime.now(UTC)
    validated, values = _validate(bundle, now)
    result = _result(validated, values, now.isoformat())
    database = _path(path)
    existed = database.exists()
    connection = None
    try:
        # Exclusive creation prevents accidentally adopting an unrelated preexisting empty file.
        if not existed:
            try:
                with database.open("xb"):
                    pass
            except FileExistsError:
                existed = True
        connection = _connect(database, "rw")
        connection.execute("BEGIN IMMEDIATE")
        if not existed:
            _initialize(connection)
        _check_database(connection)
        # Verify every stored record before extending a possibly corrupted history.
        existing = None
        for row in connection.execute("SELECT * FROM research_runs"):
            saved = _decode(row)
            if saved["run_id"] == result["run_id"]:
                existing = saved
        if existing is not None:
            connection.commit()
            return existing
        encoded = _json(result)
        connection.execute(
            "INSERT INTO research_runs (run_id,input_hash,generated_at,result_json,result_hash) "
            "VALUES (?,?,?,?,?)",
            (
                result["run_id"],
                result["input_hash"],
                result["generated_at"],
                encoded,
                _digest(encoded),
            ),
        )
        connection.commit()
        return result
    except (sqlite3.Error, OSError) as exc:
        raise ValueError(f"Research database import failed: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()  # Closing rolls back any uncommitted transaction.


def list_runs(path: str | Path) -> list[dict]:
    """Return verified full results, newest first; an absent file returns [] without creation."""
    database = _path(path)
    if not database.exists():
        return []
    connection = None
    try:
        connection = _connect(database, "ro")
        connection.execute("BEGIN")
        _check_database(connection)
        return [
            _decode(row)
            for row in connection.execute(
                "SELECT * FROM research_runs ORDER BY generated_at DESC, run_id"
            )
        ]
    except (sqlite3.Error, OSError) as exc:
        raise ValueError(f"Cannot read research workspace database: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def load_run(path: str | Path, run_id: str) -> dict:
    """Load one verified result; absent/invalid identifiers raise ValueError, without creation."""
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid research run_id")
    for result in list_runs(path):
        if result["run_id"] == run_id:
            return result
    raise ValueError(f"Research run not found: {run_id}")
