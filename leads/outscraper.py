"""
Outscraper Google Maps Search client.

Contract verified against Outscraper dashboard API docs and
https://docs.outscraper.com/endpoints/google-maps-search/ (2026-09):

- Auth: ``X-API-KEY`` header on every request (``apiKey`` query param exists
  but is less secure; we do not use it).
- Search: ``GET https://api.outscraper.cloud/google-maps-search``
  (dashboard / API explorer host; ``api.outscraper.com`` is listed in some
  OpenAPI pages but curl examples use ``.cloud``).
- ``async=false``: hold the HTTP connection until results (HTTP 200,
  ``status=Success``, ``data`` populated). Docs recommend this only for small
  ``limit`` values (fastest around 10).
- ``async=true`` (API default): submit the job and poll
  ``GET https://api.outscraper.cloud/requests/{id}`` until ``Success`` /
  ``Failure``. Preferred for larger result counts to avoid HTTP timeouts.
  Initial submit returns HTTP 202 with ``status=Pending`` and ``id``.
- Place fields we consume: ``name``, ``full_address``, ``phone``, ``site``,
  ``location_link``, ``place_id``, ``cid``, ``google_id``. Social URLs appear
  only with paid enrichments (``Facebook``, ``Instagram``, …).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

OUTSCRAPER_API_BASE_DEFAULT = "https://api.outscraper.cloud"
OUTSCRAPER_MAPS_PATH = "/google-maps-search"
# Hold the connection only for small hunts; larger limits poll a job.
OUTSCRAPER_SYNC_LIMIT = 20
OUTSCRAPER_POLL_MAX_SECONDS = 90.0
OUTSCRAPER_POLL_INTERVAL_START = 2.0
OUTSCRAPER_POLL_INTERVAL_MAX = 8.0
OUTSCRAPER_LIMIT_MAX = 500


def _api_base() -> str:
    raw = (getattr(settings, "OUTSCRAPER_API_BASE", "") or "").strip()
    return (raw or OUTSCRAPER_API_BASE_DEFAULT).rstrip("/")


def outscraper_api_key() -> str:
    key = getattr(settings, "OUTSCRAPER_API_KEY", "") or ""
    if not key.strip():
        raise ValueError("OUTSCRAPER_API_KEY is not configured.")
    return key.strip()


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key}


def _format_http_error(exc: requests.HTTPError) -> str:
    detail = ""
    if exc.response is not None:
        try:
            body = exc.response.json()
            if isinstance(body, dict):
                detail = str(
                    body.get("errorMessage") or body.get("error") or body.get("message") or ""
                ).strip()
            if not detail:
                detail = (exc.response.text or "")[:500].strip()
        except Exception:
            detail = (exc.response.text or "")[:500].strip()
    msg = f"Outscraper HTTP error: {exc}"
    if detail:
        msg += f" {detail}"
    return msg.strip()


def extract_outscraper_places(payload: Any) -> list[dict[str, Any]]:
    """Flatten Outscraper ``data``: nested per-query arrays, or a flat list."""
    root = payload
    if isinstance(payload, dict):
        root = payload.get("data")
    if not isinstance(root, list):
        return []
    places: list[dict[str, Any]] = []
    for item in root:
        if isinstance(item, list):
            places.extend(p for p in item if isinstance(p, dict))
        elif isinstance(item, dict):
            places.append(item)
    return places


def _poll_request(request_id: str, *, api_key: str) -> tuple[dict[str, Any], list[str]]:
    url = urljoin(_api_base() + "/", f"requests/{request_id.lstrip('/')}")
    deadline = time.monotonic() + OUTSCRAPER_POLL_MAX_SECONDS
    interval = OUTSCRAPER_POLL_INTERVAL_START
    last_status = "Pending"
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            resp = requests.get(url, headers=_headers(api_key), timeout=30)
            if resp.status_code == 204:
                return {}, [f"Outscraper job {request_id} finished with no results (Failure)."]
            resp.raise_for_status()
            body = resp.json()
        except requests.HTTPError as exc:
            return {}, [_format_http_error(exc)]
        except requests.RequestException as exc:
            return {}, [f"Outscraper poll failed: {exc}"]
        except ValueError as exc:
            return {}, [f"Invalid JSON from Outscraper poll: {exc}"]
        if not isinstance(body, dict):
            return {}, ["Outscraper poll returned a non-object JSON body."]
        last_status = str(body.get("status") or "")
        if last_status == "Success":
            return body, []
        if last_status == "Failure":
            return {}, [f"Outscraper job {request_id} failed."]
        interval = min(interval * 1.5, OUTSCRAPER_POLL_INTERVAL_MAX)
    return {}, [
        f"Outscraper job {request_id} still {last_status or 'Pending'} after "
        f"{int(OUTSCRAPER_POLL_MAX_SECONDS)}s. Retry the hunt, or lower the result limit."
    ]


def collect_outscraper_maps_places(
    search_q: str,
    *,
    target: int,
    api_key: str,
    region: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    """One Google Maps Search request; poll when ``target`` exceeds the sync cutoff."""
    limit = max(1, min(int(target), OUTSCRAPER_LIMIT_MAX))
    use_async = limit > OUTSCRAPER_SYNC_LIMIT
    params: dict[str, Any] = {
        "query": search_q,
        "limit": limit,
        "async": "true" if use_async else "false",
        "language": "en",
    }
    region_code = (region or "").strip().upper()
    if region_code:
        params["region"] = region_code

    url = _api_base() + OUTSCRAPER_MAPS_PATH
    timeout = 90 if not use_async else 30
    logger.info(
        "Outscraper Maps request q=%r limit=%s async=%s region=%s",
        search_q,
        limit,
        params["async"],
        params.get("region"),
    )
    try:
        resp = requests.get(url, params=params, headers=_headers(api_key), timeout=timeout)
        if resp.status_code == 204:
            return [], ["Outscraper finished with no results (Failure)."]
        resp.raise_for_status()
        body = resp.json()
    except requests.HTTPError as exc:
        return [], [_format_http_error(exc)]
    except requests.RequestException as exc:
        return [], [f"Outscraper request failed: {exc}"]
    except ValueError as exc:
        return [], [f"Invalid JSON from Outscraper: {exc}"]

    if not isinstance(body, dict):
        return [], ["Outscraper returned a non-object JSON body."]

    status = str(body.get("status") or "")
    if status == "Pending" or (use_async and status != "Success"):
        request_id = str(body.get("id") or "").strip()
        if not request_id:
            return [], ["Outscraper accepted the job but returned no request id."]
        body, poll_errors = _poll_request(request_id, api_key=api_key)
        if poll_errors:
            return [], poll_errors
        status = str(body.get("status") or "")

    if status == "Failure":
        return [], ["Outscraper job failed."]
    if status and status != "Success":
        return [], [f"Unexpected Outscraper status: {status}."]

    places = extract_outscraper_places(body)
    if not places:
        logger.warning(
            "Outscraper Maps empty places for q=%r keys=%s",
            search_q,
            list(body.keys()),
        )
        return [], [
            "Outscraper returned 0 Maps place rows. Try a clearer city/area or keyword. "
            f"Query sent: {search_q!r}"
        ]
    return places[:limit], []
