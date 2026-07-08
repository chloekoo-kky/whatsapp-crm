"""
Serper Maps scraping for business leads (any category).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

from leads.display import normalize_manual_phone
from leads.models import CategoryRule, Lead, SearchQueryRecord
from leads.pipeline import (
    ensure_pipeline_system_groups,
    get_or_create_uncategorized_group,
    phone_exists_in_database,
)

logger = logging.getLogger(__name__)

SERPER_MAPS_URL = "https://google.serper.dev/maps"
SERPER_MAPS_PAGE_SIZE = 20
SERPER_MAPS_DEFAULT_ZOOM = "13z"
# Serper free-tier rejects Google operators like -exclude in Maps queries.
_SERPER_QUERY_OPERATOR_RE = re.compile(r'\s+-"[^"]*"|\s+-[^\s]+')


def _hunt_max_results() -> int:
    return max(1, min(int(getattr(settings, "HUNT_MAX_LIMIT", 100)), 100))


def _place_dedupe_key(raw: dict[str, Any]) -> str:
    """Stable key to dedupe the same listing across Serper result pages."""
    for key in ("cid", "placeId", "place_id"):
        v = raw.get(key)
        if v is not None and str(v).strip():
            return f"id:{str(v).strip()}"
    title = (raw.get("title") or raw.get("name") or "").strip().lower()
    addr = (raw.get("address") or "").strip().lower()
    if title or addr:
        return f"na:{title}|{addr}"
    return ""

# Google ``gl`` (country) for Serper Maps — biases local results (e.g. Malaysia → my).
_COUNTRY_NAME_TO_GL: dict[str, str] = {
    "malaysia": "my",
    "my": "my",
    "singapore": "sg",
    "sg": "sg",
    "thailand": "th",
    "indonesia": "id",
    "brunei": "bn",
    "philippines": "ph",
    "vietnam": "vn",
    "australia": "au",
    "united kingdom": "uk",
    "uk": "uk",
    "united states": "us",
    "usa": "us",
    "us": "us",
    "india": "in",
    "china": "cn",
    "hong kong": "hk",
    "taiwan": "tw",
    "japan": "jp",
    "south korea": "kr",
    "korea": "kr",
}


def _country_hint_to_gl(country: str) -> str | None:
    """Map free-text country (or 2-letter code) to Serper/Google ``gl`` when possible."""
    c = (country or "").strip().lower()
    if not c:
        return None
    if len(c) == 2 and c.isalpha():
        return c
    return _COUNTRY_NAME_TO_GL.get(c)


def classify_category_from_name(name: str) -> str:
    """First matching admin rule (priority, id); case-insensitive substring on business name."""
    from leads.category_types import UNKNOWN_SLUG

    n = (name or "").strip().lower()
    if not n:
        return UNKNOWN_SLUG
    qs = CategoryRule.objects.order_by("priority", "id").only("match_phrase", "category")
    for rule in qs:
        piece = (rule.match_phrase or "").strip().lower()
        if piece and piece in n:
            return rule.category
    return UNKNOWN_SLUG


@dataclass
class FetchLeadsResult:
    created: int
    skipped_existing: int
    errors: list[str]
    places_seen: int
    created_ids: list[int]
    skipped_no_website: int = 0
    skipped_duplicate_phone: int = 0
    skipped_excluded: int = 0


def _normalize_exclude_keywords(raw) -> list[str]:
    """Normalize exclude terms from a comma string or JSON list."""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else str(raw).split(",")
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        term = " ".join(str(item or "").strip().split()).lower()
        if not term or term in seen:
            continue
        seen.add(term)
        out.append(term[:80])
    return out[:12]


def _strip_serper_query_operators(search_q: str) -> str:
    """Remove Google operators Serper free accounts reject (e.g. ``-dental``, ``-"24 jam"``)."""
    stripped = _SERPER_QUERY_OPERATOR_RE.sub("", search_q or "")
    return " ".join(stripped.split())


def _format_serper_http_error(exc: requests.HTTPError, *, page: int) -> str:
    detail = ""
    if exc.response is not None:
        try:
            body = exc.response.json()
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("error") or "").strip()
            if not detail:
                detail = (exc.response.text or "")[:500].strip()
        except Exception:
            detail = (exc.response.text or "")[:500].strip()
    msg = f"Serper HTTP error (page {page}): {exc}"
    if detail:
        msg += f" {detail}"
    if "query pattern not allowed" in (detail or msg).lower():
        msg += (
            " Serper free-tier accounts cannot use advanced query operators (e.g. -exclude). "
            "Exclude keywords are applied locally after import. Avoid minus signs in the Maps query field, "
            "or upgrade your Serper plan at serper.dev."
        )
    return msg.strip()


def _place_matches_exclude_keywords(normalized: dict[str, Any], exclude_keywords: list[str]) -> bool:
    if not exclude_keywords:
        return False
    hay = f"{normalized.get('name', '')} {normalized.get('address', '')}".lower()
    return any(term in hay for term in exclude_keywords)


def _serper_api_key() -> str:
    key = getattr(settings, "SERPER_API_KEY", "") or ""
    if not key.strip():
        raise ValueError("SERPER_API_KEY is not configured.")
    return key.strip()


def _build_search_q(
    city: str,
    query: str,
    *,
    shop_keyword: str,
    state: str = "",
    country: str = "",
    exclude_keywords: list[str] | None = None,
) -> str:
    city = city.strip()
    if not city:
        raise ValueError("city is required.")
    q = (query or "").strip() or (shop_keyword or "").strip()
    if not q:
        raise ValueError("Provide a Maps query or a non-empty shop keyword.")
    st = (state or "").strip()
    ctry = (country or "").strip()
    # One concise Maps-style query; country is also sent as ``gl`` when mappable.
    parts = [q, city]
    if st:
        parts.append(st)
    if ctry:
        parts.append(ctry)
    return " ".join(parts).strip()


def _extract_serper_maps_places(data: dict[str, Any]) -> list[Any]:
    """Serper Maps usually returns ``places``; tolerate alternate keys from API variants."""
    if not isinstance(data, dict):
        return []
    for key in ("places", "localResults", "organic", "results"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    return []


def _format_serper_ll(lat: float, lng: float, zoom: str = SERPER_MAPS_DEFAULT_ZOOM) -> str:
    return f"@{lat},{lng},{zoom}"


def _parse_ll_coordinates(ll: str) -> tuple[float, float] | None:
    """Parse ``@lat,lng,13z`` into (lat, lng)."""
    s = (ll or "").strip()
    if not s.startswith("@"):
        return None
    parts = s[1:].split(",")
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None


def _extract_ll_from_serper_response(data: dict[str, Any], places: list[Any]) -> str | None:
    """Read Serper ``ll`` from response metadata or average place coordinates."""
    if isinstance(data, dict):
        top = data.get("ll")
        if isinstance(top, str) and top.strip().startswith("@"):
            return top.strip()
        sp = data.get("searchParameters")
        if isinstance(sp, dict):
            sp_ll = sp.get("ll")
            if isinstance(sp_ll, str) and sp_ll.strip().startswith("@"):
                return sp_ll.strip()

    lats: list[float] = []
    lngs: list[float] = []
    for raw in places:
        if not isinstance(raw, dict):
            continue
        lat = raw.get("latitude")
        lng = raw.get("longitude")
        if lat is None or lng is None:
            gps = raw.get("gpsCoordinates") or raw.get("gps_coordinates")
            if isinstance(gps, dict):
                lat = gps.get("latitude", lat)
                lng = gps.get("longitude", lng)
        try:
            if lat is not None and lng is not None:
                lats.append(float(lat))
                lngs.append(float(lng))
        except (TypeError, ValueError):
            continue
    if lats and lngs:
        return _format_serper_ll(sum(lats) / len(lats), sum(lngs) / len(lngs))
    return None


def _geocode_maps_ll(
    *,
    city: str,
    state: str,
    country: str,
    api_key: str,
) -> str | None:
    """One lightweight Serper Maps lookup to resolve ``ll`` for the hunt area."""
    parts = [p.strip() for p in (city, state, country) if (p or "").strip()]
    if not parts:
        return None
    location_q = ", ".join(parts)
    payload = _serper_maps_payload(location_q, 1, country=country, page=1)
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        resp = requests.post(SERPER_MAPS_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    places = _extract_serper_maps_places(data if isinstance(data, dict) else {})
    return _extract_ll_from_serper_response(data if isinstance(data, dict) else {}, places)


def _serper_maps_payload(
    search_q: str,
    num: int,
    *,
    country: str = "",
    page: int = 1,
    ll: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "q": search_q,
        "num": max(1, min(num, SERPER_MAPS_PAGE_SIZE)),
        "page": max(1, page),
        "hl": "en",
    }
    if ll:
        payload["ll"] = ll
    gl = _country_hint_to_gl(country)
    if gl:
        payload["gl"] = gl
    return payload


def _request_serper_maps_places(
    search_q: str,
    *,
    num: int,
    country: str,
    page: int,
    api_key: str,
    ll: str | None = None,
) -> tuple[list[Any], list[str], dict[str, Any]]:
    """One Serper Maps page; returns (places, errors, raw_response)."""
    payload = _serper_maps_payload(search_q, num, country=country, page=page, ll=ll)
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    logger.info(
        "Serper Maps request q=%r page=%s num=%s gl=%s ll=%s",
        search_q,
        payload.get("page"),
        payload.get("num"),
        payload.get("gl"),
        payload.get("ll"),
    )
    errors: list[str] = []
    data: dict[str, Any] = {}
    try:
        resp = requests.post(SERPER_MAPS_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        parsed = resp.json()
        data = parsed if isinstance(parsed, dict) else {}
    except requests.HTTPError as exc:
        errors.append(_format_serper_http_error(exc, page=page))
        return [], errors, data
    except requests.RequestException as exc:
        errors.append(f"Serper request failed (page {page}): {exc}")
        return [], errors, data
    except ValueError as exc:
        errors.append(f"Invalid JSON from Serper (page {page}): {exc}")
        return [], errors, data

    places = _extract_serper_maps_places(data)
    if not places and page == 1:
        if data.get("places") is not None and not isinstance(data.get("places"), list):
            errors.append("Serper 'places' field was not a list — check API response shape.")
        else:
            hints = (
                "Serper returned 0 Maps place rows. Try: (1) City spelling Google prefers "
                '(e.g. "Melaka" or "Malacca"). (2) Clear or simplify the optional Maps query so '
                "the hunt uses keyword + city + country. (3) Confirm SERPER_API_KEY and quota. "
                f"Query sent: {search_q!r}"
            )
            errors.append(hints)
        logger.warning(
            "Serper Maps empty places for q=%r page=%s keys=%s",
            search_q,
            page,
            list(data.keys()),
        )
    return places, errors, data


def _collect_serper_maps_places(
    search_q: str,
    *,
    target: int,
    country: str,
    api_key: str,
    city: str = "",
    state: str = "",
) -> tuple[list[Any], list[str]]:
    """Paginate Serper Maps until ``target`` unique listings or no more pages."""
    safe_q = _strip_serper_query_operators(search_q)
    if safe_q != search_q:
        logger.info("Serper query sanitized for API: %r -> %r", search_q, safe_q)
    search_q = safe_q or search_q
    max_pages = max(1, (target + SERPER_MAPS_PAGE_SIZE - 1) // SERPER_MAPS_PAGE_SIZE)
    all_places: list[Any] = []
    seen_keys: set[str] = set()
    errors: list[str] = []
    ll: str | None = None

    for page in range(1, max_pages + 1):
        if len(all_places) >= target:
            break
        if page > 1 and not ll:
            ll = _geocode_maps_ll(city=city, state=state, country=country, api_key=api_key)
        if page > 1 and not ll:
            errors.append(
                "Serper requires map coordinates (ll) for page 2+. "
                "Could not resolve GPS for this city — try a clearer city/state/country."
            )
            break

        page_places, page_errors, page_data = _request_serper_maps_places(
            search_q,
            num=SERPER_MAPS_PAGE_SIZE,
            country=country,
            page=page,
            api_key=api_key,
            ll=ll,
        )
        errors.extend(page_errors)
        if page == 1 and page_errors and not page_places:
            return [], errors
        if page == 1 and not ll:
            ll = _extract_ll_from_serper_response(page_data, page_places)
        if not page_places:
            break

        added = 0
        for raw in page_places:
            if not isinstance(raw, dict):
                continue
            key = _place_dedupe_key(raw)
            if key:
                if key in seen_keys:
                    continue
                seen_keys.add(key)
            all_places.append(raw)
            added += 1
            if len(all_places) >= target:
                break

        if added == 0:
            break
        if len(page_places) < SERPER_MAPS_PAGE_SIZE:
            break

    return all_places[:target], errors


def _place_maps_url(raw: dict[str, Any]) -> str:
    for key in ("link", "url", "placeUrl", "googleMapsUri"):
        v = raw.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v.strip()
    title = (raw.get("title") or "").strip()
    addr = (raw.get("address") or "").strip()
    if title or addr:
        from urllib.parse import quote

        return "https://www.google.com/maps/search/?api=1&query=" + quote(f"{title} {addr}".strip())
    lat = raw.get("latitude")
    lng = raw.get("longitude")
    if lat is not None and lng is not None:
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    return ""


def _normalize_chain_base_name(name: str) -> str:
    return " ".join((name or "").split()).strip()


def sync_chain_flags_for_name(name: str) -> None:
    base = _normalize_chain_base_name(name)
    if not base:
        return

    qs = Lead.objects.filter(name__iexact=base)
    count = qs.count()
    if count >= 2:
        qs.update(chain_detected_internal=True, is_chain=True)
        return

    for c in qs:
        internal_only = c.chain_detected_internal and not c.chain_detected_ai
        c.chain_detected_internal = False
        if internal_only:
            c.is_chain = bool(c.chain_detected_ai)
        else:
            c.is_chain = c.chain_detected_ai or c.is_chain
        c.save(update_fields=["chain_detected_internal", "is_chain"])


_MAPS_ONLY_URL_MARKERS = (
    "maps.google.com",
    "google.com/maps",
    "goo.gl/maps",
    "maps.app.goo.gl",
)


def _coerce_http_url(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    return s[:500]


def _contact_empty(val: str | None) -> bool:
    """True when a stored phone, URL, or similar field has no usable content."""
    return not (val or "").strip()


def _is_meaningful_online_presence(url: str) -> bool:
    """True for real site or social profile URL; false for bare Maps / directions links."""
    u = (url or "").strip().lower()
    if not u.startswith(("http://", "https://")):
        return False
    return not any(m in u for m in _MAPS_ONLY_URL_MARKERS)


def _extract_public_website(raw: dict[str, Any]) -> str:
    """Prefer Maps `website` and structured `links` (Facebook, Instagram, etc.) when present."""
    candidates: list[str] = []
    for key in ("website", "webUrl"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())
    links = raw.get("links")
    if isinstance(links, dict):
        for lk in (
            "website",
            "facebook",
            "instagram",
            "twitter",
            "linkedin",
            "youtube",
            "tiktok",
        ):
            v = links.get(lk)
            if isinstance(v, str) and v.strip():
                candidates.append(v.strip())
    for c in candidates:
        u = _coerce_http_url(c)
        if _is_meaningful_online_presence(u):
            return u
    return ""


def _normalize_place_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = (raw.get("title") or raw.get("name") or "").strip()
    if not name:
        return None
    phone = raw.get("phoneNumber") or raw.get("phone") or raw.get("phone_number") or ""
    phone = str(phone).strip() if phone is not None else ""
    address = (raw.get("address") or "").strip()
    website = _extract_public_website(raw)
    if not website:
        w = (raw.get("website") or raw.get("webUrl") or "").strip()
        website = _coerce_http_url(w) if w else ""
    return {
        "name": name[:255],
        "phone_number": phone[:64] if phone else "",
        "address": address,
        "website": website[:500] if website else "",
        "source_url": _place_maps_url(raw)[:2000],
    }


def fetch_leads_from_serper(
    city: str,
    query: str,
    *,
    num: int = 100,
    shop_keyword: str = "",
    state: str = "",
    country: str = "",
    search_query_record: SearchQueryRecord | None = None,
    require_website: bool = False,
    exclude_keywords: list[str] | None = None,
) -> FetchLeadsResult:
    """
    Call Serper Maps API (paginated) and persist leads. Uniqueness is (name, address); phone
    numbers are deduplicated globally before insert. New rows land in the Uncategorized folder
    with ``whatsapp_status=idle``.

    Serper Maps returns ~20 listings per page; when ``num`` > 20, additional pages are fetched
    automatically until the target count or Serper runs out of results.

    When ``require_website`` is true, skip listings whose Maps payload has no non-Maps website
    or social profile URL (Facebook, Instagram, etc.).

    ``exclude_keywords`` are used to skip listings whose name or address contains any excluded
    phrase (not sent to Serper — free-tier accounts reject ``-term`` query operators).
    """
    kw = (shop_keyword or "").strip()
    if not kw:
        raise ValueError("shop_keyword is required (non-empty).")
    kw = kw[:160]
    exclude_terms = _normalize_exclude_keywords(exclude_keywords)

    search_q = _build_search_q(
        city,
        query,
        shop_keyword=kw,
        state=state,
        country=country,
        exclude_keywords=exclude_terms,
    )
    city_clean = city.strip()[:255]
    state_clean = (state or "").strip()[:255]
    query_clean = ((query or "").strip() or kw)[:255]
    country_clean = (country or "").strip()[:255]
    search_city_db = city_clean or None
    search_state_db = state_clean or None
    search_query_db = query_clean or None
    search_country_db = country_clean or None
    errors: list[str] = []
    created = 0
    skipped_existing = 0
    skipped_duplicate_phone = 0
    skipped_no_website = 0
    skipped_excluded = 0
    places_seen = 0
    created_ids: list[int] = []
    record_pk = search_query_record.pk if search_query_record else None
    uncategorized_group = get_or_create_uncategorized_group()

    try:
        api_key = _serper_api_key()
    except ValueError as exc:
        return FetchLeadsResult(
            created=0,
            skipped_existing=0,
            errors=[str(exc)],
            places_seen=0,
            created_ids=[],
        )

    target = max(1, min(int(num), _hunt_max_results()))
    places, errors = _collect_serper_maps_places(
        search_q,
        target=target,
        country=country_clean,
        api_key=api_key,
        city=city_clean,
        state=state_clean,
    )
    if not places:
        return FetchLeadsResult(
            created=0,
            skipped_existing=0,
            errors=errors,
            places_seen=0,
            created_ids=[],
        )

    raw_places_count = len(places)
    for raw in places:
        normalized = _normalize_place_item(raw)
        if not normalized:
            continue
        if require_website and not _is_meaningful_online_presence(normalized["website"]):
            skipped_no_website += 1
            continue
        if _place_matches_exclude_keywords(normalized, exclude_terms):
            skipped_excluded += 1
            continue
        places_seen += 1
        pn = normalize_manual_phone(normalized["phone_number"]) or normalized["phone_number"]
        if pn and phone_exists_in_database(pn):
            skipped_duplicate_phone += 1
            continue
        defaults = {
            "phone_number": pn,
            "phone_numbers": [pn] if pn else [],
            "website": normalized["website"],
            "source_url": normalized["source_url"],
            "shop_keyword": kw,
            "category": classify_category_from_name(normalized["name"]),
            "group": uncategorized_group,
            "whatsapp_status": Lead.WhatsappStatus.IDLE,
            "is_processed": False,
            "is_chain": False,
            "search_city": search_city_db,
            "search_state": search_state_db,
            "search_query": search_query_db,
            "search_country": search_country_db,
        }
        if record_pk:
            defaults["search_query_record_id"] = record_pk
        try:
            lead, was_created = Lead.objects.get_or_create(
                name=normalized["name"],
                address=normalized["address"],
                defaults=defaults,
            )
        except Exception as exc:
            errors.append(f"DB error for {normalized['name']!r}: {exc}")
            logger.exception("Lead get_or_create failed")
            continue

        if was_created:
            created += 1
            created_ids.append(lead.pk)
            sync_chain_flags_for_name(normalized["name"])
        else:
            skipped_existing += 1
            update_fields: list[str] = []
            # Existing row: never change group, category, AI/processed flags, or shop_keyword here.
            # Only refresh hunt provenance + fill in contact gaps from the new Serper payload.
            lead.search_city = search_city_db
            lead.search_state = search_state_db
            lead.search_query = search_query_db
            lead.search_country = search_country_db
            update_fields.extend(["search_city", "search_state", "search_query", "search_country"])
            if record_pk:
                lead.search_query_record_id = record_pk
                update_fields.append("search_query_record_id")

            if normalized["phone_number"] and _contact_empty(lead.phone_number):
                if not (isinstance(getattr(lead, "phone_numbers", None), list) and any(
                    str(x).strip() for x in lead.phone_numbers
                )):
                    lead.phone_number = normalized["phone_number"]
                    lead.phone_numbers = [normalized["phone_number"]]
                    update_fields.extend(["phone_number", "phone_numbers"])
            if normalized["website"] and _contact_empty(lead.website):
                lead.website = normalized["website"]
                update_fields.append("website")
            if normalized["source_url"] and _contact_empty(lead.source_url):
                lead.source_url = normalized["source_url"]
                update_fields.append("source_url")
            try:
                lead.save(update_fields=update_fields)
            except Exception as exc:
                errors.append(f"Update failed for {lead.name!r}: {exc}")
                continue
            sync_chain_flags_for_name(normalized["name"])

    if require_website and raw_places_count > 0 and places_seen == 0:
        errors.append(
            f"All {raw_places_count} Serper listing(s) had no website/social URL in the payload. "
            'Uncheck "Website/social only" to import Maps-only rows, or widen the hunt.'
        )

    if exclude_terms and raw_places_count > 0 and places_seen == 0 and not errors:
        errors.append(
            f"All {raw_places_count} Serper listing(s) matched exclude keyword(s): "
            f"{', '.join(exclude_terms[:5])}."
        )

    return FetchLeadsResult(
        created=created,
        skipped_existing=skipped_existing,
        errors=errors,
        places_seen=places_seen,
        created_ids=created_ids,
        skipped_no_website=skipped_no_website,
        skipped_duplicate_phone=skipped_duplicate_phone,
        skipped_excluded=skipped_excluded,
    )
