"""Pure cash-flow calculations shared by the frozen forecast and DCF policies."""


def fcff_proxy(row):
    if row is None:
        return None
    fcf, ni, oi, tax = (
        row.get(k) for k in ("free_cash_flow", "net_income", "operating_income", "tax_rate")
    )
    return (
        fcf - ni + oi * (1 - tax)
        if all(v is not None for v in (fcf, ni, oi, tax)) and 0 <= tax <= 1
        else None
    )
