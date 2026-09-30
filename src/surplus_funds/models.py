from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from surplus_funds.db import Base


class Source(Base):
    """A surplus funds list published by a county office."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "ga_hall"
    state: Mapped[str] = mapped_column(String(2))               # e.g. "GA"
    county: Mapped[str] = mapped_column(String(100))            # e.g. "Hall"
    agency: Mapped[str | None] = mapped_column(String(255))     # e.g. "Tax Commissioner"
    url: Mapped[str] = mapped_column(String(500))
    file_format: Mapped[str] = mapped_column(String(10))        # "pdf" or "html"

    list_updated_at: Mapped[date | None] = mapped_column(Date)  # date printed on the list itself
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    funds: Mapped[list["SurplusFund"]] = relationship(back_populates="source")


class SurplusFund(Base):
    """A single list entry: surplus from one sale of one parcel."""

    __tablename__ = "surplus_funds"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(200))  # e.g. "15025A000047|2016-11-25"

    # Common fields shared across sources
    parcel_id: Mapped[str | None] = mapped_column(String(100), index=True)
    case_number: Mapped[str | None] = mapped_column(String(100))
    owner_name: Mapped[str | None] = mapped_column(String(255), index=True)
    buyer_name: Mapped[str | None] = mapped_column(String(255))
    property_address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    sale_date: Mapped[date | None] = mapped_column(Date)
    sale_date_precision: Mapped[str | None] = mapped_column(String(10))  # "day" or "month"
    status: Mapped[str | None] = mapped_column(String(50))              # e.g. "pending_claim"

    # Original row from the list, including any source-specific fields
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped[Source] = relationship(back_populates="funds")