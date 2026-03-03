# po10_scraper

Scrapes athletics performance data from [Power of 10](https://www.thepowerof10.info/) for a given club and exports it with WMA age-grade scores.

Built for Thames Hare & Hounds, but configurable for any PO10 club.

---

## Output

Two files are written to `data/exports/`:

| File | Description |
|---|---|
| `thames_hare_hounds.parquet` | All performances since March 2025 |
| `thames_hare_hounds.csv` | Same data as CSV |

### Columns

| Column | Type | Description |
|---|---|---|
| `first_name` / `last_name` | String | Athlete name |
| `date_of_performance` | Date | |
| `event` | String | e.g. `5K`, `1500`, `Half_Marathon`, `XC` |
| `performance` | String | e.g. `"16:32"`, `"4:15.3"`, `"2:29:01"` |
| `race_position` | Int32 | Finishing position |
| `sex` | String | `"Men"` or `"Women"` |
| `age_group` | String | e.g. `"Senior"`, `"M40"`, `"W70"` |
| `age_grade` | Float32 | WMA age-adjusted score (0–100). 100 = world-record standard for that age/sex/event |
| `senior_age_grade` | Float32 | Same performance scored against the open/senior standard (no age adjustment) — measures absolute quality |

---

## Quick start

```bash
# Install dependencies
uv pip install -r requirements.txt --python /path/to/python

# Install Playwright browser (needed for the initial club search)
playwright install chromium

# First run: searches PO10 for the club, then fetches all athlete profiles
python scripts/fetch_club.py --club "Thames Hare & Hounds"

# Subsequent runs: use cached GUIDs (no browser needed)
python scripts/fetch_club.py --guids-file data/thames_hare_hounds_guids.json
```

---

## Project structure

```
po10_scraper/
├── po10/
│   ├── client.py              # Async HTTP client with rate limiting
│   ├── models.py              # Athlete / Performance dataclasses
│   ├── parsers/
│   │   └── athlete.py         # HTML parser for PO10 athlete pages
│   ├── search/
│   │   └── browser.py         # Playwright-based club member search
│   └── analysis/
│       └── age_grade.py       # WMA age-grading (reads local cache)
├── scripts/
│   ├── fetch_club.py          # Main entry point
│   └── build_age_grade_cache.py  # One-time: fetch & cache WMA factor tables
├── data/
│   ├── age_grade_tables.json  # Cached WMA factor tables (committed)
│   ├── thames_hare_hounds_guids.json  # Cached athlete GUIDs (committed)
│   ├── athletes/              # Per-athlete HTML cache (gitignored)
│   └── exports/               # Output parquet/CSV (gitignored)
└── requirements.txt
```

---

## Age grading

Age grades are computed from [WMA (World Masters Athletics)](https://world-masters-athletics.org/) factor tables, cached locally in `data/age_grade_tables.json`.

The cache is built from [Howard Grubb's online calculators](https://howardgrubb.co.uk/athletics/):

| Source | Events | Ages | Used for |
|---|---|---|---|
| T&F 2015 (`wmalookup15.html`) | Track + road + hurdles + walks | 5–100 | All events (standards + base factors) |
| T&F 2023 (`wmatnf23.html`) | Track + HM + Marathon | 30–110 | Overlay for masters athletes (preferred where available) |

**Formula:** `age_grade = 100 × open_WR / (factor[age] × performance_seconds)`

**`senior_age_grade`** uses `factor = 1.0` — the same performance measured against the open world-record standard, independent of age.

To rebuild the cache from source:
```bash
python scripts/build_age_grade_cache.py
```

### Limitations

- Age uses the bottom of the bracket (`M40` → 40 years); actual age may be up to 4 years higher, giving a slightly lower age grade than reality.
- Field events (High Jump, Discus, Shot) → `null` (different formula, not implemented).
- `"Senior"` age group → assumed age 30 (factor ≈ 1.0 for most events).
- XC events use road-equivalent distances (8 km for standard XC).

---

## Re-running the scrape

Athlete HTML pages are cached in `data/athletes/<guid>.json`. Delete these files (or the whole directory) to force a fresh fetch from PO10.

The GUIDs file (`data/thames_hare_hounds_guids.json`) records the list of club members found during the last browser-based search. Pass `--guids-file` to skip the browser step on subsequent runs.
