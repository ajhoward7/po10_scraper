from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Performance:
    event: str
    value_raw: int           # centiseconds (time events) or centimetres (field events)
    value_display: str       # human-readable: "3:52.49", "32:14", "6.85"
    date: str                # raw "DD/MM/YYYY" string from the site
    meeting: str
    venue: str
    position: Optional[int]  # finishing position, nullable
    age_group: str           # "Senior", "Under 20", "V40", etc.
    indoor: bool
    results_url: Optional[str] = None   # https://www.powerof10.uk/Home/Results/{mtid}
    handicap: Optional[float] = None    # athlete's handicap after this performance (road/XC only)


@dataclass
class EventBests:
    event_code: str          # "1500", "5K Road", "XC", "HJ", etc.
    format_type: str         # "MinSecCs", "SecCs", "MetreCm", "Metres", etc.
    all_results: list[Performance] = field(default_factory=list)


@dataclass
class Athlete:
    guid: str
    first_name: str
    last_name: str
    sex: str                 # "Men" or "Women"
    track_events: list[EventBests] = field(default_factory=list)
    road_events: list[EventBests] = field(default_factory=list)
    xc_events: list[EventBests] = field(default_factory=list)
