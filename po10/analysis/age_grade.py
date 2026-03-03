"""
Age-grade scoring using WMA (World Masters Athletics) factors.

Score of 100 = world-record standard for that age/sex/event.

Two scores are computed per row:

  age_grade         — adjusted for the athlete's age bracket (e.g. M50 gets
                      a bonus vs open standard).  Uses 2023 WMA factors where
                      available (masters ages 30+), otherwise 2015 factors.

  senior_age_grade  — the same performance measured against the senior/open
                      WMA standard (factor = 1.0).  Shows absolute quality
                      regardless of age.

Data source
-----------
Cached in data/age_grade_tables.json, built by scripts/build_age_grade_cache.py.
Primary factor data: Howard Grubb's WMA calculators
  • 2015 T&F factors + all open-WR standards: wmalookup15.html (ages 5–100)
  • 2023 T&F factors for track/road events:   wmatnf23.html   (ages 30–110)

Limitations
-----------
- Age uses bottom of bracket (M40 → 40); actual age may be up to 4 years
  higher, giving a slightly lower age_grade than reality.
- Field events (High Jump, Discus, Shot, etc.) → null (formula differs).
- "Senior" age group → age 30 assumed (factor ≈ 1.0 for most events).
- XC events use nominal road-equivalent distances (8 km for standard XC).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import polars as pl

# ---------------------------------------------------------------------------
# Load cache
# ---------------------------------------------------------------------------

_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "age_grade_tables.json"

def _load_cache() -> dict:
    import json
    if not _CACHE_PATH.exists():
        raise FileNotFoundError(
            f"Age-grading cache not found at {_CACHE_PATH}.\n"
            "Run: python scripts/build_age_grade_cache.py"
        )
    return json.loads(_CACHE_PATH.read_text())

_CACHE: dict = _load_cache()

# ---------------------------------------------------------------------------
# Event mapping: PO10 event code → cache key
# ---------------------------------------------------------------------------

# Track events use the track (non-road) WR standard.
# Road events use the road WR standard (slightly slower than track).
_EVENT_MAP: dict[str, str] = {
    # ── Track sprints / middle / long ──────────────────────────────────────
    "100":         "100m",
    "200":         "200m",
    "300":         "300m",
    "400":         "400m",
    "500":         "500m",
    "600":         "600m",
    "800":         "800m",
    "1000":        "1000m",
    "1500":        "1500m",
    "Mile":        "1Mile",
    "1M":          "1Mile",
    "2000":        "2km",
    "3000":        "3km",
    "2Mile":       "2Mile",
    "5000":        "5km",         # track 5 000 m standard (757 s)
    "10000":       "10km",        # track 10 000 m standard (1580 s)
    # ── Track hurdles / steeplechase ───────────────────────────────────────
    "60H":         "60Hur",
    "100H":        "ShortHur",    # women's 100 m hurdles
    "110H":        "ShortHur",    # men's 110 m hurdles
    "400H":        "LongHur",
    "400_Hurdles": "LongHur",
    "3000SC":      "Steeple",
    # ── Road events ────────────────────────────────────────────────────────
    "5K":          "5kmRoad",     # road 5 K standard (779 s)
    "4M":          "4MileRoad",
    "5M":          "5MileRoad",
    "10K":         "10kmRoad",    # road 10 K standard (1603 s)
    "15K":         "15km",
    "10M":         "10Mile",
    "20K":         "20km",
    "20M":         "25km",        # 20 miles ≈ 32 km; nearest table entry is 25 km
    "Half_Marathon": "Half.Mar",
    "Marathon":    "Marathon",
    # ── Cross-country (road-equivalent approximations) ─────────────────────
    "XC":          "8kmRoad",     # ≈ 8 km road
    "XC Short":    "5kmRoad",     # ≈ 5 km road (4 km XC not in tables)
    # ── Walks ──────────────────────────────────────────────────────────────
    "3000W":       "3kmWalk",
    "5000W":       "5kmWalk",
    "10000W":      "10kmWalk",
    "20000W":      "20kmWalk",
    "10KW":        "10kmWalk",
    "20KW":        "20kmWalk",
}

# ---------------------------------------------------------------------------
# Factor lookup
# ---------------------------------------------------------------------------

def _get_entry(event: str, gender: str) -> Optional[dict]:
    """Return cache entry for event + gender, or None if unsupported."""
    key = _EVENT_MAP.get(event)
    if key is None:
        return None
    g = "M" if gender == "Men" else "F"
    return _CACHE.get(g, {}).get(key)


def _factor(entry: dict, age: int) -> float:
    """
    Return the WMA factor for *age*.

    Preference order:
      1. 2023 factors if age is within their range (30–110)
      2. 2015 factors, clamped to available range (5–100)
    """
    f23 = entry.get("factors_2023")
    if f23 is not None:
        start23 = f23["age_start"]          # 30
        vals23  = f23["values"]             # 81 values
        end23   = start23 + len(vals23) - 1  # 110
        if start23 <= age <= end23:
            return vals23[age - start23]

    # Fall back to 2015 factors
    start15 = entry["age_start"]            # 5
    vals15  = entry["factors_2015"]         # 96 values
    idx = max(0, min(age - start15, len(vals15) - 1))
    return vals15[idx]

# ---------------------------------------------------------------------------
# Performance string → seconds
# ---------------------------------------------------------------------------

def parse_performance_to_seconds(performance: str) -> Optional[float]:
    """
    Parse a PO10 performance string to total seconds.

    Formats:
      SS or SS.cc     → "10.90"     →  10.90
      M:SS or M:SS.cc → "4:35.78"  → 275.78
      H:MM:SS         → "1:26:38"  → 5198.0
    """
    if not performance:
        return None
    parts = performance.strip().split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        return None
    return None

# ---------------------------------------------------------------------------
# Age group → integer age (bottom of bracket)
# ---------------------------------------------------------------------------

def age_group_to_years(age_group: str) -> Optional[int]:
    """
    Return the bottom age for the bracket.

      "Senior"      → 30  (prime age; factor ≈ 1.0)
      "Under 20"    → 19
      "Under 23"    → 22
      "M40", "W40"  → 40
      "Veteran 40"  → 40
      ""            → None
    """
    if not age_group:
        return None
    ag = age_group.strip()
    if ag.lower() == "senior":
        return 30
    m = re.match(r"[Uu]nder\s+(\d+)", ag)
    if m:
        return int(m.group(1)) - 1
    m = re.search(r"\d+", ag)
    if m:
        return int(m.group())
    return None

# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _grade(open_wr: float, factor: float, perf_secs: float) -> Optional[float]:
    """age_grade = 100 × open_WR / (factor × perf_secs), capped at 100."""
    if factor <= 0 or perf_secs <= 0:
        return None
    return round(min(100.0 * open_wr / (factor * perf_secs), 100.0), 2)


def compute_grades(
    performance: str,
    event: str,
    age_group: str,
    sex: str,
) -> tuple[Optional[float], Optional[float]]:
    """
    Return (age_grade, senior_age_grade) for a single performance row.

    age_grade         — WMA age-adjusted score (uses athlete's age bracket).
    senior_age_grade  — open/senior score (factor = 1.0, absolute quality).

    Both are None when the event is unsupported (field events, unknown codes).
    """
    secs  = parse_performance_to_seconds(performance)
    entry = _get_entry(event, sex)
    age   = age_group_to_years(age_group)

    if secs is None or secs <= 0 or entry is None:
        return None, None

    open_wr = entry["open_wr"]

    # Senior / open grade — factor 1.0 (no age adjustment)
    senior = _grade(open_wr, 1.0, secs)

    # Age-adjusted grade
    if age is None:
        age_gr = None
    else:
        factor = _factor(entry, age)
        age_gr = _grade(open_wr, factor, secs)

    return age_gr, senior

# ---------------------------------------------------------------------------
# DataFrame helper
# ---------------------------------------------------------------------------

def add_age_grades(df: pl.DataFrame) -> pl.DataFrame:
    """
    Append *age_grade* and *senior_age_grade* (Float32) columns to *df*.

    age_grade         — WMA age-adjusted score for the athlete's age bracket.
    senior_age_grade  — same performance scored against the open/senior standard.
    """
    age_grades:    list[Optional[float]] = []
    senior_grades: list[Optional[float]] = []

    for row in df.iter_rows(named=True):
        ag, sr = compute_grades(
            row["performance"],
            row["event"],
            row["age_group"],
            row["sex"],
        )
        age_grades.append(ag)
        senior_grades.append(sr)

    return df.with_columns([
        pl.Series("age_grade",        age_grades,    dtype=pl.Float32),
        pl.Series("senior_age_grade", senior_grades, dtype=pl.Float32),
    ])
