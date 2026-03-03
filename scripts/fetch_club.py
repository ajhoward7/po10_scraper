#!/usr/bin/env python3
"""
Fetch all athletes from a Power of 10 club and export their performances.

Usage:
    python scripts/fetch_club.py --club "Thames Hare & Hounds"
    python scripts/fetch_club.py --club "Thames Hare & Hounds" --concurrency 3

Output:
    data/exports/thames_hare_hounds.parquet
    data/exports/thames_hare_hounds.csv
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Allow running from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import polars as pl

from po10.analysis.age_grade import add_age_grades
from po10.client import Po10Client
from po10.models import Athlete
from po10.parsers.athlete import parse_athlete_page
from po10.search.browser import get_club_athlete_guids

DATA_DIR = Path(__file__).parent.parent / "data"
ATHLETES_DIR = DATA_DIR / "athletes"
EXPORTS_DIR = DATA_DIR / "exports"


# ---------------------------------------------------------------------------
# Caching helpers
# ---------------------------------------------------------------------------

def _cache_path(guid: str) -> Path:
    return ATHLETES_DIR / f"{guid}.json"


def _save_cache(guid: str, html: str) -> None:
    ATHLETES_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(guid).write_text(html, encoding="utf-8")


def _load_cache(guid: str) -> Optional[str]:
    p = _cache_path(guid)
    return p.read_text(encoding="utf-8") if p.exists() else None


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

async def fetch_athletes(
    athlete_stubs: list[dict],
    concurrency: int = 3,
) -> list[Athlete]:
    """
    Fetch and parse athlete profiles, using a local cache to avoid re-fetching.
    Runs up to `concurrency` requests in parallel.
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[Athlete] = []
    total = len(athlete_stubs)

    async with Po10Client(rate_limit_secs=1.5) as client:
        async def fetch_one(stub: dict, index: int) -> Optional[Athlete]:
            guid = stub["guid"]
            async with semaphore:
                html = _load_cache(guid)
                if html is None:
                    print(f"  [{index}/{total}] Fetching {stub['first_name']} {stub['last_name']} ...")
                    html = await client.get_athlete(guid)
                    _save_cache(guid, html)
                else:
                    print(f"  [{index}/{total}] Cached  {stub['first_name']} {stub['last_name']}")

                athlete = parse_athlete_page(html, guid)

                # Fill in name/sex from search results if parser couldn't extract them
                if not athlete.first_name:
                    athlete.first_name = stub["first_name"]
                if not athlete.last_name:
                    athlete.last_name = stub["last_name"]
                if not athlete.sex:
                    athlete.sex = stub.get("sex", "")

                return athlete

        tasks = [fetch_one(stub, i + 1) for i, stub in enumerate(athlete_stubs)]
        fetched = await asyncio.gather(*tasks, return_exceptions=True)

    for item in fetched:
        if isinstance(item, Exception):
            print(f"  Warning: fetch failed — {item}")
        elif item is not None:
            results.append(item)

    return results


# ---------------------------------------------------------------------------
# DataFrame construction
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> Optional[date]:
    """Parse 'DD/MM/YYYY' → date, returning None on failure."""
    if not date_str or len(date_str) != 10:
        return None
    try:
        d, m, y = date_str.split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


_FILTER_FROM = date(2025, 3, 1)


def build_dataframe(athletes: list[Athlete]) -> pl.DataFrame:
    rows = []
    for athlete in athletes:
        all_events = (
            athlete.track_events
            + athlete.road_events
            + athlete.xc_events
        )
        for event_bests in all_events:
            for perf in event_bests.all_results:
                perf_date = _parse_date(perf.date)
                if perf_date is None or perf_date < _FILTER_FROM:
                    continue
                rows.append(
                    {
                        "first_name": athlete.first_name,
                        "last_name": athlete.last_name,
                        "date_of_performance": perf_date,
                        "event": perf.event,
                        "performance": perf.value_display,
                        "race_position": perf.position,
                        "sex": athlete.sex,
                        "age_group": perf.age_group,
                        "meeting": perf.meeting,
                        "venue": perf.venue,
                        "results_url": perf.results_url,
                    }
                )

    if not rows:
        return pl.DataFrame(
            schema={
                "first_name": pl.Utf8,
                "last_name": pl.Utf8,
                "date_of_performance": pl.Date,
                "event": pl.Utf8,
                "performance": pl.Utf8,
                "race_position": pl.Int32,
                "sex": pl.Utf8,
                "age_group": pl.Utf8,
                "meeting": pl.Utf8,
                "venue": pl.Utf8,
                "results_url": pl.Utf8,
            }
        )

    df = pl.DataFrame(rows)

    # Cast to correct types
    df = df.with_columns(
        [
            pl.col("date_of_performance").cast(pl.Date),
            pl.col("race_position").cast(pl.Int32),
        ]
    )

    return df


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _club_to_filename(club: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", club.lower()).strip("_")


def export(df: pl.DataFrame, club: str) -> None:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = _club_to_filename(club)
    parquet_path = EXPORTS_DIR / f"{stem}.parquet"
    csv_path = EXPORTS_DIR / f"{stem}.csv"
    df.write_parquet(parquet_path)
    df.write_csv(csv_path)
    print(f"\nSaved: {parquet_path}")
    print(f"Saved: {csv_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch all athletes from a PO10 club.")
    parser.add_argument("--club", default="Thames Hare & Hounds", help="Club name to search for")
    parser.add_argument("--concurrency", type=int, default=3, help="Parallel fetch limit")
    parser.add_argument(
        "--guids-file",
        help="Skip search; load athlete stubs from a JSON file (list of {guid, first_name, last_name, sex})",
    )
    args = parser.parse_args()

    if args.guids_file:
        with open(args.guids_file) as f:
            athlete_stubs = json.load(f)
        print(f"Loaded {len(athlete_stubs)} athletes from {args.guids_file}")
    else:
        athlete_stubs = await get_club_athlete_guids(args.club)

    if not athlete_stubs:
        print("No athletes found. Exiting.")
        return

    # Save stubs for reuse (skip search next time with --guids-file)
    stubs_path = DATA_DIR / f"{_club_to_filename(args.club)}_guids.json"
    stubs_path.parent.mkdir(parents=True, exist_ok=True)
    stubs_path.write_text(json.dumps(athlete_stubs, indent=2))
    print(f"Athlete GUIDs saved to {stubs_path}")

    print(f"\nFetching {len(athlete_stubs)} athlete profiles...")
    athletes = await fetch_athletes(athlete_stubs, concurrency=args.concurrency)
    print(f"Successfully parsed {len(athletes)} athletes.")

    print("\nBuilding DataFrame...")
    df = build_dataframe(athletes)
    df = add_age_grades(df)

    print(f"\nDataFrame shape: {df.shape[0]:,} rows x {df.shape[1]} columns")
    print(df.schema)
    print(df.head(10))

    export(df, args.club)


if __name__ == "__main__":
    asyncio.run(main())
