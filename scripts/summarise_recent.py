#!/usr/bin/env python3
"""
Output a structured JSON summary of recent club performances.

Intended as data input for the monthly results round-up email task.

Usage:
    python scripts/summarise_recent.py                                   # last 30 days, Thames H&H
    python scripts/summarise_recent.py --club "Blackheath & Bromley"
    python scripts/summarise_recent.py --days 60
    python scripts/summarise_recent.py --since 2025-05-01
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import polars as pl

_EXPORTS_DIR = Path(__file__).parent.parent / "data" / "exports"


def _club_to_filename(club: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", club.lower()).strip("_")


def _to_records(frame: pl.DataFrame) -> list[dict]:
    """Serialise a Polars DataFrame to a list of dicts, converting dates to ISO strings."""
    return [
        {k: (v.isoformat() if isinstance(v, date) else v) for k, v in row.items()}
        for row in frame.iter_rows(named=True)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise recent club performances as JSON.")
    parser.add_argument(
        "--club", default="Thames Hare & Hounds",
        help="Club name (must match the fetch_club.py --club value used to generate the data)",
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Look-back window in days (default: 30)",
    )
    parser.add_argument(
        "--since", type=str,
        help="Explicit start date YYYY-MM-DD (overrides --days)",
    )
    args = parser.parse_args()

    parquet = _EXPORTS_DIR / f"{_club_to_filename(args.club)}.parquet"
    if not parquet.exists():
        print(
            f"ERROR: Parquet file not found at {parquet}. Run fetch_club.py --club {args.club!r} first.",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pl.read_parquet(parquet)

    since: date = date.fromisoformat(args.since) if args.since else date.today() - timedelta(days=args.days)
    recent = df.filter(pl.col("date_of_performance") >= since)

    if recent.is_empty():
        json.dump({"error": f"No performances found since {since}"}, sys.stdout, indent=2)
        return

    n_athletes  = recent.select(["first_name", "last_name"]).unique().height
    n_perfs     = len(recent)
    events_seen = sorted(recent["event"].unique().to_list())

    # Top 10 by absolute quality (senior_age_grade — no age adjustment), one per athlete
    top_absolute = (
        recent
        .filter(pl.col("senior_age_grade").is_not_null())
        .sort("senior_age_grade", descending=True)
        .unique(subset=["first_name", "last_name"], keep="first", maintain_order=True)
        .head(10)
        .select([
            "first_name", "last_name", "event", "performance",
            "age_group", "sex", "date_of_performance",
            "meeting", "venue", "senior_age_grade", "age_grade", "results_url",
        ])
    )

    # Top 10 by age-graded score (age_grade — adjusted for age bracket), one per athlete
    top_age_graded = (
        recent
        .filter(pl.col("age_grade").is_not_null())
        .sort("age_grade", descending=True)
        .unique(subset=["first_name", "last_name"], keep="first", maintain_order=True)
        .head(10)
        .select([
            "first_name", "last_name", "event", "performance",
            "age_group", "sex", "date_of_performance",
            "meeting", "venue", "senior_age_grade", "age_grade", "results_url",
        ])
    )

    # All podium finishes (1st / 2nd / 3rd place)
    podium = (
        recent
        .filter(pl.col("race_position").is_not_null() & (pl.col("race_position") <= 3))
        .sort(["race_position", "date_of_performance"], descending=[False, True])
        .select([
            "first_name", "last_name", "event", "performance",
            "race_position", "age_group", "sex", "date_of_performance",
            "meeting", "venue", "results_url",
        ])
    )

    # Every performance in the window (for full narrative context)
    all_recent = (
        recent
        .sort("date_of_performance", descending=True)
        .select([
            "first_name", "last_name", "event", "performance",
            "race_position", "age_group", "sex", "date_of_performance",
            "meeting", "venue", "senior_age_grade", "age_grade", "results_url",
        ])
    )

    output = {
        "period": {
            "since": str(since),
            "until": str(date.today()),
            "n_athletes_competing": n_athletes,
            "n_performances": n_perfs,
            "events": events_seen,
        },
        "top_absolute":          _to_records(top_absolute),
        "top_age_graded":        _to_records(top_age_graded),
        "podium_finishes":       _to_records(podium),
        "all_recent_performances": _to_records(all_recent),
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
