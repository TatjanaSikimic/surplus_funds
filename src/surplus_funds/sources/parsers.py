"""Universal table parsers for PDF and HTML surplus funds lists.

Both parsers share the same logic: find the header row, map each column
to a SurplusFund field using known header names, then turn every data row
into a normalized record. They differ only in how they read table rows
from the file.
"""

import io
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

import pdfplumber
from bs4 import BeautifulSoup

from surplus_funds.sources.common import clean_text, parse_amount, parse_sale_date
from surplus_funds.sources.config import SourceConfig

logger = logging.getLogger(__name__)

# Header names used by different counties for the same field.
# Headers are compared after normalize_header(), so case and punctuation don't matter.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "parcel_id": (
        "PARCEL",
        "PARCEL NUMBER",
        "PARCEL NO",
        "PARCEL ID",
        "MAPCODE",
        "MAP CODE",
        "PIN",
        "PARCEL IDENTIFICATION NUMBER",
        "ACCOUNT NUMBER",
        "TAX ID",
    ),
    "case_number": (
        "CASE",
        "CASE NUMBER",
        "CASE NO",
        "TAX DEED NUMBER",
        "TAX DEED NO",
        "CERTIFICATE NUMBER",
        "FILE NUMBER",
    ),
    "owner_name": (
        "OWNER",
        "OWNER NAME",
        "ORIGINAL OWNER",
        "PROPERTY OWNER",
        "FORMER OWNER",
        "OWNER OF RECORD",
        "DEFENDANT",
    ),
    "buyer_name": ("BUYER", "NAME OF BUYER", "PURCHASER", "SUCCESSFUL BIDDER", "HIGH BIDDER"),
    "property_address": (
        "SITUS",
        "SITUS ADDRESS",
        "PROPERTY ADDRESS",
        "ADDRESS",
        "PROPERTY LOCATION",
        "LOCATION",
    ),
    "city": ("CITY",),
    "amount": (
        "EXCESS FUNDS",
        "EXCESS",
        "EXCESS AMOUNT",
        "EXCESS PROCEEDS",
        "SURPLUS",
        "SURPLUS FUNDS",
        "SURPLUS AMOUNT",
        "OVERAGE",
        "AMOUNT",
        "BALANCE",
        "AMOUNT AVAILABLE",
    ),
    "sale_date": (
        "SALE DATE",
        "TAX SALE DATE",
        "DATE OF SALE",
        "DATE SOLD",
        "AUCTION DATE",
        "TAX SALE MONTH/YEAR",
        "SALE MONTH/YEAR",
    ),
    "status": ("STATUS", "CLAIM STATUS"),
}

TEXT_FIELDS = (
    "parcel_id",
    "case_number",
    "owner_name",
    "buyer_name",
    "property_address",
    "city",
    "status",
)


def normalize_header(text: str) -> str:
    """'Parcel #' -> 'PARCEL', 'Case No.' -> 'CASE NO', 'EXCESS\\nFUNDS' -> 'EXCESS FUNDS'."""
    text = re.sub(r"[#:.*()]", " ", text.upper())
    return " ".join(text.split())


_ALIAS_TO_FIELD = {
    normalize_header(alias): field_name for field_name, aliases in FIELD_ALIASES.items() for alias in aliases
}


class TableParser(ABC):
    """Turns table rows into records ready for storage.upsert_funds."""

    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self._aliases = {
            **_ALIAS_TO_FIELD,
            **{normalize_header(h): f for h, f in config.header_overrides.items()},
        }

    @abstractmethod
    def extract_rows(self, content: bytes) -> Iterator[list[str]]:
        """Yield every table row in the file as a list of cleaned cell strings."""

    def parse(self, content: bytes) -> list[dict[str, Any]]:
        """Parse a downloaded file into a list of normalized records."""
        headers = list(self.config.columns)
        mapping = self._map_headers(headers) if headers else None
        records: list[dict[str, Any]] = []
        skipped = 0

        for cells in self.extract_rows(content):
            # Blank rows and single-cell rows (titles, notes, totals) carry no record.
            if sum(1 for cell in cells if cell) <= 1:
                continue

            # A header row can appear at the top or be repeated on every page.
            detected = self._detect_header(cells)
            if detected:
                mapping, headers = detected, cells
                continue

            # Titles and notes above the first header row.
            if mapping is None:
                continue

            record = self._build_record(cells, mapping, headers)
            if record is None:
                skipped += 1
            else:
                records.append(record)

        if mapping is None:
            raise ValueError(
                f"{self.config.key}: no header row found. Add the column names to "
                f"'columns' or unknown headers to 'header_overrides' in the source config."
            )

        logger.info("%s: parsed %d records, skipped %d rows", self.config.key, len(records), skipped)
        return records

    def _map_headers(self, cells: list[str]) -> dict[int, str]:
        """Map column index -> field name for every recognized header."""
        mapping: dict[int, str] = {}
        for index, cell in enumerate(cells):
            field_name = self._aliases.get(normalize_header(cell))
            if field_name and field_name not in mapping.values():
                mapping[index] = field_name
        return mapping

    def _detect_header(self, cells: list[str]) -> dict[int, str] | None:
        """Return a column mapping if the row looks like a header row, else None."""
        mapping = self._map_headers(cells)
        if "amount" in mapping.values() and len(mapping) >= 2:
            return mapping
        return None

    def _build_record(self, cells: list[str], mapping: dict[int, str], headers: list[str]) -> dict[str, Any] | None:
        values = {field_name: cells[index] if index < len(cells) else "" for index, field_name in mapping.items()}
        raw_data = {
            (headers[i] if i < len(headers) and headers[i] else f"column_{i}"): cell
            for i, cell in enumerate(cells)
            if cell
        }

        try:
            amount = parse_amount(values.get("amount", ""))
        except ValueError:
            logger.warning("%s: row without a valid amount skipped: %s", self.config.key, raw_data)
            return None

        sale_date, precision = None, None
        if values.get("sale_date"):
            try:
                sale_date, precision = parse_sale_date(values["sale_date"])
            except ValueError:
                logger.warning("%s: unreadable sale date kept in raw_data: %r", self.config.key, values["sale_date"])

        # Every record has the same keys, which upsert_funds requires.
        record: dict[str, Any] = {name: values.get(name) or None for name in TEXT_FIELDS}
        record.update(
            amount=amount,
            sale_date=sale_date,
            sale_date_precision=precision,
            raw_data=raw_data,
        )

        id_parts = [record.get(name) for name in self.config.id_fields]
        if any(part is None for part in id_parts):
            logger.warning("%s: row missing %s skipped: %s", self.config.key, "/".join(self.config.id_fields), raw_data)
            return None
        record["external_id"] = "|".join(str(part) for part in id_parts)
        return record


class PdfParser(TableParser):
    """Reads ruled tables (with visible cell borders) from every page of a PDF."""

    def extract_rows(self, content: bytes) -> Iterator[list[str]]:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    for row in table:
                        yield [clean_text(cell) for cell in row]


class HtmlParser(TableParser):
    """Reads <table> elements from an HTML page."""

    def extract_rows(self, content: bytes) -> Iterator[list[str]]:
        soup = BeautifulSoup(content, "html.parser")
        if self.config.table_selector:
            tables = soup.select(self.config.table_selector)
        else:
            tables = soup.find_all("table")

        for table in tables:
            for tr in table.find_all("tr"):
                cells = tr.find_all(["th", "td"])
                yield [clean_text(cell.get_text(" ")) for cell in cells]


_PARSERS: dict[str, type[TableParser]] = {
    "pdf": PdfParser,
    "html": HtmlParser,
}


def get_parser(config: SourceConfig) -> TableParser:
    """Return the right parser for the source's file format."""
    try:
        return _PARSERS[config.file_format](config)
    except KeyError:
        raise ValueError(f"Unsupported file format: {config.file_format!r}") from None
