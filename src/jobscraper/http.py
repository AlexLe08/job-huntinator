"""Polite HTTP client: clear UA, timeouts, retries with exponential backoff, spacing between requests."""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "job-huntinator/0.1 (personal job-search tool; polls public job-board APIs twice daily)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PoliteClient:
    def __init__(
        self,
        timeout: float = 15.0,
        retries: int = 3,
        delay: float = 0.6,
        backoff_base: float = 1.5,
        transport: httpx.BaseTransport | None = None,
    ):
        self.retries = retries
        self.delay = delay
        self.backoff_base = backoff_base
        self._last_request = 0.0
        self._lock = threading.Lock()  # spacing is per client (= per host), shared across threads
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            transport=transport,
        )

    def _wait_turn(self) -> None:
        with self._lock:
            if self.delay > 0:
                gap = time.monotonic() - self._last_request
                target = self.delay + random.uniform(0, self.delay / 2)
                if gap < target:
                    time.sleep(target - gap)
            self._last_request = time.monotonic()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait_turn()
            try:
                resp = self._client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                log.debug("network error %s on %s (attempt %d)", exc, url, attempt + 1)
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code not in RETRY_STATUSES:
                    raise FetchError(f"HTTP {resp.status_code} for {url}", resp.status_code)
                last_exc = FetchError(f"HTTP {resp.status_code} for {url}", resp.status_code)
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit() and attempt < self.retries:
                    time.sleep(min(int(retry_after), 60))
                    continue
            if attempt < self.retries:
                time.sleep(self.backoff_base ** (attempt + 1) if self.backoff_base else 0)
        status = getattr(last_exc, "status", None)
        raise FetchError(f"giving up on {url}: {last_exc}", status)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs).json()

    def post_json(self, url: str, json: Any, **kwargs: Any) -> Any:
        return self.request("POST", url, json=json, **kwargs).json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.request("GET", url, **kwargs).text

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
