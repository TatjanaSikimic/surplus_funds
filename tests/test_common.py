from datetime import date
from decimal import Decimal

import pytest
import requests

from surplus_funds.sources import common
from surplus_funds.sources.common import clean_text, parse_amount, parse_sale_date


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def test_download(monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return FakeResponse(200, b"%PDF-1.4")

    monkeypatch.setattr(common.requests, "get", fake_get)
    assert common.download("https://example.com/list.pdf") == b"%PDF-1.4"

    url, headers, timeout = calls[0]
    assert url == "https://example.com/list.pdf"
    assert "surplus-funds-aggregator" in headers["User-Agent"]
    assert timeout == 60


def test_download_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(common.requests, "get", lambda url, headers, timeout: FakeResponse(404))
    with pytest.raises(requests.HTTPError):
        common.download("https://example.com/missing.pdf")


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
