from __future__ import annotations

import asyncio
import time

import httpx

BASE_URL = "https://www.powerof10.uk"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class Po10Client:
    def __init__(self, rate_limit_secs: float = 2.0):
        self._client = httpx.AsyncClient(
            headers=_HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )
        self._rate_limit = rate_limit_secs
        self._last_request: float = 0.0

    async def get_athlete(self, guid: str) -> str:
        return await self._get(f"/Home/Athlete/{guid}")

    async def _get(self, path: str) -> str:
        await self._throttle()
        for attempt in range(3):
            try:
                r = await self._client.get(BASE_URL + path)
                r.raise_for_status()
                self._last_request = time.monotonic()
                return r.text
            except (httpx.HTTPStatusError, httpx.RequestError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)

    async def __aenter__(self) -> Po10Client:
        return self

    async def __aexit__(self, *_) -> None:
        await self._client.aclose()
