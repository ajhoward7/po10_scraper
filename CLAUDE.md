# CLAUDE.md — po10_scraper

Notes for Claude Code when working in this repository.

---

## Environment

Run all scripts from the repo root. Use whichever Python interpreter has the dependencies installed.

---

## Common commands

```bash
# Reprocess using cached athlete HTML (no browser, fast)
python scripts/fetch_club.py --guids-file data/thames_hare_hounds_guids.json

# Full scrape (requires Playwright + network)
python scripts/fetch_club.py --club "Thames Hare & Hounds"

# Rebuild WMA age-grading cache from Howard Grubb's web pages
python scripts/build_age_grade_cache.py

# Spot-check the output
python -c "
import polars as pl
df = pl.read_parquet('data/exports/thames_hare_hounds.parquet')
print(df.schema)
print(df.sort('age_grade', descending=True, nulls_last=True).head(20).select(
    ['first_name','last_name','event','performance','age_group','sex','age_grade','senior_age_grade']
))
print('Scored:', df['age_grade'].drop_nulls().len(), '/', len(df))
"
```

---

## Architecture

```
fetch_club.py
  → get_club_athlete_guids()   # Playwright: browser search on PO10
  → fetch_athletes()           # Async HTTP: fetch + parse athlete pages
  → build_dataframe()          # Flatten performances into rows
  → add_age_grades()           # Apply WMA age grading (reads local JSON cache)
  → export()                   # Write .parquet + .csv
```

The data pipeline is intentionally simple — no database, no ORM, just Polars DataFrames written to flat files.

---

## Data model

`po10/models.py` — core dataclasses:
- `Athlete` — name, sex, lists of `EventBests` (track / road / xc)
- `EventBests` — event name + list of `Performance`
- `Performance` — date, value_display, position, age_group

`po10/parsers/athlete.py` — parses a raw PO10 HTML page into an `Athlete`.

---

## Age grading (`po10/analysis/age_grade.py`)

Reads `data/age_grade_tables.json` at import time.

Key functions:
- `parse_performance_to_seconds(s)` — handles `"M:SS"`, `"M:SS.cc"`, `"H:MM:SS"`, `"SS.cc"`
- `age_group_to_years(ag)` — `"Senior"→30`, `"Under 20"→19`, `"M40"→40`, etc.
- `compute_grades(performance, event, age_group, sex)` → `(age_grade, senior_age_grade)`
- `add_age_grades(df)` → appends both columns to a Polars DataFrame

**Event mapping**: PO10 codes → WMA table keys (see `_EVENT_MAP` dict).
Key distinction: `"5K"` uses road standard (779 s), `"5000"` uses track standard (757 s).

**Factor precedence**: 2023 factors (ages 30–110) are preferred for track/road events where available; 2015 factors (ages 5–100) used otherwise.

---

## Caching

| Cache file | Purpose | Gitignored? |
|---|---|---|
| `data/athletes/<guid>.json` | Raw HTML per athlete | Yes (300+ files) |
| `data/*_guids.json` | Athlete GUIDs from last search | Yes |
| `data/age_grade_tables.json` | WMA factor tables | No |
| `data/exports/*.parquet` / `*.csv` | Output | Yes |

To force a fresh scrape of a specific athlete, delete their file in `data/athletes/`.

---

## Adding a new club

```bash
python scripts/fetch_club.py --club "Club Name Here"
```

The club name is used both for the PO10 search and to derive the output filename (e.g. `data/exports/club_name_here.parquet`).

---

## Dependencies

| Package | Purpose |
|---|---|
| `httpx` | Async HTTP client |
| `playwright` | Browser automation (club member search) |
| `beautifulsoup4` | HTML parsing |
| `polars` | DataFrame operations |
| `requests` | Used only in `build_age_grade_cache.py` |
