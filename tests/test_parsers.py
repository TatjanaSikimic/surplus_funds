from datetime import date
from decimal import Decimal

import pytest

from surplus_funds.sources import SOURCES, HtmlParser, PdfParser, SourceConfig, get_parser


def html_config(**overrides) -> SourceConfig:
    fields = dict(key="test_html", state="GA", county="Test", url="https://example.com",
                  file_format="html")
    return SourceConfig(**{**fields, **overrides})


HTML_LIST = b"""
<html><body>
<h1>Excess Funds List</h1>
<table>
  <tr><th>Parcel #</th><th>Owner Name</th><th>Sale Date</th><th>Excess Amount</th></tr>
  <tr><td>A-1</td><td>JOHN   DOE</td><td>05/2021</td><td>$1,000.50</td></tr>
  <tr><td>A-2</td><td>JANE ROE</td><td>11/25/2016</td><td>n/a</td></tr>
  <tr><td>A-3</td><td>MARY  MAJOR</td><td>11/25/2016</td><td>$ 20.00</td></tr>
  <tr><td colspan="4">Total: $1,020.50</td></tr>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# Hall County PDF (real file from the repo)
# ---------------------------------------------------------------------------


def test_hall_pdf_record_count(hall_pdf):
    records = get_parser(SOURCES["ga_hall"]).parse(hall_pdf)
    assert len(records) == 73
    assert sum(r["amount"] for r in records) == Decimal("962083.53")


def test_hall_pdf_first_record(hall_pdf):
    first = get_parser(SOURCES["ga_hall"]).parse(hall_pdf)[0]
    assert first["parcel_id"] == "15025A000047"
    assert first["owner_name"] == "NEWCOMB ALVIN"
    assert first["buyer_name"] == "JOSE MANZO-MADRIZAL"
    assert first["property_address"] == "3442 CANDLER ROAD"
    assert first["city"] == "GAINESVILLE"
    assert first["amount"] == Decimal("220.17")
    assert first["sale_date"] == date(2016, 11, 25)
    assert first["sale_date_precision"] == "day"
    assert first["external_id"] == "15025A000047|2016-11-25"
    assert first["raw_data"]["EXCESS FUNDS"] == "$ 220.17"


def test_hall_pdf_records_ready_for_upsert(hall_pdf):
    records = get_parser(SOURCES["ga_hall"]).parse(hall_pdf)
    # upsert_funds requires identical keys and unique external_ids.
    assert len({frozenset(r) for r in records}) == 1
    assert len({r["external_id"] for r in records}) == len(records)


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------


def test_get_parser_picks_class_by_format():
    assert isinstance(get_parser(SOURCES["ga_hall"]), PdfParser)
    assert isinstance(get_parser(html_config()), HtmlParser)
    with pytest.raises(ValueError):
        get_parser(html_config(file_format="xlsx"))


def test_html_parser_detects_header_and_skips_bad_rows():
    records = get_parser(html_config()).parse(HTML_LIST)

    # A-2 has no valid amount; the title and the total row are not records.
    assert [r["parcel_id"] for r in records] == ["A-1", "A-3"]

    first = records[0]
    assert first["owner_name"] == "JOHN DOE"
    assert first["amount"] == Decimal("1000.50")
    assert first["sale_date"] == date(2021, 5, 1)
    assert first["sale_date_precision"] == "month"
    assert first["external_id"] == "A-1|2021-05-01"


def test_header_repeated_on_every_page():
    html = HTML_LIST.replace(b"</table>", b"""
      <tr><th>Parcel #</th><th>Owner Name</th><th>Sale Date</th><th>Excess Amount</th></tr>
      <tr><td>B-1</td><td>NEW PAGE</td><td>Aug 2021</td><td>$5</td></tr>
    </table>""")
    records = get_parser(html_config()).parse(html)
    assert [r["parcel_id"] for r in records] == ["A-1", "A-3", "B-1"]


def test_unknown_header_needs_override():
    html = b"""<table>
      <tr><th>Parcel</th><th>Sale Date</th><th>Amount Due Owner</th></tr>
      <tr><td>C-1</td><td>2020-01-15</td><td>$99.99</td></tr>
    </table>"""

    with pytest.raises(ValueError, match="no header row found"):
        get_parser(html_config()).parse(html)

    config = html_config(header_overrides={"AMOUNT DUE OWNER": "amount"})
    records = get_parser(config).parse(html)
    assert records[0]["amount"] == Decimal("99.99")


def test_custom_id_fields():
    config = html_config(id_fields=("parcel_id",))
    records = get_parser(config).parse(HTML_LIST)
    assert records[0]["external_id"] == "A-1"


def test_table_selector():
    html = b"""
      <table id="other"><tr><th>Parcel</th><th>Amount</th></tr>
        <tr><td>X-1</td><td>$1</td></tr></table>
      <table id="funds"><tr><th>Parcel</th><th>Amount</th></tr>
        <tr><td>Y-1</td><td>$2</td></tr></table>
    """
    config = html_config(table_selector="table#funds", id_fields=("parcel_id",))
    records = get_parser(config).parse(html)
    assert [r["parcel_id"] for r in records] == ["Y-1"]
