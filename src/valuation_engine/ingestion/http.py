import time

import httpx

from valuation_engine.logging import log


class SourceClient:
    def __init__(
        self, user_agent: str = "QVE/0.1 official-research", client: httpx.Client | None = None
    ):
        self.client = client or httpx.Client(
            timeout=45, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        self.last_request = 0.0

    def get(self, url: str) -> bytes:
        for attempt in range(3):
            time.sleep(max(0, 0.25 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            response = self.client.get(url)
            if response.status_code in (429, 500, 502, 503, 504):
                log("source_retry", source=url, status=response.status_code, attempt=attempt + 1)
                retry = response.headers.get("Retry-After", "")
                time.sleep(min(10, float(retry)) if retry.isdigit() else 2**attempt)
                continue
            response.raise_for_status()
            return response.content
        raise RuntimeError(f"Source unavailable / rate limited after 3 attempts: {url}")
