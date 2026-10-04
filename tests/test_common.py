from datetime import date
from decimal import Decimal

import pytest

from surplus_funds.sources.common import clean_text, parse_amount, parse_sale_date


@pytest.mark.parametrize(
    "text, expected",
    [
        ("$3,789.69", Decimal("3789.69")),
        ("$ 220.17", Decimal("220.17")),
        ("1000", Decimal("1000")),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "n/a", "$"])
def test_parse_amount_invalid(text):
    with pytest.raises(ValueError):
        parse_amount(text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("November 25, 2016", (date(2016, 11, 25), "day")),
        ("Nov 25, 2016", (date(2016, 11, 25), "day")),
        ("11/25/2016", (date(2016, 11, 25), "day")),
        ("11/25/16", (date(2016, 11, 25), "day")),
        ("2016-11-25", (date(2016, 11, 25), "day")),
        ("May 2021", (date(2021, 5, 1), "month")),
        ("Aug 2021", (date(2021, 8, 1), "month")),
        ("05/2021", (date(2021, 5, 1), "month")),
    ],
)
def test_parse_sale_date(text, expected):
    assert parse_sale_date(text) == expected


def test_parse_sale_date_invalid():
    with pytest.raises(ValueError):
        parse_sale_date("sometime in 2021")


def test_clean_text():
    assert clean_text("  EXCESS\nFUNDS  ") == "EXCESS FUNDS"
    assert clean_text(None) == ""
