"""Decimal-only calculations and canonical serialization for immutable research outputs."""

import json
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, NewType

D = Decimal
EPSForecastShares = NewType("EPSForecastShares", Decimal)
MarketEquityShares = NewType("MarketEquityShares", Decimal)
POLICY = json.loads(Path(__file__).with_name("policy_v1.json").read_text())


def p(name: str) -> Decimal:
    return D(str(POLICY[name]))


def div(a, b):
    return a / b if a is not None and b is not None and b != 0 else None


def total(values):
    return sum(values, D(0)) if values and all(v is not None for v in values) else None


def mean(values):
    return sum(values, D(0)) / len(values) if values else None


def quantile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    pos = D(len(values) - 1) * fraction
    index = int(pos)
    return values[index] + (values[min(index + 1, len(values) - 1)] - values[index]) * (pos - index)


def median(values):
    return quantile(values, D("0.5"))


def dispersion(values):
    m = mean(values)
    return (sum(((v - m) ** 2 for v in values), D(0)) / len(values)).sqrt() if values else None


def stats(values):
    return {
        "sample_count": len(values),
        "mean": mean(values),
        "median": median(values),
        "dispersion": dispersion(values),
    }


def canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        with localcontext() as ctx:
            ctx.prec = 48
            return format(value.quantize(D(1).scaleb(-POLICY["decimal_places"])), "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(v) for v in value]
    return value


def bound(value, lower, upper, name, warnings):
    if value is None:
        return None
    if not value.is_finite():
        warnings.append({"parameter": name, "reason": "non_finite", "raw": str(value)})
        return None
    result = min(upper, max(lower, value))
    if result != value:
        warnings.append(
            {
                "parameter": name,
                "reason": "bounded",
                "raw": value,
                "used": result,
                "bounds": [lower, upper],
            }
        )
    return result
