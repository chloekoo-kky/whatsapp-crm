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
    return _env_value("YCLOUD_WABA_ID") or _env_value("WHATSAPP_BUSINESS_ACCOUNT_ID")


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
    language = str(row.get("language") or "en").strip()
    if language.lower() in ("en_us", "en"):
        language = "en"
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
    """List APPROVED WhatsApp templates from YCloud."""
    api_key = ycloud_api_key()
    if not api_key:
        raise ValueError("YCLOUD_API_KEY is required.")

    waba_id = ycloud_waba_id()
    with httpx.Client(timeout=45.0) as client:
        if waba_id:
            catalog = _fetch_approved_templates_page(client, waba_id=waba_id)
            if catalog:
                return catalog
            logger.warning(
                "No YCloud templates for WABA %s; retrying without WABA filter.",
                waba_id,
            )
        return _fetch_approved_templates_page(client)


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
