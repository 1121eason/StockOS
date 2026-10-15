"""Pure fiscal-calendar arithmetic and period labels, without ingestion or storage."""

from datetime import date, timedelta


def fiscal_start(fy: int, fq: int) -> date:
    jan = date(fy - 1, 1, 31)
    last_sunday = jan - timedelta(days=(jan.weekday() + 1) % 7)
    return last_sunday + timedelta(days=1, weeks=13 * (fq - 1))


def prior_period(fy: int, fq: int, offset: int = 1) -> tuple[int, int]:
    n = fy * 4 + fq - 1 - offset
    return n // 4, n % 4 + 1


def period_name(fy, fq):
    return f"FY{fy}-Q{fq}"


def period_tuple(name):
    fy, fq = name.removeprefix("FY").split("-Q")
    return int(fy), int(fq)
