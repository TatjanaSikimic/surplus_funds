"""Source configurations and the universal PDF/HTML parsers."""

from surplus_funds.sources.config import SourceConfig
from surplus_funds.sources.parsers import HtmlParser, PdfParser, get_parser
from surplus_funds.sources.registry import SOURCES

__all__ = ["SOURCES", "HtmlParser", "PdfParser", "SourceConfig", "get_parser"]
