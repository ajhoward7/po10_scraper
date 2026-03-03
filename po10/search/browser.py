"""
Playwright-based athlete search for powerof10.uk.

The athlete search page is protected by reCaptcha v3. We launch a *visible*
(non-headless) browser so the user can interact naturally if the captcha
challenge appears. Once reCaptcha is satisfied the search AJAX response is
intercepted and parsed.

Pagination: results are served 50 per page. We click through all pages.
"""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import Page, async_playwright

_SEARCH_URL = "https://www.powerof10.uk/Home/AthleteSearch"
_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


async def get_club_athlete_guids(club_name: str) -> list[dict]:
    """
    Search powerof10.uk for all athletes in a club.

    Returns a list of dicts:
        {"guid": str, "first_name": str, "last_name": str, "sex": str}

    A visible browser window opens so reCaptcha v3 can be satisfied naturally
    if triggered.
    """
    print(f"Opening browser to search for club: {club_name!r}")
    print("If a CAPTCHA appears, complete it in the browser window.\n")

    athletes: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # First page
        page_athletes = await _search_page(page, club_name)
        athletes.extend(page_athletes)
        print(f"\r  Page 1: {len(page_athletes)} athletes found")

        # Keep clicking Next until no more pages
        page_num = 2
        while True:
            next_athletes = await _next_page(page)
            if not next_athletes:
                break
            athletes.extend(next_athletes)
            print(f"  Page {page_num}: {len(next_athletes)} athletes found")
            page_num += 1

        await browser.close()

    # Deduplicate by guid
    seen: set[str] = set()
    unique = []
    for a in athletes:
        if a["guid"] not in seen:
            seen.add(a["guid"])
            unique.append(a)

    print(f"\nTotal: {len(unique)} athletes found in {club_name!r}")
    return unique


async def _search_page(page: Page, club_name: str) -> list[dict]:
    """Navigate to the search page, submit the club query, and wait for the AJAX response."""
    collected: list[dict] = []
    response_event = asyncio.Event()

    # Static file extensions to ignore
    _STATIC_EXTS = (".js", ".css", ".png", ".jpg", ".ico", ".woff", ".woff2", ".ttf", ".svg", ".map")

    async def handle_response(response):
        # Only care about the RunAthleteSearch endpoint
        if "RunAthleteSearch" not in response.url:
            return

        try:
            body = await response.text()
        except Exception:
            return

        try:
            import json as _json
            data = _json.loads(body)
        except Exception:
            print(f"\n  [debug] Non-JSON RunAthleteSearch response: {body[:300]!r}")
            response_event.set()
            return

        status = data.get("status", "")

        if status == "RECAPTCHA_REQUIRED":
            # First probe — JS will call grecaptcha.execute() and retry with a real token
            print("\n  reCaptcha token requested, waiting for retry...")
            return

        if status == "ERROR_RECAPTCHA":
            print("\n  [warning] reCaptcha token rejected by server.")
            response_event.set()
            return

        _extract_athletes(data, collected)
        response_event.set()

    await page.goto(_SEARCH_URL, wait_until="domcontentloaded")
    await page.fill("#searchClubName", club_name)

    # Register listener just before the click
    page.on("response", handle_response)
    await page.click("#search-submit")

    await _wait_with_spinner(response_event, timeout=120, label="Waiting for search results")

    page.remove_listener("response", handle_response)

    if not response_event.is_set():
        print("\n  [warning] Timed out — no API response received after 120s.")

    return collected


async def _next_page(page: Page) -> list[dict]:
    """Click the Next pagination button and collect the next page of results."""
    collected: list[dict] = []

    next_btn = await page.query_selector(
        "a[data-page], button[data-page], "
        "a:has-text('Next'), button:has-text('Next'), "
        "[aria-label='Next page'], .pagination-next"
    )
    if not next_btn:
        return []

    response_event = asyncio.Event()

    async def handle_response(response):
        if "RunAthleteSearch" not in response.url:
            return
        try:
            body = await response.text()
        except Exception:
            return
        if body.strip() == "RECAPTCHA_REQUIRED":
            return
        try:
            import json as _json
            data = _json.loads(body)
            _extract_athletes(data, collected)
        except Exception:
            pass
        response_event.set()

    page.on("response", handle_response)
    await next_btn.click()
    await _wait_with_spinner(response_event, timeout=30, label="Loading next page")
    page.remove_listener("response", handle_response)

    return collected


async def _wait_with_spinner(event: asyncio.Event, timeout: int, label: str) -> None:
    """Show a spinner while waiting for an asyncio.Event, up to `timeout` seconds."""
    frame = 0
    for elapsed in range(timeout * 10):  # check every 0.1s
        if event.is_set():
            break
        spin = _SPINNER[frame % len(_SPINNER)]
        sys.stdout.write(f"\r  {spin} {label}... ({elapsed // 10}s)")
        sys.stdout.flush()
        frame += 1
        await asyncio.sleep(0.1)


def _is_empty_result(data: dict | list) -> bool:
    """Return True if the response is a valid but empty result set."""
    if isinstance(data, list):
        return len(data) == 0
    if isinstance(data, dict):
        status = data.get("status", "")
        if status in ("OK", "ok") and not data.get("results"):
            return True
        if "noResults" in data or data.get("count") == 0:
            return True
    return False


def _extract_athletes(data: dict | list, out: list[dict]) -> None:
    """Parse athletes from a search JSON response into out list."""
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = (
            data.get("results")
            or data.get("data")
            or data.get("athletes")
            or data.get("items")
            or []
        )
    else:
        return

    for r in records:
        if not isinstance(r, dict):
            continue
        guid = r.get("id") or r.get("guid") or r.get("athid") or r.get("athleteId")
        if not guid:
            continue
        first = r.get("fn") or r.get("firstName") or r.get("first_name") or ""
        last = (
            r.get("ln")
            or r.get("lastName")
            or r.get("last_name")
            or r.get("surname")
            or ""
        )
        sex_raw = r.get("sex") or r.get("gender") or ""
        out.append(
            {
                "guid": str(guid),
                "first_name": first,
                "last_name": last,
                "sex": _normalise_sex(sex_raw),
            }
        )


def _normalise_sex(raw: str) -> str:
    lower = raw.lower().strip()
    if lower in ("w", "f", "female", "women", "woman"):
        return "Women"
    if lower in ("m", "male", "men", "man"):
        return "Men"
    return raw
