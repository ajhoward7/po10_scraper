# Monthly Results Round-Up

Generate a monthly results round-up HTML email for Thames Hare & Hounds.

---

## Step 1 — Fetch up-to-date results

Run a full scrape from scratch (browser search + fresh athlete profiles):

```bash
/Users/alexhoward/.venv/bin/python scripts/fetch_club.py --club "Thames Hare & Hounds"
```

This re-searches PO10 for the current club membership and re-fetches all athlete profiles. Wait for it to complete before proceeding.

---

## Step 2 — Generate performance summary

Run the summary script for the last 30 days (adjust `--days` or use `--since YYYY-MM-DD` for a different window):

```bash
/Users/alexhoward/.venv/bin/python scripts/summarise_recent.py --days 30
```

Capture the JSON output. It contains:

| Key | Contents |
|-----|----------|
| `period` | Date range, athlete count, event list |
| `top_absolute` | Top 10 performances by `senior_age_grade` (absolute quality, no age adjustment), one per athlete |
| `top_age_graded` | Top 10 by `age_grade` (WMA age-adjusted), one per athlete |
| `podium_finishes` | Every 1st / 2nd / 3rd place finish in the period |
| `all_recent_performances` | Full list for narrative context |

---

## Step 3 — Write the HTML email

Using the JSON data, write the email and save to:

```
data/exports/roundup_YYYY-MM-DD.html
```

(Use today's date in the filename.)

### Email sections (in order)

1. **Header** — Club name + period covered (e.g. "Results Round-Up: May 2025")
2. **At a Glance** — 2–3 sentences: how many athletes competed, how many events, any headline stat
3. **Highlights** — Written narrative (see guidance below)
4. **Top Performances table** — Sourced from `top_absolute`
5. **Top Age-Graded Performances table** — Sourced from `top_age_graded`
6. **Sign-off** — From the club captain

---

## Highlights narrative guidance

Write 3–6 paragraphs of engaging club-newsletter prose. Aim for the tone of a supportive, enthusiastic club captain — warm, specific, not generic.

**Always cover:**
- Podium finishes and race wins — these are the most newsworthy results; name the athlete, event, and meeting
- The top 1–3 absolute performances (senior_age_grade) with brief context
- The top age-graded performances, especially where an athlete's age_grade significantly exceeds their senior_age_grade (this means they ran exceptionally well relative to their age group)

**Include where relevant:**
- Athletes competing in multiple events or particularly busy weeks
- Mention meeting/venue names to give the results a sense of place
- If `results_url` is available for a performance, mention that full results are linked in the table

**Age grade benchmarks** (use these to calibrate language):
- ≥ 90% — world-class / elite national standard
- ≥ 80% — excellent, national-class club performance
- ≥ 70% — very strong club standard / regional class
- ≥ 60% — solid club performance

**Tone notes:**
- Use first names throughout
- Avoid hollow filler phrases like "truly remarkable" or "outstanding achievement"
- Be specific: name the event, the time, and the context
- For masters athletes, age_grade is the more meaningful metric — lead with that

---

## Table specifications

### Top Performances (by absolute quality)

Columns: Athlete | Event | Performance | Date | Meeting | Senior Age Grade

- Sort by `senior_age_grade` descending
- Where `results_url` is not null, make the Meeting name a hyperlink to that URL
- Format `senior_age_grade` as e.g. `86.7%`
- Format `date_of_performance` as e.g. `12 Apr`

### Top Age-Graded Performances

Columns: Athlete | Event | Performance | Age Group | Date | Meeting | Age Grade

- Sort by `age_grade` descending
- Same link and formatting rules as above
- Include Age Group column so readers can see masters adjustments

---

## HTML styling requirements

Use **inline CSS only** (required for email client compatibility).

- `font-family: Arial, Helvetica, sans-serif`
- `font-size: 14px`, `line-height: 1.6`
- Max container width: `700px`, centred
- **Header**: dark navy background (`#1a2e4a`), white text, club name prominent
- **Section headings**: navy text (`#1a2e4a`), bottom border
- **Tables**:
  - Full width, `border-collapse: collapse`
  - Header row: `#1a2e4a` background, white text, `padding: 8px 12px`
  - Alternating rows: white / `#f5f7fa`
  - Top row (best performance): `#fff8dc` (light gold) background
  - Cell padding: `8px 12px`
  - Thin border: `1px solid #dde`
- **Links**: navy, no underline unless hovered (inline `color: #1a2e4a`)
- **Footer**: small grey text, italic

---

## Example subject line

```
Thames H&H Results Round-Up — [Month] [Year]
```
