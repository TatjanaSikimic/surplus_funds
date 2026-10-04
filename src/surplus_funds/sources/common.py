"""Low-level helpers shared by all parsers."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

_USER_AGENT = "Mozilla/5.0 (compatible; surplus-funds-aggregator/0.1)"

# Date formats seen on county lists, with the precision each one carries.
_DATE_FORMATS = (
    ("%B %d, %Y", "day"),  # November 25, 2016
    ("%b %d, %Y", "day"),  # Nov 25, 2016
    ("%m/%d/%Y", "day"),  # 11/25/2016
    ("%m/%d/%y", "day"),  # 11/25/16
    ("%Y-%m-%d", "day"),  # 2016-11-25
    ("%B %Y", "month"),  # May 2021
    ("%b %Y", "month"),  # Aug 2021
    ("%m/%Y", "month"),  # 05/2021
)


def download(url: str, timeout: int = 60) -> bytes:
    """Download a file and return its raw bytes. Raises on HTTP errors."""
    response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.content


def clean_text(value: str | None) -> str:
    """Collapse whitespace and line breaks inside a cell; None becomes ''."""
    if value is None:
        return ""
    return " ".join(value.split())


def parse_amount(text: str) -> Decimal:
    """Convert '$3,789.69' or '$ 220.17' to Decimal('3789.69')."""
    cleaned = text.replace("$", "").replace(",", "").replace(" ", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Invalid amount: {text!r}") from None


def parse_sale_date(text: str) -> tuple[date, str]:
    """Parse a sale date and return (date, precision).

    Month-only dates such as 'May 2021' become the 1st of the month
    with precision 'month'.
    """
    text = text.strip()
    for fmt, precision in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), precision
        except ValueError:
            continue
    raise ValueError(f"Unknown date format: {text!r}")
