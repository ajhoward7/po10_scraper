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
    track, road, xc = [], [], []

    for idx, event_code in event_keys.items():
        event_bests = _parse_event_bests(script, idx, event_code)
        category = _categorise_event(event_code)
        if category == "road":
            road.append(event_bests)
        elif category == "xc":
            xc.append(event_bests)
        else:
            track.append(event_bests)

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

def _parse_event_bests(script: str, idx: int, event_code: str) -> EventBests:
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
