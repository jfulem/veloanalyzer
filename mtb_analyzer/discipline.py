"""Per-discipline configuration.

The project began as MTB cross-country only, and the identifiers still say so
(`xco_race_id`, `uci_xco_race_results`, `build_uci_xco_history`). Those names
now mean "a UCI competition result" generically, for whichever discipline is
passed — renaming them would churn the database, the read API and the whole
frontend for no behavioural gain.

Everything that genuinely differs between MTB XCO and cyclo-cross lives here:
the UCI's own identifiers for the discipline, how a season maps onto a year,
which domestic-cup standings page to read, and how ranking points accumulate.
"""

from dataclasses import dataclass, field
from datetime import datetime

XCO = "XCO"
CX  = "CX"


@dataclass(frozen=True)
class Discipline:
    code: str
    label: str

    # dataride.uci.ch — the official ranking feed.
    dataride_discipline_id: int
    # RaceTypeId filter for the ranking query. MTB needs it (one discipline
    # carries XCO, XCM, DHI... rankings); cyclo-cross rankings carry
    # RaceTypeId 0, so 0 means "send no race-type filter at all".
    dataride_race_type_id: int

    # www.uci.org — the calendar/results API and the competition-details page.
    # `calendar_discipline` is both the ?discipline= value and the path
    # segment in /competition-details/{year}/{DISC}/{id}.
    calendar_discipline: str
    calendar_race_type: str | None

    # True when a season spans a new year (cyclo-cross runs Aug → Feb and the
    # UCI labels that whole span with the *later* year). Drives season_year().
    season_spans_years: bool
    # First month of a cross-year season.
    season_start_month: int = 1

    # Category IDs in the Czech Cup standings form (sportsoft WebForms).
    cup_category_ids: dict = field(default_factory=dict)

    # UCI competition class codes that never count against a points quota.
    uncapped_classes: frozenset = frozenset()

    def season_year(self, when: datetime | None = None) -> int:
        """The UCI's label for the season containing `when`.

        For MTB this is just the calendar year. For cyclo-cross the 2026/27
        season — which starts in August 2026 — is the UCI's "2027", so both
        the calendar API and dataride want 2027 for any date from August on.
        """
        when = when or datetime.now()
        if self.season_spans_years and when.month >= self.season_start_month:
            return when.year + 1
        return when.year


DISCIPLINES: dict[str, Discipline] = {
    XCO: Discipline(
        code=XCO,
        label="MTB XCO",
        dataride_discipline_id=7,
        dataride_race_type_id=92,      # Cross-country Olympic
        calendar_discipline="MTB",
        calendar_race_type="XCO",
        season_spans_years=False,
        cup_category_ids={"MJ": "7", "WJ": "8", "ME": "9", "WE": "10"},
        # CM = World Champs, CDM = World Cup, CC = Continental Champs,
        # CN = National Champs (French abbreviations, as the UCI writes them).
        uncapped_classes=frozenset({"CM", "CDM", "CC", "CN"}),
    ),
    CX: Discipline(
        code=CX,
        label="Cyclo-cross",
        dataride_discipline_id=3,
        dataride_race_type_id=0,       # cyclo-cross rankings carry no race type
        calendar_discipline="CRO",
        calendar_race_type="CRO-IND",  # excludes the mixed team relay
        season_spans_years=True,
        season_start_month=8,
        # cpcx.sportsoft.cz has no Juniorky category: junior women are ranked
        # with the women, exactly as UCI art. C1025 ranks them.
        cup_category_ids={"MJ": "3", "WJ": "2", "ME": "1", "WE": "2"},
        uncapped_classes=frozenset({"CM", "CDM", "CC", "CN", "CMM"}),
    ),
}

DEFAULT_DISCIPLINE = XCO


def normalize(code: str | None) -> str:
    """Accept a races.yml `discipline:` value (any case) and return a known
    code, defaulting to XCO so every pre-existing entry keeps working."""
    key = (code or "").strip().upper()
    return key if key in DISCIPLINES else DEFAULT_DISCIPLINE


def get(code: str | None) -> Discipline:
    return DISCIPLINES[normalize(code)]
