"""All supported sources. Adding a county means adding one SourceConfig here."""

from surplus_funds.sources.config import SourceConfig

SOURCE_CONFIGS = [
    SourceConfig(
        key="ga_hall",
        state="GA",
        county="Hall",
        agency="Tax Commissioner",
        # The file name changes with every update; check hallcountytax.org for the latest list.
        url="https://www.hallcountytax.org/wp-content/uploads/2023/09/Website-Excess-Funds-List-09-29-2023.pdf",
        file_format="pdf",
        # The header is printed above the table grid, so it's listed here explicitly.
        columns=(
            "TAX SALE DATE",
            "BUYER",
            "MAPCODE",
            "ORIGINAL OWNER",
            "PROPERTY ADDRESS",
            "CITY",
            "EXCESS FUNDS",
        ),
    ),
    # Template for a list whose header row is part of the table (most lists):
    #
    # SourceConfig(
    #     key="ga_example",
    #     state="GA",
    #     county="Example",
    #     agency="Tax Commissioner",
    #     url="https://...",
    #     file_format="pdf",   # or "html"
    # ),
]

SOURCES: dict[str, SourceConfig] = {config.key: config for config in SOURCE_CONFIGS}
