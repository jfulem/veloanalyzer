from dataclasses import dataclass, field
from typing import Optional

from .config import FLAG


@dataclass
class Rider:
    first_name: str
    last_name: str
    country: str = ""
    uci_id: str = ""
    team: str = ""
    category: str = ""
    birth_year: str = ""
    start_nr: str = ""
    uci_rank: Optional[int] = None
    uci_points: Optional[int] = None
    match_confidence: int = 100  # 100 = exact match, <100 = fuzzy match %
    corrected_name: str = ""    # set when fuzzy match reveals a non-diacritic typo
    xcodata_slug: str = ""
    race_results: list = field(default_factory=list)  # [{race_id, race_name, date, location, rank, cat}]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def flag(self):
        return FLAG.get(self.country, "  ")
