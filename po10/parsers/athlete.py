"""
Parse a Power of 10 athlete profile page (SSR HTML) into an Athlete object.

All performance data is embedded in an inline <script> block as JS variable
assignments. We extract it with regex and json.loads rather than executing JS.

Key variables per event index N:
    evntKeys.set(N, 'EVENT_CODE')
    var dataRpValues{N}     = [int, ...]          centiseconds or centimetres
    var dataRpMeetDates{N}  = ['DD/MM/YYYY', ...]
    var dataRpMeetings{N}   = ['Meeting name', ...]
    var dataRpLocations{N}  = ['Venue', ...]
    var dataRpPositions{N}  = ['1', '3', ...]  or [null, ...]
    var dataRpAgeGroups{N}  = ['Senior', 'U20', ...]
    var dataRpIndoors{N}    = ['0', '1', ...]
    var dataFormatToUse{N}  = 'MinSecCs'           scalar string (NOT an array)

Format types and their value units:
    SecCs     → value in centiseconds, display as SS.cc
    MinSecCs  → value in centiseconds, display as M:SS.cc
    MinSec    → value in centiseconds, display as M:SS  (no centiseconds)
    HrMinSec  → value in seconds,      display as H:MM:SS or MM:SS
    MetreCm   → value in centimetres,  display as M.cc
    Metres    → value in whole metres

JS quirks handled:
    - Single-quoted strings (['value']) are not valid JSON → converted to double quotes
    - Sparse arrays ([a,,b]) are not valid JSON → null-patched before parsing
"""

from __future__ import annotations

import json
import re
from datetime import date as _date
from typing import Optional

from bs4 import BeautifulSoup

from ..models import Athlete, EventBests, Performance

# Road and XC event keywords used to categorise events
_ROAD_KEYWORDS = {
    "road", "mile", "5k", "10k", "10m", "hm", "halfmar", "mar",
    "5mile", "10mile", "parkrun", "ukr", "half_marathon", "marathon",
}
_XC_KEYWORDS = {"xc", "cross"}


def parse_athlete_page(html: str, guid: str) -> Athlete:
    soup = BeautifulSoup(html, "html.parser")

    first_name, last_name, sex = _parse_metadata(soup)
    script = _find_data_script(html)

    if not script:
        return Athlete(
            guid=guid,
            first_name=first_name,
            last_name=last_name,
            sex=sex,
        )

    event_keys = _parse_event_keys(script)
    links_lookup = _parse_griddata_links(html)
    track, road, xc = [], [], []

    for idx, event_code in event_keys.items():
        event_bests = _parse_event_bests(script, idx, event_code, links_lookup)
        category = _categorise_event(event_code)
        if category == "road":
            road.append(event_bests)
        elif category == "xc":
            xc.append(event_bests)
        else:
            track.append(event_bests)

    # Add any performances present in gridData but absent from dataRpValues
    # (covers parkruns, XC races, relays, and other events missing from evntKeys)
    track, road, xc = _supplement_from_griddata(html, track, road, xc, links_lookup)

    return Athlete(
        guid=guid,
        first_name=first_name,
        last_name=last_name,
        sex=sex,
        track_events=track,
        road_events=road,
        xc_events=xc,
    )


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def _parse_metadata(soup: BeautifulSoup) -> tuple[str, str, str]:
    first_name = ""
    last_name = ""
    sex = ""

    for sel in ("h1.athlete-name", "h1", ".athlete-firstname", ".ath-name"):
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            parts = text.split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])
            elif parts:
                last_name = parts[0]
            break

    for label_text in ("SEX", "Sex", "Gender"):
        label = soup.find(string=re.compile(rf"\b{label_text}\b", re.I))
        if label and label.parent:
            sibling = label.parent.find_next_sibling()
            if sibling:
                val = sibling.get_text(strip=True).lower()
                if "wom" in val or val == "f" or val == "female":
                    sex = "Women"
                elif "men" in val or val == "m" or val == "male":
                    sex = "Men"
                break

    if not sex:
        for tag in soup.find_all(string=re.compile(r"\b(Men|Women)\b")):
            t = tag.strip()
            if t in ("Men", "Women"):
                sex = t
                break

    return first_name, last_name, sex


# ---------------------------------------------------------------------------
# Script block extraction
# ---------------------------------------------------------------------------

def _find_data_script(html: str) -> str:
    match = re.search(
        r"<script[^>]*>(.*?evntKeys\.set\(.*?)</script>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _parse_event_keys(script: str) -> dict[int, str]:
    return {
        int(idx): name
        for idx, name in re.findall(r"evntKeys\.set\((\d+),\s*'([^']+)'\)", script)
    }


_MONTH_ABBR: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_BASE_RESULTS_URL = "https://www.powerof10.uk/Home/Results/"


def _parse_griddata_links(html: str) -> dict[tuple[int, int], str]:
    """
    Extract (day, month) → results URL from the inline gridData JSON.

    gridData is a JS variable present on all modern PO10 athlete pages.
    Each performance entry carries a 'mtid' (meeting ID) and 'dte' ("16 Mar").
    The full results URL is baseResultsUrl with the mtid substituted in.
    """
    m = re.search(r"let\s+gridData\s*=\s*(\{.*?\});\s*\n", html, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}

    links: dict[tuple[int, int], str] = {}
    dictpgs = data.get("perfs", {}).get("dictpgs", {})
    for cat_data in dictpgs.values():
        for pg in cat_data.get("pgs", []):
            for r in pg.get("results", []):
                mtid = r.get("mtid", "")
                dte  = r.get("dte", "")   # e.g. "16 Mar"
                if not mtid or not dte:
                    continue
                parts = dte.strip().split()
                if len(parts) == 2:
                    try:
                        day   = int(parts[0])
                        month = _MONTH_ABBR.get(parts[1].lower(), 0)
                        if day and month:
                            links[(day, month)] = mtid
                    except (ValueError, IndexError):
                        pass
    return links


def _norm_event(event_code: str) -> str:
    """Normalise an event code for deduplication: lowercase, spaces → underscores."""
    return event_code.lower().replace(" ", "_")


def _infer_date(day: int, month: int, yr: int) -> Optional[str]:
    """
    Return DD/MM/YYYY for a gridData (day, month, season-year) triple.

    gridData 'dte' is "16 Mar" with no year. If the date with the season year
    is in the future, the performance must be from the previous calendar year.
    """
    today = _date.today()
    try:
        d = _date(yr, month, day)
        if d > today:
            d = _date(yr - 1, month, day)
        return f"{day:02d}/{month:02d}/{d.year}"
    except ValueError:
        return None


def _supplement_from_griddata(
    html: str,
    track: list[EventBests],
    road: list[EventBests],
    xc: list[EventBests],
    links_lookup: dict[tuple[int, int], str],
) -> tuple[list[EventBests], list[EventBests], list[EventBests]]:
    """
    Supplement the dataRpValues parse with any performances only present in gridData.

    PO10's dataRpValues arrays only exist for events where an athlete has an
    established history (with a named evntKey entry). Parkruns, XC races with
    varied distances, relays, and field events often appear exclusively in
    gridData. This function adds those missing performances.
    """
    m = re.search(r"let\s+gridData\s*=\s*(\{.*?\});\s*\n", html, re.DOTALL)
    if not m:
        return track, road, xc
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return track, road, xc

    yr = data.get("perfs", {}).get("yr", _date.today().year)

    # Build a dedup set of already-parsed performances: (date, norm_event, perf_display)
    all_existing = track + road + xc
    known: set[tuple[str, str, str]] = {
        (r.date, _norm_event(r.event), r.value_display)
        for eb in all_existing
        for r in eb.all_results
    }

    # Index existing EventBests by normalised event code for O(1) append
    event_index: dict[str, EventBests] = {
        _norm_event(eb.event_code): eb for eb in all_existing
    }

    dictpgs = data.get("perfs", {}).get("dictpgs", {})
    for cat_data in dictpgs.values():
        for pg in cat_data.get("pgs", []):
            for r in pg.get("results", []):
                event_code   = r.get("evnt", "").strip()
                perf_display = r.get("perf", "").strip()

                if not event_code or not perf_display:
                    continue
                if perf_display.upper() in ("DNS", "DNF", "DQ", "NH", "NM"):
                    continue

                dte   = r.get("dte", "")
                parts = dte.strip().split()
                if len(parts) != 2:
                    continue
                try:
                    day   = int(parts[0])
                    month = _MONTH_ABBR.get(parts[1].lower(), 0)
                    if not (day and month):
                        continue
                except (ValueError, IndexError):
                    continue

                date_str = _infer_date(day, month, yr)
                if date_str is None:
                    continue

                key = (date_str, _norm_event(event_code), perf_display)
                if key in known:
                    continue
                known.add(key)

                mtid        = r.get("mtid", "")
                results_url = (_BASE_RESULTS_URL + mtid) if mtid else None

                perf = Performance(
                    event=event_code,
                    value_raw=0,          # gridData has display string only
                    value_display=perf_display,
                    date=date_str,
                    meeting=r.get("mtn", ""),
                    venue=r.get("venn", ""),
                    position=_safe_int(r.get("pos") or None),
                    age_group=r.get("ag", ""),
                    indoor=False,
                    results_url=results_url,
                )

                norm = _norm_event(event_code)
                if norm in event_index:
                    event_index[norm].all_results.append(perf)
                else:
                    eb = EventBests(event_code=event_code, format_type="", all_results=[perf])
                    event_index[norm] = eb
                    category = _categorise_event(event_code)
                    if category == "road":
                        road.append(eb)
                    elif category == "xc":
                        xc.append(eb)
                    else:
                        track.append(eb)

    return track, road, xc


# ---------------------------------------------------------------------------
# JS value extraction
# ---------------------------------------------------------------------------

def _extract_js_array(script: str, var_name: str) -> list:
    """
    Extract a JS array variable and return it as a Python list.

    Handles two JS quirks not valid in JSON:
      1. Single-quoted strings: ['value'] → ["value"]
      2. Sparse arrays: [a,,b] → [a, null, b]
    """
    pattern = rf"var\s+{re.escape(var_name)}\s*=\s*(\[.*?\]);"
    match = re.search(pattern, script, re.DOTALL)
    if not match:
        return []
    raw = match.group(1)

    # Patch JS sparse arrays (must come before quote conversion)
    raw = re.sub(r",\s*,", ", null,", raw)
    raw = re.sub(r",\s*\]", ", null]", raw)

    # Convert JS single-quoted strings to JSON double-quoted strings.
    # Handles escaped single quotes (\') inside strings.
    if "'" in raw:
        raw = re.sub(r"'((?:[^'\\]|\\.)*)'", r'"\1"', raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _extract_js_string(script: str, var_name: str) -> str:
    """
    Extract a scalar JS string variable: var name = 'value';
    Returns empty string if not found.
    """
    match = re.search(
        rf"var\s+{re.escape(var_name)}\s*=\s*'([^']*)'",
        script,
    )
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------

def _format_value(value: int, fmt: str) -> str:
    """Convert a raw numeric value to a human-readable performance string."""
    if fmt == "MinSecCs":
        # Value in centiseconds → M:SS.cc
        mins = value // 6000
        secs = (value % 6000) // 100
        cs = value % 100
        return f"{mins}:{secs:02d}.{cs:02d}" if mins else f"{secs}.{cs:02d}"

    elif fmt == "MinSec":
        # Value in centiseconds → M:SS (road races: 10K, 5K, etc.)
        mins = value // 6000
        secs = (value % 6000) // 100
        return f"{mins}:{secs:02d}" if mins else f"{secs}"

    elif fmt == "HrMinSec":
        # Value in whole seconds → H:MM:SS (marathons, half marathons)
        hrs = value // 3600
        mins = (value % 3600) // 60
        secs = value % 60
        if hrs:
            return f"{hrs}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    elif fmt == "SecCs":
        # Value in centiseconds → SS.cc (sprints, field events)
        return f"{value // 100}.{value % 100:02d}"

    elif fmt == "MetreCm":
        # Value in centimetres → M.cc (jumps, throws)
        return f"{value // 100}.{value % 100:02d}"

    elif fmt == "Metres":
        return str(value)

    else:
        return str(value)


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Event bests construction
# ---------------------------------------------------------------------------

def _parse_event_bests(
    script: str,
    idx: int,
    event_code: str,
    links_lookup: Optional[dict[tuple[int, int], str]] = None,
) -> EventBests:
    # dataFormatToUse{N} is a scalar string, not an array
    fmt = _extract_js_string(script, f"dataFormatToUse{idx}") or "SecCs"

    rp_values    = _extract_js_array(script, f"dataRpValues{idx}")
    rp_dates     = _extract_js_array(script, f"dataRpMeetDates{idx}")
    rp_meetings  = _extract_js_array(script, f"dataRpMeetings{idx}")
    rp_locations = _extract_js_array(script, f"dataRpLocations{idx}")
    rp_positions = _extract_js_array(script, f"dataRpPositions{idx}")
    rp_age_groups= _extract_js_array(script, f"dataRpAgeGroups{idx}")
    rp_indoors   = _extract_js_array(script, f"dataRpIndoors{idx}")

    def _get(lst: list, i: int, default=""):
        return lst[i] if i < len(lst) and lst[i] is not None else default

    results: list[Performance] = []
    for i, val in enumerate(rp_values):
        if val is None:
            continue

        indoor_val = _get(rp_indoors, i, "0")
        try:
            indoor = bool(int(indoor_val))
        except (ValueError, TypeError):
            indoor = False

        # Look up results URL via (day, month) key from gridData
        results_url: Optional[str] = None
        if links_lookup:
            date_str = _get(rp_dates, i)
            if len(date_str) == 10:
                try:
                    day   = int(date_str[:2])
                    month = int(date_str[3:5])
                    mtid  = links_lookup.get((day, month))
                    if mtid:
                        results_url = _BASE_RESULTS_URL + mtid
                except ValueError:
                    pass

        results.append(
            Performance(
                event=event_code,
                value_raw=val,
                value_display=_format_value(val, fmt),
                date=_get(rp_dates, i),
                meeting=_get(rp_meetings, i),
                venue=_get(rp_locations, i),
                position=_safe_int(_get(rp_positions, i, None)),
                age_group=_get(rp_age_groups, i),
                indoor=indoor,
                results_url=results_url,
            )
        )

    return EventBests(
        event_code=event_code,
        format_type=fmt,
        all_results=results,
    )


# ---------------------------------------------------------------------------
# Event categorisation
# ---------------------------------------------------------------------------

def _categorise_event(event_code: str) -> str:
    lower = event_code.lower()
    for kw in _XC_KEYWORDS:
        if kw in lower:
            return "xc"
    for kw in _ROAD_KEYWORDS:
        if kw in lower:
            return "road"
    return "track"
