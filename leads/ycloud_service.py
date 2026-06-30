"""YCloud WhatsApp BSP API client (https://api.ycloud.com/v2)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from django.conf import settings

from leads.display import normalize_manual_phone

logger = logging.getLogger(__name__)

YCLOUD_API_BASE = "https://api.ycloud.com/v2"
YCLOUD_SEND_DIRECT_URL = f"{YCLOUD_API_BASE}/whatsapp/messages/sendDirectly"
YCLOUD_SEND_QUEUE_URL = f"{YCLOUD_API_BASE}/whatsapp/messages"
YCLOUD_TEMPLATES_URL = f"{YCLOUD_API_BASE}/whatsapp/templates"
YCLOUD_PHONE_NUMBERS_URL = f"{YCLOUD_API_BASE}/whatsapp/phoneNumbers"

_resolved_waba_cache: str = ""


def _normalize_credential(value: str | None) -> str:
    if not value:
        return ""
    return str(value).strip().replace("\r", "").replace("\n", "")


def _parse_env_file(path) -> dict[str, str]:
    from pathlib import Path

    env_path = Path(path)
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw_val = stripped.partition("=")
        key = key.strip()
        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key] = val
    return values


def _env_value(name: str) -> str:
    direct = _normalize_credential(os.getenv(name, ""))
    if direct:
        return direct
    direct = _normalize_credential(getattr(settings, name, None) or "")
    if direct:
        return direct
    file_vars = _parse_env_file(getattr(settings, "BASE_DIR", "") / ".env")
    return _normalize_credential(file_vars.get(name))


def ycloud_api_key() -> str:
    return _env_value("YCLOUD_API_KEY")


def ycloud_webhook_secret() -> str:
    return _env_value("YCLOUD_WEBHOOK_SECRET")


def ycloud_waba_id() -> str:
    resolved = resolve_sending_waba_id()
    if resolved:
        return resolved
    return _env_value("YCLOUD_WABA_ID") or _env_value("WHATSAPP_BUSINESS_ACCOUNT_ID")


def _phones_match_ycloud(a: str, b: str) -> bool:
    left = normalize_manual_phone(a) or (a or "").strip()
    right = normalize_manual_phone(b) or (b or "").strip()
    return bool(left and right and left == right)


def resolve_sending_waba_id(*, refresh: bool = False) -> str:
    """
    Resolve the WABA that owns ``WHATSAPP_FROM_NUMBER`` via YCloud phoneNumbers API.
    Falls back to ``YCLOUD_WABA_ID`` when the number cannot be matched.
    """
    global _resolved_waba_cache
    if _resolved_waba_cache and not refresh:
        return _resolved_waba_cache

    from_number = whatsapp_from_number()
    env_waba = _env_value("YCLOUD_WABA_ID") or _env_value("WHATSAPP_BUSINESS_ACCOUNT_ID")
    if not from_number:
        _resolved_waba_cache = env_waba
        return env_waba

    api_key = ycloud_api_key()
    if not api_key:
        _resolved_waba_cache = env_waba
        return env_waba

    page = 1
    limit = 100
    matched_waba = ""
    try:
        with httpx.Client(timeout=45.0) as client:
            while page <= 100:
                response = client.get(
                    YCLOUD_PHONE_NUMBERS_URL,
                    params={"page": page, "limit": limit},
                    headers=ycloud_headers(),
                )
                if response.status_code != 200:
                    logger.warning(
                        "YCloud phoneNumbers lookup failed: %s",
                        extract_ycloud_error(response),
                    )
                    break

                payload = response.json()
                items = payload.get("items") if isinstance(payload, dict) else []
                if not isinstance(items, list) or not items:
                    break

                for row in items:
                    if not isinstance(row, dict):
                        continue
                    candidate = (row.get("phoneNumber") or row.get("displayPhoneNumber") or "").strip()
                    if not _phones_match_ycloud(from_number, candidate):
                        continue
                    matched_waba = str(row.get("wabaId") or "").strip()
                    if matched_waba:
                        break
                if matched_waba:
                    break

                page_info = payload.get("page") if isinstance(payload, dict) else {}
                length = page_info.get("length") if isinstance(page_info, dict) else len(items)
                page_limit = page_info.get("limit") if isinstance(page_info, dict) else limit
                if not length or length < page_limit:
                    break
                page += 1
    except httpx.RequestError as exc:
        logger.warning("YCloud phoneNumbers lookup error: %s", exc)

    if matched_waba:
        if env_waba and env_waba != matched_waba:
            logger.warning(
                "YCLOUD_WABA_ID=%s does not match %s (resolved WABA %s). Using resolved WABA.",
                env_waba,
                from_number,
                matched_waba,
            )
        _resolved_waba_cache = matched_waba
        return matched_waba

    _resolved_waba_cache = env_waba
    return env_waba


def whatsapp_from_number() -> str:
    """Business sender line in E.164 (e.g. +60126336529)."""
    raw = _env_value("WHATSAPP_FROM_NUMBER") or _env_value("WHATSAPP_PHONE_NUMBER_ID")
    if not raw:
        return ""
    if raw.isdigit() or (raw.startswith("+") and raw[1:].isdigit()):
        return normalize_manual_phone(raw) or raw
    return raw


def resolve_ycloud_credentials() -> tuple[str, str]:
    """Return (api_key, from_number_e164)."""
    return ycloud_api_key(), whatsapp_from_number()


def ycloud_headers() -> dict[str, str]:
    return {
        "X-API-Key": ycloud_api_key(),
        "Content-Type": "application/json",
    }


def e164_recipient(phone: str) -> str:
    return normalize_manual_phone(phone) or ""


def extract_ycloud_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            msg = (err.get("message") or "").strip()
            code = err.get("code")
            parts = [part for part in (msg, f"code={code}" if code else "") if part]
            if parts:
                return " — ".join(parts)
        if isinstance(data, dict):
            wa_err = data.get("errorMessage") or data.get("errorCode")
            if wa_err:
                return str(wa_err)
    except ValueError:
        pass
    return (response.text or "").strip()[:2000] or f"HTTP {response.status_code}"


def message_id_from_response(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("wamid", "id"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def build_template_payload(
    *,
    from_number: str,
    to_number: str,
    template_name: str,
    language_code: str,
) -> dict[str, Any]:
    return {
        "from": from_number,
        "to": to_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }


def build_text_payload(*, from_number: str, to_number: str, body: str) -> dict[str, Any]:
    return {
        "from": from_number,
        "to": to_number,
        "type": "text",
        "text": {"body": (body or "").strip()},
    }


def send_message_directly(payload: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """
    POST /whatsapp/messages/sendDirectly — synchronous send.
    Returns (ok, error_detail, response_json).
    """
    api_key, from_number = resolve_ycloud_credentials()
    if not api_key or not from_number:
        missing = []
        if not api_key:
            missing.append("YCLOUD_API_KEY")
        if not from_number:
            missing.append("WHATSAPP_FROM_NUMBER")
        return False, f"YCloud is not configured (missing: {', '.join(missing)}).", {}

    payload = dict(payload)
    payload.setdefault("from", from_number)

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                YCLOUD_SEND_DIRECT_URL,
                json=payload,
                headers=ycloud_headers(),
            )
    except httpx.RequestError as exc:
        return False, str(exc), {}

    if response.status_code != 200:
        return False, extract_ycloud_error(response), {}

    try:
        return True, "", response.json()
    except ValueError:
        return True, "", {}


def _parse_template_row(row: dict[str, Any]) -> dict[str, Any] | None:
    status = (row.get("status") or "").upper()
    if status and status != "APPROVED":
        return None
    name = str(row.get("name") or "").strip()
    if not name:
        return None
    language = str(row.get("language") or "en").strip().replace("-", "_")
    body = ""
    components = row.get("components")
    if isinstance(components, list):
        for comp in components:
            if isinstance(comp, dict) and (comp.get("type") or "").upper() == "BODY":
                body = str(comp.get("text") or "").strip()[:500]
                break
    return {
        "name": name,
        "status": status or "APPROVED",
        "language": language,
        "body": body,
        "wabaId": str(row.get("wabaId") or "").strip(),
    }


def _fetch_approved_templates_page(
    client: httpx.Client, *, waba_id: str = ""
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": 100}
    if waba_id:
        params["filter.wabaId"] = waba_id

    catalog: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    offset = 0

    while True:
        page_params = {**params, "offset": offset}
        response = client.get(
            YCLOUD_TEMPLATES_URL,
            params=page_params,
            headers=ycloud_headers(),
        )
        if response.status_code != 200:
            raise ValueError(extract_ycloud_error(response))

        payload = response.json()
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            items = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            break

        for row in items:
            if not isinstance(row, dict):
                continue
            parsed = _parse_template_row(row)
            if not parsed:
                continue
            key = (parsed["name"], parsed["language"])
            if key in seen:
                continue
            seen.add(key)
            catalog.append(parsed)

        page = payload.get("page") if isinstance(payload, dict) else {}
        length = page.get("length") if isinstance(page, dict) else len(items)
        limit = page.get("limit") if isinstance(page, dict) else params["limit"]
        if not length or length < limit:
            break
        offset += int(length)

    catalog.sort(key=lambda t: (t["name"].lower(), t["language"]))
    return catalog


def fetch_approved_templates() -> list[dict[str, Any]]:
    """List APPROVED WhatsApp templates for the sending WABA (+6429 Coex line)."""
    api_key = ycloud_api_key()
    if not api_key:
        raise ValueError("YCLOUD_API_KEY is required.")

    waba_id = resolve_sending_waba_id(refresh=True)
    if not waba_id:
        raise ValueError(
            "Could not resolve WABA for WHATSAPP_FROM_NUMBER. Connect the number in YCloud "
            "or set YCLOUD_WABA_ID to the WABA shown on the YCloud channel."
        )

    with httpx.Client(timeout=45.0) as client:
        catalog = _fetch_approved_templates_page(client, waba_id=waba_id)

    if not catalog:
        raise ValueError(
            f"No approved templates on YCloud for WABA {waba_id}. "
            "Create and approve a template on this WABA, then click Update in the dashboard."
        )

    filtered = [
        row
        for row in catalog
        if not row.get("wabaId") or str(row.get("wabaId")).strip() == waba_id
    ]
    return filtered or catalog


def fetch_gateway_status() -> dict[str, Any]:
    api_key, from_number = resolve_ycloud_credentials()
    if api_key and from_number:
        return {"connected": True, "state": "open", "error": None}
    missing: list[str] = []
    if not api_key:
        missing.append("YCLOUD_API_KEY")
    if not from_number:
        missing.append("WHATSAPP_FROM_NUMBER")
    return {
        "connected": False,
        "state": "unconfigured",
        "error": f"Missing: {', '.join(missing)}" if missing else None,
    }
