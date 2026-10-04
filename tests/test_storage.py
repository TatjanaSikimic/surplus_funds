from dataclasses import replace
from decimal import Decimal

from sqlalchemy import func, update

from surplus_funds import storage
from surplus_funds.models import SurplusFund
from surplus_funds.sources import SOURCES, get_parser

# A separate key so the tests never touch a real "ga_hall" source.
CONFIG = replace(SOURCES["ga_hall"], key="test_ga_hall")


def import_hall(session, records):
    source = storage.get_or_create_source(session, CONFIG.key, **CONFIG.source_fields())
    storage.upsert_funds(session, source, records)
    return source


def test_full_pipeline(session, hall_pdf):
    """PDF -> parser -> upsert_funds -> queries."""
    records = get_parser(CONFIG).parse(hall_pdf)
    source = storage.get_or_create_source(session, CONFIG.key, **CONFIG.source_fields())

    assert storage.upsert_funds(session, source, records) == 73
    assert storage.count_funds(session, source_id=source.id) == 73
    assert source.last_scraped_at is not None

    fund = storage.get_fund_by_external_id(session, source.id, "15025A000047|2016-11-25")
    assert fund.owner_name == "NEWCOMB ALVIN"
    assert fund.amount == Decimal("220.17")
    assert fund.raw_data["MAPCODE"] == "15025A000047"


def test_second_import_does_not_duplicate(session, hall_pdf):
    records = get_parser(CONFIG).parse(hall_pdf)
    source = import_hall(session, records)
    import_hall(session, records)

    assert storage.count_funds(session, source_id=source.id) == 73


def test_second_import_updates_changed_values(session, hall_pdf):
    records = get_parser(CONFIG).parse(hall_pdf)
    source = import_hall(session, records)

    changed = [{**r, "amount": Decimal("1.00")} if i == 0 else r for i, r in enumerate(records)]
    import_hall(session, changed)
    session.expire_all()

    fund = storage.get_fund_by_external_id(session, source.id, records[0]["external_id"])
    assert fund.amount == Decimal("1.00")


def test_funds_missing_from_new_list_are_stale(session, hall_pdf):
    records = get_parser(CONFIG).parse(hall_pdf)
    source = import_hall(session, records)

    # now() is fixed within a transaction, so simulate that the first
    # import happened a day earlier.
    session.execute(
        update(SurplusFund)
        .where(SurplusFund.source_id == source.id)
        .values(last_seen_at=func.now() - func.make_interval(0, 0, 0, 1))
    )

    # The new list no longer contains the first record (e.g. it was paid out).
    import_hall(session, records[1:])

    stale = storage.list_stale_funds(session, source)
    assert [f.external_id for f in stale] == [records[0]["external_id"]]


def test_empty_list_writes_nothing(session):
    source = storage.get_or_create_source(session, CONFIG.key, **CONFIG.source_fields())

    assert storage.upsert_funds(session, source, []) == 0
    assert source.last_scraped_at is None


def test_list_funds_filters(session, hall_pdf):
    source = import_hall(session, get_parser(CONFIG).parse(hall_pdf))

    funds = storage.list_funds(session, source_id=source.id, min_amount=Decimal("10000"))
    assert funds
    assert all(f.amount >= Decimal("10000") for f in funds)
    assert [f.amount for f in funds] == sorted((f.amount for f in funds), reverse=True)

    by_owner = storage.list_funds(session, source_id=source.id, owner_name="newcomb")
    assert [f.parcel_id for f in by_owner] == ["15025A000047"]
