"""Command-line interface: surplus-funds <command>.

    surplus-funds sources                      list configured sources
    surplus-funds scrape ga_hall               download, parse and store a list
    surplus-funds scrape ga_hall --file x.pdf  same, from a local file
    surplus-funds funds --state GA             search stored funds
    surplus-funds stale ga_hall                funds missing from the latest list
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import requests

from surplus_funds.sources import SOURCES, get_parser
from surplus_funds.sources.common import download

# Database modules are imported inside the commands that need them:
# surplus_funds.db reads DATABASE_URL on import, and `sources` works without it.


def format_amount(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def cmd_sources(args: argparse.Namespace) -> int:
    for config in SOURCES.values():
        print(f"{config.key:<15} {config.state}  {config.county:<20} {config.file_format:<5} {config.url}")
    return 0


def cmd_scrape(args: argparse.Namespace) -> int:
    from surplus_funds import storage
    from surplus_funds.db import SessionLocal

    config = SOURCES[args.key]
    try:
        content = args.file.read_bytes() if args.file else download(config.url)
        records = get_parser(config).parse(content)
    except (OSError, requests.RequestException, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    with SessionLocal() as session:
        source = storage.get_or_create_source(session, config.key, **config.source_fields())
        # Keep the stored URL etc. in sync with registry.py.
        storage.update_source(session, source.id, **config.source_fields())
        count = storage.upsert_funds(session, source, records)
        session.commit()

        if count == 0:
            print(f"{config.key}: no records found, nothing was written", file=sys.stderr)
            return 1

        total = storage.count_funds(session, source_id=source.id)
        stale = len(storage.list_stale_funds(session, source))
        print(f"{config.key}: {count} records imported, {total} in database, {stale} stale")
    return 0


def cmd_funds(args: argparse.Namespace) -> int:
    from surplus_funds import storage
    from surplus_funds.db import SessionLocal

    filters = {
        "state": args.state,
        "county": args.county,
        "owner_name": args.owner,
        "parcel_id": args.parcel,
        "min_amount": args.min_amount,
        "max_amount": args.max_amount,
    }
    with SessionLocal() as session:
        if args.source:
            source = storage.get_source_by_key(session, args.source)
            if source is None:
                print(f"error: source {args.source!r} has not been scraped yet", file=sys.stderr)
                return 1
            filters["source_id"] = source.id

        funds = storage.list_funds(session, limit=args.limit, **filters)
        total = storage.count_funds(session, **filters)

        for fund in funds:
            print(
                f"{format_amount(fund.amount):>14}  {fund.sale_date or '':<10}  "
                f"{fund.source.state} {fund.source.county:<12}  {fund.parcel_id or '':<16}  "
                f"{fund.owner_name or ''}"
            )
    print(f"showing {len(funds)} of {total}")
    return 0


def cmd_stale(args: argparse.Namespace) -> int:
    from surplus_funds import storage
    from surplus_funds.db import SessionLocal

    with SessionLocal() as session:
        source = storage.get_source_by_key(session, args.key)
        if source is None:
            print(f"error: source {args.key!r} has not been scraped yet", file=sys.stderr)
            return 1

        funds = storage.list_stale_funds(session, source)
        for fund in funds:
            print(
                f"{format_amount(fund.amount):>14}  last seen {fund.last_seen_at:%Y-%m-%d}  "
                f"{fund.parcel_id or '':<16}  {fund.owner_name or ''}"
            )
    print(f"{len(funds)} stale funds")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="surplus-funds", description="Surplus funds aggregator")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    sources = commands.add_parser("sources", help="list configured sources")
    sources.set_defaults(handler=cmd_sources)

    scrape = commands.add_parser("scrape", help="download, parse and store a list")
    scrape.add_argument("key", choices=SOURCES, help="source key from registry.py")
    scrape.add_argument("--file", type=Path, help="parse a local file instead of downloading")
    scrape.set_defaults(handler=cmd_scrape)

    funds = commands.add_parser("funds", help="search stored funds, largest first")
    funds.add_argument("--source", help="source key, e.g. ga_hall")
    funds.add_argument("--state")
    funds.add_argument("--county")
    funds.add_argument("--owner", help="partial, case-insensitive match")
    funds.add_argument("--parcel")
    funds.add_argument("--min-amount", type=Decimal)
    funds.add_argument("--max-amount", type=Decimal)
    funds.add_argument("--limit", type=int, default=20)
    funds.set_defaults(handler=cmd_funds)

    stale = commands.add_parser("stale", help="funds missing from the latest list")
    stale.add_argument("key", help="source key, e.g. ga_hall")
    stale.set_defaults(handler=cmd_stale)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
