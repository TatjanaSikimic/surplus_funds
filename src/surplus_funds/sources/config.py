"""Configuration describing a single source (one county list)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceConfig:
    """Everything needed to download and parse one list.

    Most sources only need the basic fields: the parser detects columns
    automatically from the table header. The optional fields cover
    lists that don't follow the usual patterns.
    """

    key: str  # unique identifier, e.g. "ga_hall"
    state: str  # two-letter state code
    county: str
    url: str
    file_format: str  # "pdf" or "html"
    agency: str | None = None

    # Header names in column order, for tables whose header row is not part
    # of the table itself (e.g. printed above the grid in a PDF).
    columns: tuple[str, ...] = ()

    # Extra header -> field mappings for headers the parser doesn't know,
    # e.g. {"AMOUNT DUE OWNER": "amount"}.
    header_overrides: dict[str, str] = field(default_factory=dict)

    # Fields combined into the unique external_id of each record.
    id_fields: tuple[str, ...] = ("parcel_id", "sale_date")

    # HTML only: CSS selector for the table(s) to read, e.g. "table#funds".
    table_selector: str | None = None

    def source_fields(self) -> dict[str, Any]:
        """Column values for the Source row in the database."""
        return {
            "state": self.state,
            "county": self.county,
            "agency": self.agency,
            "url": self.url,
            "file_format": self.file_format,
        }
