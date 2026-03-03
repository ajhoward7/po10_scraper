#!/usr/bin/env python3
"""Fetch WMA age-grading tables from Howard Grubb's online calculators and
save them as a local JSON cache for offline use.

Sources
-------
T&F 2015  (standards + factors ages 5–100, all events):
    https://howardgrubb.co.uk/athletics/wmalookup15.html
T&F 2023  (factors ages 30–110 only, no standards):
    https://howardgrubb.co.uk/athletics/wmatnf23.html

The two datasets are merged per event: 2015 factors are stored for full age
coverage (5–100); where a 2023 equivalent exists the newer factors are stored
separately under "factors_2023" and will be preferred at runtime for masters
athletes (age 30+).

Field events (jumps, throws) are excluded — they use a different formula
(higher distance = better) and are not relevant to time-based running.

Output
------
data/age_grade_tables.json

Run once to populate; delete the file and re-run to refresh.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUT = DATA_DIR / "age_grade_tables.json"

TNF15_URL = "https://howardgrubb.co.uk/athletics/wmalookup15.html"
TNF23_URL = "https://howardgrubb.co.uk/athletics/wmatnf23.html"

# ---------------------------------------------------------------------------
# 2015 → 2023 event name mapping (None = no 2023 counterpart)
# ---------------------------------------------------------------------------

_NAME_2015_TO_2023: dict[str, str | None] = {
    # Sprints / track
    "50m":       None,
    "55m":       None,
    "60m":       "60m",
    "100m":      "100m",
    "200m":      "200m",
    "300m":      None,
    "400m":      "400m",
    "500m":      None,
    "600m":      None,
    "800m":      "800m",
    "1000m":     "1000m",
    "1500m":     "1500m",
    "1Mile":     "Mile",
    "2km":       None,
    "3km":       "3000m",
    "2Mile":     None,
    "4km":       None,
    "3Mile":     None,
    "5km":       "5000m",
    "6km":       None,
    "4Mile":     None,
    "8km":       None,
    "5Mile":     None,
    "10km":      "10000m",
    # Hurdles
    "50Hur":     None,
    "55Hur":     None,
    "60Hur":     "60mHurdles",
    "ShortHur":  "ShortHurdles",
    "LongHur":   "LongHurdles",
    # Steeplechase
    "Steeple":   "SteepleChase",
    # Road — 2023 page has HalfMarathon and Marathon
    "Half.Mar":  "HalfMarathon",
    "Marathon":  "Marathon",
    # Road — no 2023 equivalents for shorter road events
    "5kmRoad":   None,
    "6kmRoad":   None,
    "4MileRoad": None,
    "8kmRoad":   None,
    "5MileRoad": None,
    "10kmRoad":  None,
    "12km":      None,
    "15km":      None,
    "10Mile":    None,
    "20km":      None,
    "25km":      None,
    "30km":      None,
    "50km":      None,
    "50Mile":    None,
    "100km":     None,
    "150km":     None,
    "100Mile":   None,
    "200km":     None,
    # Walks
    "1500mWalk": None,
    "1MileWalk": None,
    "3kmWalk":   None,
    "5kmWalk":   None,
    "8kmWalk":   None,
    "10kmWalk":  "10kRaceWalk",
    "15kmWalk":  None,
    "20kmWalk":  "20kRaceWalk",
    "H.Mar.Walk": None,
    "25kmWalk":  None,
    "30kmWalk":  None,
    "40kmWalk":  None,
    "Mar.Walk":  None,
    "50kmWalk":  None,
}

# Field events use a different formula (distance, not time) — skip entirely
_FIELD_EVENTS = {
    "HighJump", "PoleVault", "LongJump", "TripleJump",
    "Hammer", "Shotput", "Discus", "Javelin", "Weight",
}

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Matches: new facrow("name", dist_km, open_wr_secs, f1, f2, ..., f96)
_FACROW_RE = re.compile(
    r'new\s+facrow\s*\(\s*"([^"]+)"\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.,\s]+?)\s*\)',
    re.DOTALL,
)


def _fetch(url: str) -> str:
    print(f"  Fetching {url} ...", flush=True)
    r = requests.get(url, timeout=30, headers=_HEADERS)
    r.raise_for_status()
    return r.text


def _parse_facrows_2015(html: str, var_prefix: str) -> dict[str, dict]:
    """
    Parse all facrow() entries associated with *var_prefix*
    (e.g. "WMA_15_M_facs") from a Howard Grubb 2015 page.

    Returns a dict keyed by event name.
    Each value: {open_wr, dist_km, age_start, factors_2015}
    """
    results: dict[str, dict] = {}
    for chunk in html.split(var_prefix):
        m = _FACROW_RE.search(chunk)  # search full chunk (~600 chars each)
        if not m:
            continue
        name = m.group(1)
        if name in results or name in _FIELD_EVENTS:
            continue
        factors = [float(x.strip()) for x in m.group(4).split(",") if x.strip()]
        if len(factors) != 96:
            continue  # sanity guard
        results[name] = {
            "open_wr": float(m.group(3)),
            "dist_km": float(m.group(2)),
            "age_start": 5,
            "factors_2015": factors,
        }
    return results


def _parse_factors_2023(html: str, gender_key: str) -> dict[str, list[float]]:
    """
    Parse WMA_M_facs / WMA_F_facs from the 2023 T&F page.
    Returns {event_2023_name: [f_age30, ..., f_age110]}  (81 values each)
    """
    prefix = f'WMA_{gender_key}_facs'
    results: dict[str, list[float]] = {}
    for m in re.finditer(
        rf'{re.escape(prefix)}\["([^"]+)"\]\s*=\s*\[([^\]]+)\]', html
    ):
        name = m.group(1)
        vals = [v.strip().strip('"') for v in m.group(2).split(",")]
        try:
            factors = [float(v) for v in vals[1:]]   # skip type code ("T1"/"T2"/"D2")
        except ValueError:
            continue
        if len(factors) == 81:
            results[name] = factors
    return results


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build_gender(
    html15: str,
    html23: str,
    prefix15_m: str,
    prefix15_f: str,
) -> tuple[dict, dict]:
    m_data = _parse_facrows_2015(html15, prefix15_m)
    f_data = _parse_facrows_2015(html15, prefix15_f)
    m_2023 = _parse_factors_2023(html23, "M")
    f_2023 = _parse_factors_2023(html23, "F")

    for name_15, name_23 in _NAME_2015_TO_2023.items():
        if name_23 is None:
            continue
        if name_15 in m_data and name_23 in m_2023:
            m_data[name_15]["factors_2023"] = {
                "age_start": 30,
                "values": m_2023[name_23],
            }
        if name_15 in f_data and name_23 in f_2023:
            f_data[name_15]["factors_2023"] = {
                "age_start": 30,
                "values": f_2023[name_23],
            }
    return m_data, f_data


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("Building WMA age-grading cache...")
    html15 = _fetch(TNF15_URL)
    html23 = _fetch(TNF23_URL)

    m_data, f_data = _build_gender(
        html15, html23,
        prefix15_m="WMA_15_M_facs",
        prefix15_f="WMA_15_W_facs",
    )

    cache = {"M": m_data, "F": f_data}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(cache, indent=2))
    print(f"\nWrote {OUTPUT}")

    # Summary
    for g, data in [("M", m_data), ("F", f_data)]:
        n23 = sum(1 for v in data.values() if "factors_2023" in v)
        print(f"  {g}: {len(data)} events total, {n23} with 2023 factors")

    # Sanity checks
    print("\nSanity checks (age_grade = 100 × wr / (factor × time)):")
    checks = [
        ("M", "1500m",  240.0, 40,  "M40 1500m 4:00"),
        ("M", "5km",    757.0, 40,  "M40 5km track 12:37"),
        ("M", "5kmRoad",779.0, 40,  "M40 5K road 12:59 (=100%)"),
        ("F", "Half.Mar", 3912.0, 50, "F50 HM 65:12 (=100%)"),
    ]
    for g, ev, time_s, age, label in checks:
        entry = cache[g].get(ev)
        if not entry:
            print(f"  {label}: event not found")
            continue
        # Use 2023 factors if available and age in range
        fac23 = entry.get("factors_2023")
        if fac23 and fac23["age_start"] <= age:
            factor = fac23["values"][age - fac23["age_start"]]
            src = "2023"
        else:
            idx = max(0, min(age - entry["age_start"], 95))
            factor = entry["factors_2015"][idx]
            src = "2015"
        ag = 100.0 * entry["open_wr"] / (factor * time_s)
        print(f"  {label}: factor={factor:.4f}({src}) → age_grade={ag:.2f}%")


if __name__ == "__main__":
    main()
