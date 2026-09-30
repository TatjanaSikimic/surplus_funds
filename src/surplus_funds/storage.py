"""Database access layer: CRUD operations for sources and surplus funds.

Functions in this module never commit. The caller owns the transaction,
so several operations either all succeed or all get rolled back:

    with SessionLocal() as session:
        source = get_or_create_source(session, "ga_hall", state="GA", ...)
        upsert_funds(session, source, records)
        session.commit()
"""

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from surplus_funds.models import Source, SurplusFund

# Columns that identify a row and must never be changed by an update.
_SOURCE_PROTECTED = {"id"}
_FUND_PROTECTED = {"id", "source_id", "external_id", "first_seen_at"}

# Keeps each INSERT well below PostgreSQL's limit of 65,535 bound parameters.
_UPSERT_BATCH_SIZE = 1000


def _apply_fields(obj: Source | SurplusFund, fields: dict[str, Any], protected: set[str]) -> None:
    """Set column values on a model instance, rejecting unknown or protected columns."""
    columns = obj.__table__.columns.keys()
    for name, value in fields.items():
        if name not in columns:
            raise ValueError(f"{type(obj).__name__} has no column {name!r}")
        if name in protected:
            raise ValueError(f"Column {name!r} cannot be updated")
        setattr(obj, name, value)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def create_source(session: Session, key: str, **fields: Any) -> Source:
    """Create a new source. Raises IntegrityError if the key already exists."""
    source = Source(key=key, **fields)
    session.add(source)
    session.flush()  # assigns source.id without committing
    return source


def get_source(session: Session, source_id: int) -> Source | None:
    return session.get(Source, source_id)


def get_source_by_key(session: Session, key: str) -> Source | None:
    return session.scalar(select(Source).where(Source.key == key))


def get_or_create_source(session: Session, key: str, **fields: Any) -> Source:
    """Return the source with the given key, creating it if it doesn't exist."""
    source = get_source_by_key(session, key)
    if source is None:
        source = create_source(session, key, **fields)
    return source


def list_sources(session: Session, state: str | None = None) -> Sequence[Source]:
    stmt = select(Source).order_by(Source.state, Source.county)
    if state:
        stmt = stmt.where(Source.state == state.upper())
    return session.scalars(stmt).all()


def update_source(session: Session, source_id: int, **fields: Any) -> Source | None:
    """Update the given columns. Returns None if the source doesn't exist."""
    source = get_source(session, source_id)
    if source is None:
        return None
    _apply_fields(source, fields, _SOURCE_PROTECTED)
    session.flush()
    return source


def delete_source(session: Session, source_id: int) -> bool:
    """Delete a source together with all of its funds. Returns False if not found."""
    session.execute(delete(SurplusFund).where(SurplusFund.source_id == source_id))
    result = session.execute(delete(Source).where(Source.id == source_id))
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Surplus funds
# ---------------------------------------------------------------------------


def create_fund(
    session: Session,
    source: Source,
    external_id: str,
    amount: Decimal,
    **fields: Any,
) -> SurplusFund:
    """Create a single fund. For importing whole lists, use upsert_funds instead."""
    fund = SurplusFund(source=source, external_id=external_id, amount=amount, **fields)
    session.add(fund)
    session.flush()
    return fund


def get_fund(session: Session, fund_id: int) -> SurplusFund | None:
    return session.get(SurplusFund, fund_id)


def get_fund_by_external_id(
    session: Session, source_id: int, external_id: str
) -> SurplusFund | None:
    stmt = select(SurplusFund).where(
        SurplusFund.source_id == source_id,
        SurplusFund.external_id == external_id,
    )
    return session.scalar(stmt)


def _fund_filters(
    *,
    source_id: int | None = None,
    state: str | None = None,
    county: str | None = None,
    owner_name: str | None = None,
    parcel_id: str | None = None,
    status: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
) -> list[ColumnElement[bool]]:
    """Build WHERE conditions shared by list_funds and count_funds."""
    conditions: list[ColumnElement[bool]] = []
    if source_id is not None:
        conditions.append(SurplusFund.source_id == source_id)
    if state:
        conditions.append(Source.state == state.upper())
    if county:
        conditions.append(func.lower(Source.county) == county.lower())
    if owner_name:
        conditions.append(SurplusFund.owner_name.ilike(f"%{owner_name}%"))
    if parcel_id:
        conditions.append(SurplusFund.parcel_id == parcel_id)
    if status:
        conditions.append(SurplusFund.status == status)
    if min_amount is not None:
        conditions.append(SurplusFund.amount >= min_amount)
    if max_amount is not None:
        conditions.append(SurplusFund.amount <= max_amount)
    return conditions


def list_funds(
    session: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    **filters: Any,
) -> Sequence[SurplusFund]:
    """Search funds, largest amounts first.

    Filters: source_id, state, county, owner_name (partial, case-insensitive),
    parcel_id, status, min_amount, max_amount.

        list_funds(session, state="GA", min_amount=Decimal("10000"))
    """
    stmt = (
        select(SurplusFund)
        .join(SurplusFund.source)
        .where(*_fund_filters(**filters))
        .order_by(SurplusFund.amount.desc(), SurplusFund.id)
        .limit(limit)
        .offset(offset)
    )
    return session.scalars(stmt).all()


def count_funds(session: Session, **filters: Any) -> int:
    """Count funds matching the same filters as list_funds (useful for pagination)."""
    stmt = (
        select(func.count())
        .select_from(SurplusFund)
        .join(SurplusFund.source)
        .where(*_fund_filters(**filters))
    )
    return session.scalar(stmt) or 0


def update_fund(session: Session, fund_id: int, **fields: Any) -> SurplusFund | None:
    """Update the given columns. Returns None if the fund doesn't exist."""
    fund = get_fund(session, fund_id)
    if fund is None:
        return None
    _apply_fields(fund, fields, _FUND_PROTECTED)
    session.flush()
    return fund


def delete_fund(session: Session, fund_id: int) -> bool:
    """Delete a fund. Returns False if not found."""
    result = session.execute(delete(SurplusFund).where(SurplusFund.id == fund_id))
    return result.rowcount > 0


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


def upsert_funds(session: Session, source: Source, records: Iterable[dict[str, Any]]) -> int:
    """Insert new funds and update existing ones, matched by (source, external_id).

    Each record is a dict of SurplusFund columns produced by a parser. All
    records must have the same keys and must include external_id and amount.
    Values in raw_data must be JSON-serializable (plain strings are safest).

    Existing rows get their fields refreshed and last_seen_at bumped;
    first_seen_at is never touched. Returns the number of records processed.

    An empty list is treated as a failed scrape: nothing is written and
    source.last_scraped_at is left unchanged, so no funds are marked stale.
    """
    # The same external_id twice in one INSERT makes PostgreSQL fail,
    # so keep only the last occurrence.
    unique = {record["external_id"]: record for record in records}
    rows = [{**record, "source_id": source.id} for record in unique.values()]
    if not rows:
        return 0

    for start in range(0, len(rows), _UPSERT_BATCH_SIZE):
        batch = rows[start : start + _UPSERT_BATCH_SIZE]
        stmt = insert(SurplusFund).values(batch)
        updates = {
            name: stmt.excluded[name]
            for name in batch[0]
            if name not in _FUND_PROTECTED
        }
        updates["last_seen_at"] = func.now()
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_id", "external_id"],
            set_=updates,
        )
        session.execute(stmt)

    # func.now() is the transaction start time, the same value used for
    # last_seen_at above, which keeps list_stale_funds exact.
    source.last_scraped_at = func.now()
    session.flush()
    return len(rows)


def list_stale_funds(session: Session, source: Source) -> Sequence[SurplusFund]:
    """Funds missing from the most recent scrape of this source.

    These were most likely paid out or transferred to the state.
    """
    if source.last_scraped_at is None:
        return []
    stmt = (
        select(SurplusFund)
        .where(
            SurplusFund.source_id == source.id,
            SurplusFund.last_seen_at < source.last_scraped_at,
        )
        .order_by(SurplusFund.last_seen_at)
    )
    return session.scalars(stmt).all()