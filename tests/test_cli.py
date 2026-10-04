from dataclasses import replace
from pathlib import Path

import pytest
import requests
from sqlalchemy import func, update

from surplus_funds import cli, db
from surplus_funds.models import SurplusFund
from surplus_funds.sources import SOURCES, SourceConfig

HALL_PDF = Path(__file__).resolve().parent.parent / "Website-Excess-Funds-List-09-29-2023.pdf"

# Separate keys so the tests never touch a real "ga_hall" source.
HALL = replace(SOURCES["ga_hall"], key="test_ga_hall")
EMPTY = SourceConfig(key="test_empty", state="GA", county="Empty", url="https://example.com", file_format="html")


@pytest.fixture
def run(session, monkeypatch, capsys):
    """Run the CLI against the rolled-back test session; returns (exit code, stdout, stderr)."""
    monkeypatch.setattr(db, "SessionLocal", lambda: session)
    monkeypatch.setattr(cli, "SOURCES", {HALL.key: HALL, EMPTY.key: EMPTY})

    def run_cli(*args: str) -> tuple[int, str, str]:
        code = cli.main([str(arg) for arg in args])
        out, err = capsys.readouterr()
        return code, out, err

    return run_cli


@pytest.fixture
def scraped(run):
    """The CLI runner, with the Hall County list already imported."""
    code, _, _ = run("scrape", HALL.key, "--file", HALL_PDF)
    assert code == 0
    return run


def test_sources(monkeypatch, capsys):
    # Works without a database.
    monkeypatch.setattr(cli, "SOURCES", {HALL.key: HALL})
    assert cli.main(["sources"]) == 0
    out = capsys.readouterr().out
    assert "test_ga_hall" in out
    assert "Hall" in out


def test_unknown_source_key_is_rejected(run):
    with pytest.raises(SystemExit):
        run("scrape", "nonexistent")


# ---------------------------------------------------------------------------
# scrape
# ---------------------------------------------------------------------------


def test_scrape_local_file(run):
    code, out, _ = run("scrape", HALL.key, "--file", HALL_PDF)
    assert code == 0
    assert "test_ga_hall: 73 records imported, 73 in database, 0 stale" in out


def test_scrape_twice_does_not_duplicate(scraped):
    code, out, _ = scraped("scrape", HALL.key, "--file", HALL_PDF)
    assert code == 0
    assert "73 in database" in out


def test_scrape_downloads_without_file(run, monkeypatch):
    urls = []

    def fake_download(url):
        urls.append(url)
        return HALL_PDF.read_bytes()

    monkeypatch.setattr(cli, "download", fake_download)
    code, out, _ = run("scrape", HALL.key)
    assert code == 0
    assert urls == [HALL.url]
    assert "73 records imported" in out


def test_scrape_download_error(run, monkeypatch):
    def failing_download(url):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(cli, "download", failing_download)
    code, _, err = run("scrape", HALL.key)
    assert code == 1
    assert "error: no network" in err


def test_scrape_missing_file(run, tmp_path):
    code, _, err = run("scrape", HALL.key, "--file", tmp_path / "missing.pdf")
    assert code == 1
    assert err.startswith("error:")


def test_scrape_empty_list_writes_nothing(run, tmp_path):
    page = tmp_path / "empty.html"
    page.write_text("<table><tr><th>Parcel</th><th>Sale Date</th><th>Amount</th></tr></table>")

    code, _, err = run("scrape", EMPTY.key, "--file", page)
    assert code == 1
    assert "no records found, nothing was written" in err


# ---------------------------------------------------------------------------
# funds
# ---------------------------------------------------------------------------


def test_funds(scraped):
    code, out, _ = scraped("funds", "--source", HALL.key, "--limit", 5)
    lines = out.splitlines()
    assert code == 0
    assert len(lines) == 6  # 5 funds + summary
    assert "$155,318.89" in lines[0]  # largest first
    assert lines[-1] == "showing 5 of 73"


def test_funds_filters(scraped):
    code, out, _ = scraped("funds", "--source", HALL.key, "--owner", "newcomb")
    assert code == 0
    assert "15025A000047" in out
    assert out.splitlines()[-1] == "showing 1 of 1"


def test_funds_unknown_source(run):
    code, _, err = run("funds", "--source", "nonexistent")
    assert code == 1
    assert "has not been scraped yet" in err


# ---------------------------------------------------------------------------
# stale
# ---------------------------------------------------------------------------


def test_stale_none_after_fresh_scrape(scraped):
    code, out, _ = scraped("stale", HALL.key)
    assert code == 0
    assert out.strip() == "0 stale funds"


def test_stale_lists_funds_missing_from_latest_list(scraped, session):
    # now() is fixed within a transaction, so pretend one fund was last seen a day earlier.
    session.execute(
        update(SurplusFund)
        .where(SurplusFund.external_id == "15025A000047|2016-11-25")
        .values(last_seen_at=func.now() - func.make_interval(0, 0, 0, 1))
    )

    code, out, _ = scraped("stale", HALL.key)
    assert code == 0
    assert "15025A000047" in out
    assert out.splitlines()[-1] == "1 stale funds"


def test_stale_unknown_source(run):
    code, _, err = run("stale", "nonexistent")
    assert code == 1
    assert "has not been scraped yet" in err


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["funds.xlsx", "funds.csv", "funds.html"])
def test_export(scraped, tmp_path, name):
    path = tmp_path / name
    code, out, _ = scraped("export", path, "--source", HALL.key)
    assert code == 0
    assert path.stat().st_size > 0
    assert "73 funds exported" in out


def test_export_with_filters(scraped, tmp_path):
    code, out, _ = scraped("export", tmp_path / "big.csv", "--source", HALL.key, "--min-amount", "10000")
    assert code == 0
    assert "18 funds exported" in out


def test_export_unsupported_extension(run, tmp_path):
    code, _, err = run("export", tmp_path / "funds.pdf")
    assert code == 1
    assert "unsupported file type '.pdf'" in err


def test_export_unknown_source(run, tmp_path):
    code, _, err = run("export", tmp_path / "funds.csv", "--source", "nonexistent")
    assert code == 1
    assert "has not been scraped yet" in err


def test_export_file_open_in_excel(scraped, tmp_path, monkeypatch):
    def locked(funds, path):
        raise PermissionError(path)

    monkeypatch.setattr("surplus_funds.export.export_funds", locked)
    code, _, err = scraped("export", tmp_path / "funds.xlsx", "--source", HALL.key)
    assert code == 1
    assert "is it open in Excel?" in err
