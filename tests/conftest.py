import os
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HALL_PDF = PROJECT_ROOT / "Website-Excess-Funds-List-09-29-2023.pdf"


@pytest.fixture
def hall_pdf() -> bytes:
    """The Hall County list stored in the repo, so tests don't need the network."""
    return HALL_PDF.read_bytes()


@pytest.fixture
def session():
    """A database session whose changes are rolled back after the test.

    Requires the PostgreSQL container (docker compose up -d) and applied
    migrations (alembic upgrade head); the test is skipped otherwise.
    """
    from surplus_funds.db import engine

    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.fail(f"PostgreSQL is not available (docker compose up -d): {exc}", pytrace=False)

    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()
