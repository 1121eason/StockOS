from datetime import datetime

import pytest

from valuation_engine.time import calculate_next_tradable_timestamp


@pytest.mark.parametrize(
    "at,expected",
    [
        ("2023-05-24T16:20:00-04:00", "2023-05-25T09:30:00-04:00"),
        ("2023-05-26T16:20:00-04:00", "2023-05-30T09:30:00-04:00"),
        ("2023-11-24T13:01:00-05:00", "2023-11-27T09:30:00-05:00"),
        ("2023-11-24T12:00:00-05:00", "2023-11-27T09:30:00-05:00"),
        ("2024-03-08T16:20:00-05:00", "2024-03-11T09:30:00-04:00"),
        ("2024-11-01T16:20:00-04:00", "2024-11-04T09:30:00-05:00"),
        ("2024-07-04T10:00:00-04:00", "2024-07-05T09:30:00-04:00"),
        ("2024-06-08T12:00:00-04:00", "2024-06-10T09:30:00-04:00"),
        ("2024-06-10T09:29:59-04:00", "2024-06-10T09:30:00-04:00"),
        ("2024-06-10T09:30:00-04:00", "2024-06-10T09:30:00-04:00"),
    ],
)
def test_next_open(at, expected):
    assert calculate_next_tradable_timestamp(datetime.fromisoformat(at)) == datetime.fromisoformat(
        expected
    )


def test_timezone_required():
    with pytest.raises(ValueError):
        calculate_next_tradable_timestamp(datetime(2024, 1, 1))
