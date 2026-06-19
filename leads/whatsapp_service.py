"""Meta WhatsApp Cloud API helpers and outbound first-touchpoint dispatch."""

from __future__ import annotations

import inspect
import logging
import os
import re
from datetime import datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from leads.chat_messages import record_outbound_chat_message
from leads.display import whatsapp_me_url
from leads.models import (
    Lead,
    LeadConversationLog,
    WhatsAppBatchSchedule,
    WhatsAppConfig,
    WhatsAppScriptTemplate,
)
from leads.pipeline import (
    QUEUE_GROUP_NAME,
    TRASH_GROUP_NAME,
    UNCATEGORIZED_GROUP_NAME,
)

logger = logging.getLogger(__name__)

OFFICIAL_API_MARKER = "[Official API]"
# Meta Business Manager approved outbound template (static — no body variables).
# Language must be ``en`` (English registration); ``en_US`` triggers Meta error 132001.
DEFAULT_META_TEMPLATE_NAME = "just_to_say_hi"
APPROVED_META_TEMPLATES = frozenset(
    {
        DEFAULT_META_TEMPLATE_NAME,
        "first_outreach",
        "follow_up_promo",
    }
)
APPROVED_META_TEMPLATE_CHOICES = (
    (DEFAULT_META_TEMPLATE_NAME, "just_to_say_hi (Default)"),
    ("first_outreach", "first_outreach"),
    ("follow_up_promo", "follow_up_promo"),
)
META_TEMPLATE_PREVIEW_BODIES = {
    DEFAULT_META_TEMPLATE_NAME: "Hello",
    "first_outreach": "Hi there — reaching out for the first time.",
    "follow_up_promo": "Following up with a quick promo update.",
}
META_OUTBOUND_TEMPLATE_LANGUAGE = "en"
GATEWAY_GUARD_LOG_PREFIX = "WhatsApp Gateway"
GATEWAY_NOT_READY_PREFIX = "Gateway not ready"
CRITICAL_DISPATCH_BLOCKED_MSG = (
    "[CRITICAL WARNING] Dispatched blocked! WhatsApp Cloud API credentials are "
    "missing or invalid. Outbound cancelled."
)
QUALITY_LEADS_GROUP_NAME = "Quality Leads"
COLD_SAFETY_GROUP_NAMES = frozenset(
    {QUALITY_LEADS_GROUP_NAME, UNCATEGORIZED_GROUP_NAME}
)
SUSPICIOUS_COLD_KEYWORDS = (
    "click here",
    "buy now",
    "limited time",
    "act now",
    "free money",
    "congratulations",
    "you have won",
    "urgent",
    "discount",
    "% off",
    "promo code",
    "subscribe now",
)

QUEUE_EMPTY_SLEEP_SECONDS = 60
RESTRICTED_DAY_SLEEP_SECONDS = 10 * 60
OUTSIDE_WINDOW_POLL_SECONDS = 5 * 60
PAUSED_SLEEP_SECONDS = 60


def campaign_timezone() -> ZoneInfo:
    tz_name = getattr(settings, "WHATSAPP_CAMPAIGN_TIMEZONE", "Asia/Kuala_Lumpur")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Asia/Kuala_Lumpur")


def now_campaign_local() -> datetime:
    return timezone.now().astimezone(campaign_timezone())


def _normalize_credential(value: str | None) -> str:
    """Trim outer whitespace only — do not slice or alter token body."""
    if not value:
        return ""
    return str(value).strip().replace("\r", "").replace("\n", "")


def _parse_env_file(path) -> dict[str, str]:
    """Parse KEY=VALUE lines from a .env file (no caching, no django-environ)."""
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


def meta_access_token() -> str:
    """Official Meta Graph API bearer token — ``WHATSAPP_ACCESS_TOKEN`` only."""
    token = _sanitize_meta_access_token(os.getenv("WHATSAPP_ACCESS_TOKEN", ""))
    if not token:
        token = _sanitize_meta_access_token(
            getattr(settings, "WHATSAPP_ACCESS_TOKEN", None) or ""
        )
    if token:
        return _normalize_credential(token)
    file_vars = _parse_env_file(getattr(settings, "BASE_DIR", "") / ".env")
    return _sanitize_meta_access_token(
        _normalize_credential(file_vars.get("WHATSAPP_ACCESS_TOKEN"))
    )


def meta_phone_number_id() -> str:
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not phone_id:
        phone_id = (getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None) or "").strip()
    if phone_id:
        return _normalize_credential(phone_id)
    file_vars = _parse_env_file(getattr(settings, "BASE_DIR", "") / ".env")
    return _normalize_credential(file_vars.get("WHATSAPP_PHONE_NUMBER_ID"))


def resolve_meta_dispatch_credentials() -> tuple[str, str]:
    """Live Meta Cloud API credentials at POST time (no Evolution legacy keys)."""
    return meta_access_token(), meta_phone_number_id()


def whatsapp_access_token() -> str:
    return meta_access_token()


def whatsapp_phone_number_id() -> str:
    return meta_phone_number_id()


def whatsapp_graph_api_version() -> str:
    raw = os.environ.get("WHATSAPP_GRAPH_API_VERSION") or "v20.0"
    return raw.strip() or "v20.0"


def meta_messages_url(*, phone_id: str) -> str:
    version = whatsapp_graph_api_version()
    return f"https://graph.facebook.com/{version}/{phone_id}/messages"


def meta_graph_url(path: str) -> str:
    version = whatsapp_graph_api_version()
    return f"https://graph.facebook.com/{version}/{path.lstrip('/')}"


def meta_waba_id() -> str:
    """Optional ``WHATSAPP_BUSINESS_ACCOUNT_ID``; otherwise resolved via phone number ID."""
    waba = _normalize_credential(os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", ""))
    if not waba:
        waba = _normalize_credential(
            getattr(settings, "WHATSAPP_BUSINESS_ACCOUNT_ID", None) or ""
        )
    if waba:
        return waba
    file_vars = _parse_env_file(getattr(settings, "BASE_DIR", "") / ".env")
    return _normalize_credential(file_vars.get("WHATSAPP_BUSINESS_ACCOUNT_ID"))


def _sanitize_meta_access_token(raw_token: str) -> str:
    """Strip whitespace and correct known corrupted token segment before Graph API calls."""
    token = (raw_token or "").strip()
    if "EAAOkG95CGZAYBRv3Z" in token:
        token = token.replace("EAAOkG95CGZAYBRv3Z", "EAAOkG95CGZAYBR3Z")
    return token


def _runtime_meta_bearer_header() -> str:
    """Build Authorization value directly from process env immediately before HTTP dispatch."""
    raw_token = _sanitize_meta_access_token(os.getenv("WHATSAPP_ACCESS_TOKEN", ""))
    return f"Bearer {raw_token}"


def _apply_runtime_auth_header_override(headers: dict[str, str]) -> None:
    """Force sanitized Bearer token onto headers dict right before Meta HTTP request."""
    headers["Authorization"] = _runtime_meta_bearer_header()


def meta_dispatch_headers() -> dict[str, str]:
    """Bearer header for Graph API — strictly ``WHATSAPP_ACCESS_TOKEN`` (never Evolution keys)."""
    return {
        "Authorization": _runtime_meta_bearer_header(),
        "Content-Type": "application/json",
    }


def print_meta_http_tracking_debug(headers: dict[str, str]) -> None:
    """Emit runtime credential diagnostics to stdout (Docker/gunicorn console)."""
    raw_env_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    sanitized_token = _sanitize_meta_access_token(raw_env_token)
    settings_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "NOT DEFINED")
    legacy_key = os.getenv("WHATSAPP_API_GLOBAL_API_KEY")
    active_auth_header = headers.get("Authorization", "MISSING")

    print("\n" + "=" * 60)
    print("[TRACKING DETECTED] A Meta Cloud API call is firing right now!")
    print(f"[ENV EVALUATION] os.getenv('WHATSAPP_ACCESS_TOKEN'): {str(raw_env_token)[:15]}...")
    print(
        f"[SANITIZED TOKEN] chars 15-20 after override: "
        f"{repr(sanitized_token[15:21]) if len(sanitized_token) > 15 else 'n/a'}"
    )
    print(f"[SETTINGS EVALUATION] settings.WHATSAPP_ACCESS_TOKEN: {str(settings_token)[:15]}...")
    print(f"[LEGACY CHECK] os.getenv('WHATSAPP_API_GLOBAL_API_KEY'): {str(legacy_key)[:15]}...")
    print(f"[ACTUAL HEADER SENT TO META] -> {active_auth_header[:25]}...")
    print("=" * 60 + "\n")


def meta_dispatch_origin_label() -> str:
    """Return ``leads/views.py -> whatsapp_force_send`` for the active dispatch caller."""
    for frame_info in inspect.stack()[1:]:
        path = frame_info.filename.replace("\\", "/")
        if path.endswith("whatsapp_service.py"):
            continue
        idx = path.rfind("leads/")
        rel_path = path[idx:] if idx >= 0 else path.split("/")[-1]
        return f"{rel_path} -> {frame_info.function}"
    return "unknown -> unknown"


def append_meta_dispatch_origin(detail: str) -> str:
    """Append caller file/function so Live Activity shows where Meta dispatch failed."""
    origin = meta_dispatch_origin_label()
    return f"{detail} (Triggered inside {origin})"


def _approved_templates_from_config(config: WhatsAppConfig) -> list[dict[str, Any]]:
    raw = config.meta_message_templates
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and (item.get("name") or "").strip():
            out.append(item)
    return out


def known_meta_template_names() -> frozenset[str]:
    config = WhatsAppConfig.load()
    synced = {str(t["name"]).strip() for t in _approved_templates_from_config(config)}
    if synced:
        return frozenset(synced | set(APPROVED_META_TEMPLATES))
    return APPROVED_META_TEMPLATES


def _meta_template_body_from_components(components: Any) -> str:
    if not isinstance(components, list):
        return ""
    for comp in components:
        if not isinstance(comp, dict):
            continue
        if (comp.get("type") or "").upper() == "BODY":
            text = (comp.get("text") or "").strip()
            if text:
                return text[:500]
    return ""


def _normalize_meta_template_language(language: str) -> str:
    lang = (language or "").strip().replace("-", "_")
    if not lang:
        return META_OUTBOUND_TEMPLATE_LANGUAGE
    if lang.lower() in ("en_us", "en"):
        return "en"
    return lang


def meta_template_choices_for_ui() -> tuple[tuple[str, str], ...]:
    """Dropdown choices: synced Meta catalog when present, else built-in defaults."""
    config = WhatsAppConfig.load()
    templates = [
        t for t in _approved_templates_from_config(config)
        if (t.get("status") or "APPROVED").upper() == "APPROVED"
    ]
    if not templates:
        return APPROVED_META_TEMPLATE_CHOICES

    choices: list[tuple[str, str]] = []
    for item in sorted(templates, key=lambda t: str(t.get("name") or "").lower()):
        name = str(item["name"]).strip()
        lang = _normalize_meta_template_language(str(item.get("language") or ""))
        if name == DEFAULT_META_TEMPLATE_NAME:
            label = f"{name} (Default · {lang})"
        else:
            label = f"{name} ({lang})"
        choices.append((name, label))
    return tuple(choices)


def meta_template_language_for_name(template_name: str | None) -> str:
    name = (template_name or "").strip()
    if not name:
        return META_OUTBOUND_TEMPLATE_LANGUAGE
    config = WhatsAppConfig.load()
    for item in _approved_templates_from_config(config):
        if str(item.get("name") or "").strip() == name:
            return _normalize_meta_template_language(str(item.get("language") or ""))
    return META_OUTBOUND_TEMPLATE_LANGUAGE


def _resolve_waba_id_for_templates(*, token: str, phone_id: str) -> str:
    waba = meta_waba_id()
    if waba:
        return waba
    url = meta_graph_url(phone_id)
    headers = {"Authorization": f"Bearer {_sanitize_meta_access_token(token)}"}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params={"fields": "whatsapp_business_account"}, headers=headers)
    except httpx.RequestError as exc:
        raise ValueError(f"Could not resolve WhatsApp Business Account: {exc}") from exc
    if response.status_code != 200:
        raise ValueError(extract_meta_error(response) or f"HTTP {response.status_code}")
    data = response.json()
    waba_node = data.get("whatsapp_business_account")
    if isinstance(waba_node, dict):
        waba_id = str(waba_node.get("id") or "").strip()
        if waba_id:
            return waba_id
    waba_id = str(data.get("id") or "").strip()
    if waba_id and waba_id != phone_id:
        return waba_id
    raise ValueError("WhatsApp Business Account ID not found for this phone number.")


def fetch_meta_message_templates_from_api() -> list[dict[str, Any]]:
    """List APPROVED message templates from Meta Graph API."""
    token, phone_id = resolve_meta_dispatch_credentials()
    if not token or not phone_id:
        raise ValueError("WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required.")

    waba_id = _resolve_waba_id_for_templates(token=token, phone_id=phone_id)
    headers = meta_dispatch_headers()
    url = meta_graph_url(f"{waba_id}/message_templates")
    params: dict[str, Any] = {
        "limit": 100,
        "fields": "name,status,language,components",
    }

    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    next_url: str | None = url
    next_params: dict[str, Any] | None = params

    with httpx.Client(timeout=45.0) as client:
        while next_url:
            response = client.get(
                next_url,
                params=next_params,
                headers=headers,
            )
            if response.status_code != 200:
                raise ValueError(extract_meta_error(response) or f"HTTP {response.status_code}")
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    status = (row.get("status") or "").upper()
                    if status and status != "APPROVED":
                        continue
                    name = str(row.get("name") or "").strip()
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    catalog.append(
                        {
                            "name": name,
                            "status": status or "APPROVED",
                            "language": _normalize_meta_template_language(
                                str(row.get("language") or "")
                            ),
                            "body": _meta_template_body_from_components(row.get("components")),
                        }
                    )
            paging = payload.get("paging") if isinstance(payload, dict) else {}
            next_link = paging.get("next") if isinstance(paging, dict) else None
            next_url = str(next_link).strip() if next_link else None
            next_params = None

    catalog.sort(key=lambda t: t["name"].lower())
    return catalog


def sync_meta_message_templates_to_config() -> tuple[int, str | None]:
    """Refresh ``WhatsAppConfig.meta_message_templates`` from Meta. Returns (count, error)."""
    try:
        catalog = fetch_meta_message_templates_from_api()
    except Exception as exc:
        logger.warning("Meta template sync failed: %s", exc)
        return 0, str(exc)

    if not catalog:
        return 0, "No approved message templates returned by Meta."

    config = WhatsAppConfig.load()
    config.meta_message_templates = catalog
    config.meta_templates_synced_at = timezone.now()
    active = normalize_outbound_template_name(config.outbound_template_name)
    if active not in {t["name"] for t in catalog}:
        config.outbound_template_name = DEFAULT_META_TEMPLATE_NAME
    config.save(
        update_fields=[
            "meta_message_templates",
            "meta_templates_synced_at",
            "outbound_template_name",
        ]
    )
    return len(catalog), None


def normalize_outbound_template_name(name: str) -> str:
    """Return a known Meta template name, falling back to the default."""
    cleaned = (name or "").strip()
    if cleaned in known_meta_template_names():
        return cleaned
    return DEFAULT_META_TEMPLATE_NAME


def get_active_config_template_name() -> str:
    """Active outbound template from ``WhatsAppConfig`` (default ``just_to_say_hi``)."""
    config = WhatsAppConfig.load()
    return normalize_outbound_template_name(config.outbound_template_name)


def meta_template_preview_body(template_name: str | None = None) -> str:
    """Human-readable snapshot of the selected Meta template body."""
    name = normalize_outbound_template_name(template_name or get_active_config_template_name())
    config = WhatsAppConfig.load()
    for item in _approved_templates_from_config(config):
        if str(item.get("name") or "").strip() == name:
            body = (item.get("body") or "").strip()
            if body:
                return body
    return META_TEMPLATE_PREVIEW_BODIES.get(name, META_TEMPLATE_PREVIEW_BODIES[DEFAULT_META_TEMPLATE_NAME])


def whatsapp_template_name() -> str:
    """Meta-approved template name selected in campaign configuration."""
    return get_active_config_template_name()


def whatsapp_template_language() -> str:
    """Meta template language code for the active configured template."""
    return meta_template_language_for_name(get_active_config_template_name())


def _digits_for_whatsapp(phone: str) -> str:
    url = whatsapp_me_url(phone or "")
    if not url:
        return ""
    return url.rsplit("/", 1)[-1]


def primary_phone(lead: Lead) -> str:
    primary = (lead.phone_number or "").strip()
    if primary:
        return primary
    numbers = lead.phone_numbers if isinstance(lead.phone_numbers, list) else []
    for raw in numbers:
        candidate = str(raw or "").strip()
        if candidate:
            return candidate
    return ""


def _mask_phone_for_activity_log(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) <= 6:
        return digits or "unknown"
    if len(digits) <= 8:
        return f"{digits[:4]}XXXX"
    return f"{digits[:4]}{'X' * (len(digits) - 7)}{digits[-3:]}"


SCRIPT_TEMPLATE_FALLBACK_GROUP = "General Outreach"
SCRIPT_SYSTEM_GROUP_NAMES = frozenset(
    {
        UNCATEGORIZED_GROUP_NAME,
        QUEUE_GROUP_NAME,
        TRASH_GROUP_NAME,
    }
)

DEFAULT_OUTREACH_SCRIPT = (
    "Hi {{ name }},\n\n"
    "I came across your business in {{ area }} and wanted to reach out.\n\n"
    "Would you be open to a quick chat?"
)


def lead_city_area(lead: Lead) -> str:
    city = (lead.search_city or "").strip()
    if city:
        return city
    address = (lead.address or "").strip()
    if not address:
        return "your area"
    first_line = address.split("\n", 1)[0].strip()
    if len(first_line) > 80:
        return first_line[:77] + "..."
    return first_line or "your area"


def script_group_name_for_lead(lead: Lead) -> str:
    if lead.group_id and lead.group:
        group_name = (lead.group.name or "").strip()
        if group_name and group_name not in SCRIPT_SYSTEM_GROUP_NAMES:
            return group_name
    category = (lead.category or "").strip().lower()
    if category and category != Lead.Category.UNKNOWN:
        return lead.get_category_display()
    return SCRIPT_TEMPLATE_FALLBACK_GROUP


def render_script_template(template_text: str, lead: Lead) -> str:
    area = lead_city_area(lead)
    rendered = template_text
    rendered = rendered.replace("{{ name }}", lead.name or "")
    rendered = rendered.replace("{{ area }}", area)
    rendered = rendered.replace("{{name}}", lead.name or "")
    rendered = rendered.replace("{{area}}", area)
    return rendered.strip()


def _script_template_text(group_name: str) -> str:
    row = WhatsAppScriptTemplate.objects.filter(group_name=group_name).first()
    if row and (row.template_text or "").strip():
        return row.template_text.strip()
    return ""


def compose_outbound_message(lead: Lead) -> str:
    draft = (lead.whatsapp_draft or "").strip()
    if draft:
        return draft

    group_name = script_group_name_for_lead(lead)
    template_text = _script_template_text(group_name)
    if not template_text:
        template_text = _script_template_text(SCRIPT_TEMPLATE_FALLBACK_GROUP)
    if not template_text:
        template_text = DEFAULT_OUTREACH_SCRIPT
    return render_script_template(template_text, lead)


def _lead_group_name(lead: Lead) -> str:
    if lead.group_id and lead.group:
        return (lead.group.name or "").strip()
    return ""


def lead_requires_cold_copy_sanitization(lead: Lead) -> bool:
    if lead.conversation_logs.exists():
        return False
    group_name = _lead_group_name(lead).lower()
    return group_name in {name.lower() for name in COLD_SAFETY_GROUP_NAMES}


def sanitize_cold_outbound_copy(text: str) -> str:
    cleaned = re.sub(r"https?://\S+", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"www\.\S+", "", cleaned, flags=re.IGNORECASE)
    for keyword in SUSPICIOUS_COLD_KEYWORDS:
        cleaned = re.sub(re.escape(keyword), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def build_message_body(lead: Lead) -> str:
    """Preview copy for dashboard script editors (Meta sends approved templates)."""
    body = compose_outbound_message(lead)
    if lead_requires_cold_copy_sanitization(lead):
        body = sanitize_cold_outbound_copy(body)
    return body


def template_clinic_name(lead: Lead) -> str:
    """Dynamic {{1}} body parameter for parameterized Meta templates."""
    return (lead.name or "your business").strip()[:256]


def build_meta_template_payload(lead: Lead, *, template_name: str | None = None) -> dict[str, Any]:
    """
    Meta template payload (static body, no components). Uses ``template_name`` when
    provided (per-batch override), otherwise the active configured template.
    """
    number = _digits_for_whatsapp(primary_phone(lead))
    if template_name:
        selected_template = normalize_outbound_template_name(template_name)
    else:
        selected_template = get_active_config_template_name()
    language_code = meta_template_language_for_name(selected_template)
    return {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "template",
        "template": {
            "name": selected_template,
            "language": {"code": language_code},
        },
    }


def is_dispatch_blocked_detail(detail: str) -> bool:
    message = (detail or "").strip()
    return (
        message.startswith(GATEWAY_NOT_READY_PREFIX)
        or message.startswith("[CRITICAL WARNING]")
    )


def fetch_gateway_status() -> dict[str, Any]:
    """Cloud API readiness: configured when live env token + phone number ID exist."""
    token, phone_id = resolve_meta_dispatch_credentials()
    if token and phone_id:
        return {
            "connected": True,
            "state": "open",
            "error": None,
        }

    missing: list[str] = []
    if not token:
        missing.append("WHATSAPP_ACCESS_TOKEN")
    if not phone_id:
        missing.append("WHATSAPP_PHONE_NUMBER_ID")
    return {
        "connected": False,
        "state": "unconfigured",
        "error": f"Missing: {', '.join(missing)}" if missing else None,
    }


def connection_state_label(state_info: dict[str, Any]) -> str:
    if state_info.get("connected"):
        return "CONNECTED"
    if state_info.get("error"):
        return "UNCONFIGURED"
    return "UNCONFIGURED"


def gateway_send_ready() -> tuple[bool, str]:
    state_info = fetch_gateway_status()
    if connection_state_label(state_info) == "CONNECTED":
        return True, ""

    err = (state_info.get("error") or "").strip()
    detail = CRITICAL_DISPATCH_BLOCKED_MSG
    if err:
        detail = f"{detail} ({err})"
    return False, detail


def extract_meta_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error", {})
        if isinstance(err, dict):
            msg = (err.get("message") or err.get("error_user_msg") or "").strip()
            code = err.get("code")
            subcode = err.get("error_subcode")
            parts = [part for part in (msg, f"code={code}" if code else "", f"subcode={subcode}" if subcode else "") if part]
            if parts:
                return " — ".join(parts)
    except ValueError:
        pass
    return (response.text or "").strip()[:2000] or f"HTTP {response.status_code}"


def record_whatsapp_activity_warning(message: str, *, lead: Optional[Lead] = None) -> None:
    target = lead
    if target is None:
        target = (
            Lead.objects.filter(whatsapp_status=Lead.WhatsappStatus.PENDING)
            .order_by("created_at", "id")
            .first()
        )
    if target is None:
        target = Lead.objects.order_by("id").first()
    if target is None:
        logger.warning("WhatsApp activity warning (no lead to attach): %s", message)
        return

    LeadConversationLog.objects.create(
        lead=target,
        conversation_date=timezone.now().date(),
        remarks=f"{GATEWAY_GUARD_LOG_PREFIX} — {message}",
    )


def build_official_dispatch_remark(lead: Lead) -> str:
    phone = _mask_phone_for_activity_log(primary_phone(lead))
    return f"{OFFICIAL_API_MARKER} Template successfully delivered to {phone}"


def queue_counts() -> dict[str, int]:
    base = Lead.objects.exclude(group__name=TRASH_GROUP_NAME)
    return {
        "pending": base.filter(whatsapp_status=Lead.WhatsappStatus.PENDING).count(),
        "processing": base.filter(whatsapp_status=Lead.WhatsappStatus.PROCESSING).count(),
        "sent": base.filter(whatsapp_status=Lead.WhatsappStatus.SENT).count(),
        "failed": base.filter(whatsapp_status=Lead.WhatsappStatus.FAILED).count(),
    }


def reset_campaign_metrics_snapshot() -> dict[str, int]:
    base = Lead.objects.exclude(group__name=TRASH_GROUP_NAME)
    requeue_statuses = (
        Lead.WhatsappStatus.FAILED,
        Lead.WhatsappStatus.SENT,
        Lead.WhatsappStatus.PROCESSING,
    )
    base.filter(whatsapp_status__in=requeue_statuses).update(
        whatsapp_status=Lead.WhatsappStatus.PENDING,
        whatsapp_last_error="",
        whatsapp_sent_at=None,
        whatsapp_instance_id="",
    )
    return queue_counts()


def campaign_metrics() -> dict[str, Any]:
    counts = queue_counts()
    total_with_phone = Lead.objects.exclude(phone_number="").count()
    sent = counts["sent"]
    response_rate = None
    if sent:
        logs = LeadConversationLog.objects.filter(
            remarks__icontains=OFFICIAL_API_MARKER
        ).count()
        response_rate = round((logs / max(sent, 1)) * 100, 1)
    return {
        **counts,
        "total_with_phone": total_with_phone,
        "response_baseline_pct": response_rate,
    }


def mark_sent(
    lead: Lead,
    phone_number_id: str,
    *,
    priority: bool = False,
    meta_message_id: str = "",
) -> None:
    now = timezone.now()
    lead.whatsapp_status = Lead.WhatsappStatus.SENT
    lead.whatsapp_sent_at = now
    lead.whatsapp_instance_id = phone_number_id
    lead.whatsapp_last_error = ""
    lead.save(
        update_fields=[
            "whatsapp_status",
            "whatsapp_sent_at",
            "whatsapp_instance_id",
            "whatsapp_last_error",
        ]
    )
    remark = build_official_dispatch_remark(lead)
    if priority:
        remark = f"Priority Force Trigger — {remark}"
    LeadConversationLog.objects.create(
        lead=lead,
        conversation_date=now.date(),
        remarks=remark,
    )
    record_outbound_chat_message(
        lead,
        template_name=whatsapp_template_name(),
        body=build_message_body(lead),
        meta_message_id=meta_message_id,
    )


def mark_failed(lead: Lead, error_message: str) -> None:
    lead.whatsapp_status = Lead.WhatsappStatus.FAILED
    lead.whatsapp_last_error = (error_message or "Unknown error")[:4000]
    lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])


def send_text_to_lead(
    lead: Lead, *, priority: bool = False, template_name: str | None = None
) -> tuple[bool, str]:
    """Dispatch a Meta template (per-batch ``template_name`` or the config default)."""
    token, phone_id = resolve_meta_dispatch_credentials()
    if not token or not phone_id:
        detail = "WhatsApp Cloud API is not configured."
        record_whatsapp_activity_warning(detail, lead=lead)
        mark_failed(lead, detail)
        return False, detail

    ready, guard_msg = gateway_send_ready()
    if not ready:
        record_whatsapp_activity_warning(guard_msg, lead=lead)
        return False, guard_msg

    phone_raw = primary_phone(lead)
    number = _digits_for_whatsapp(phone_raw)
    if not number:
        mark_failed(lead, "No valid phone number on lead.")
        return False, "No valid phone number on lead."

    payload = build_meta_template_payload(lead, template_name=template_name)
    url = meta_messages_url(phone_id=phone_id)
    headers = meta_dispatch_headers()
    _apply_runtime_auth_header_override(headers)
    logger.info("Meta Graph API POST %s (phone_number_id=%s)", url, phone_id)
    print_meta_http_tracking_debug(headers)

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        detail = append_meta_dispatch_origin(str(exc))
        record_whatsapp_activity_warning(f"Meta API network error: {detail}", lead=lead)
        mark_failed(lead, detail)
        return False, detail

    if response.status_code == 200:
        meta_message_id = ""
        try:
            payload = response.json()
            messages = payload.get("messages") if isinstance(payload, dict) else None
            if isinstance(messages, list) and messages:
                meta_message_id = str(messages[0].get("id") or "").strip()
        except ValueError:
            pass
        mark_sent(
            lead,
            phone_id,
            priority=priority,
            meta_message_id=meta_message_id,
        )
        return True, ""

    detail = append_meta_dispatch_origin(extract_meta_error(response))
    record_whatsapp_activity_warning(f"Meta API error: {detail}", lead=lead)
    mark_failed(lead, detail)
    return False, detail


def build_meta_free_text_payload(lead: Lead, text: str) -> dict[str, Any]:
    """Meta Cloud API payload for a session free-form text reply (24h window)."""
    number = _digits_for_whatsapp(primary_phone(lead))
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "text",
        "text": {"body": (text or "").strip()},
    }


def send_free_text_to_lead(lead: Lead, text: str) -> tuple[bool, str, Optional["ChatMessage"]]:
    """
    Send a free-form WhatsApp text within the Meta 24h customer service window.
    Returns (ok, error_detail, ChatMessage|None).
    """
    body = (text or "").strip()
    if not body:
        return False, "Message cannot be empty.", None

    token, phone_id = resolve_meta_dispatch_credentials()
    if not token or not phone_id:
        detail = "WhatsApp Cloud API is not configured."
        record_whatsapp_activity_warning(detail, lead=lead)
        return False, detail, None

    ready, guard_msg = gateway_send_ready()
    if not ready:
        record_whatsapp_activity_warning(guard_msg, lead=lead)
        return False, guard_msg, None

    number = _digits_for_whatsapp(primary_phone(lead))
    if not number:
        return False, "No valid phone number on lead.", None

    payload = build_meta_free_text_payload(lead, body)
    url = meta_messages_url(phone_id=phone_id)
    headers = meta_dispatch_headers()
    _apply_runtime_auth_header_override(headers)

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        detail = append_meta_dispatch_origin(str(exc))
        record_whatsapp_activity_warning(f"Meta API network error: {detail}", lead=lead)
        return False, detail, None

    if response.status_code != 200:
        detail = append_meta_dispatch_origin(extract_meta_error(response))
        record_whatsapp_activity_warning(f"Meta API error: {detail}", lead=lead)
        return False, detail, None

    meta_message_id = ""
    try:
        data = response.json()
        messages = data.get("messages") if isinstance(data, dict) else None
        if isinstance(messages, list) and messages:
            meta_message_id = str(messages[0].get("id") or "").strip()
    except ValueError:
        pass

    now = timezone.now()
    LeadConversationLog.objects.create(
        lead=lead,
        conversation_date=now.date(),
        remarks=f"[WhatsApp · agent] {body}",
    )
    chat_msg = record_outbound_chat_message(
        lead,
        template_name="",
        body=body,
        meta_message_id=meta_message_id,
    )
    return True, "", chat_msg


def _time_in_window(now_t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_t <= end
    return now_t >= start or now_t <= end


def _combine_local(day: datetime.date, t: time) -> datetime:
    tz = campaign_timezone()
    return datetime.combine(day, t, tzinfo=tz)


def seconds_until_next_allowed_slot(config: WhatsAppConfig, now_local: datetime) -> int:
    allowed = set(config.normalized_allowed_days())
    if not allowed:
        return OUTSIDE_WINDOW_POLL_SECONDS

    for day_offset in range(0, 8):
        day = (now_local.date() + timedelta(days=day_offset))
        weekday = day.isoweekday()
        if weekday not in allowed:
            continue

        windows = [
            (config.window1_start, config.window1_end),
            (config.window2_start, config.window2_end),
        ]
        for start, end in windows:
            if start is None or end is None:
                continue
            window_start = _combine_local(day, start)
            window_end = _combine_local(day, end)
            if day_offset == 0:
                if now_local < window_start:
                    return min(
                        int((window_start - now_local).total_seconds()),
                        OUTSIDE_WINDOW_POLL_SECONDS,
                    )
                if window_start <= now_local <= window_end:
                    return 0
            else:
                return min(
                    int((window_start - now_local).total_seconds()),
                    OUTSIDE_WINDOW_POLL_SECONDS,
                )

    return RESTRICTED_DAY_SLEEP_SECONDS


def evaluate_campaign_gate(config: WhatsAppConfig) -> tuple[str, int, str]:
    now_local = now_campaign_local()

    if config.is_paused:
        return "sleep", PAUSED_SLEEP_SECONDS, "Campaign paused globally."

    weekday = now_local.isoweekday()
    allowed = set(config.normalized_allowed_days())
    if weekday not in allowed:
        return (
            "sleep",
            RESTRICTED_DAY_SLEEP_SECONDS,
            f"Today is a restricted day (weekday={weekday}).",
        )

    now_t = now_local.time()
    in_window = _time_in_window(now_t, config.window1_start, config.window1_end) or _time_in_window(
        now_t, config.window2_start, config.window2_end
    )
    if not in_window:
        sleep_for = seconds_until_next_allowed_slot(config, now_local)
        sleep_for = max(sleep_for, OUTSIDE_WINDOW_POLL_SECONDS)
        return (
            "sleep",
            sleep_for,
            "Outside allowed marketing windows. Calculating sleep time...",
        )

    return "proceed", 0, ""


def claim_next_pending_lead() -> Optional[Lead]:
    """Atomically claim the oldest PENDING lead with a usable phone (FIFO).

    Flips it to PROCESSING under ``select_for_update(skip_locked=True)`` so
    concurrent workers/batches never grab the same lead.
    """
    with transaction.atomic():
        lead = (
            Lead.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(whatsapp_status=Lead.WhatsappStatus.PENDING)
            .exclude(group__name=TRASH_GROUP_NAME)
            .filter(Q(phone_number__gt="") | Q(phone_numbers__0__isnull=False))
            .order_by("created_at", "id")
            .first()
        )
        if lead is None:
            return None
        lead.whatsapp_status = Lead.WhatsappStatus.PROCESSING
        lead.whatsapp_last_error = ""
        lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
        return lead


def claim_next_pending_lead_for_batch(batch_id: int) -> Optional[Lead]:
    """Atomically claim the oldest PENDING lead assigned to ``batch_id``."""
    with transaction.atomic():
        lead = (
            Lead.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(
                whatsapp_batches=batch_id,
                whatsapp_status=Lead.WhatsappStatus.PENDING,
            )
            .exclude(group__name=TRASH_GROUP_NAME)
            .filter(Q(phone_number__gt="") | Q(phone_numbers__0__isnull=False))
            .order_by("created_at", "id")
            .first()
        )
        if lead is None:
            return None
        lead.whatsapp_status = Lead.WhatsappStatus.PROCESSING
        lead.whatsapp_last_error = ""
        lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
        return lead


def clear_pending_batch_memberships(lead_ids) -> int:
    """Detach the given leads from any still-PENDING batch.

    Used when a lead leaves the outbound queue (dequeue / trash / pause) before
    its batch has been sent — a pending-batch assignment only makes sense while
    the lead is queued. Completed/cancelled batch history is preserved. Returns
    the number of (lead, batch) memberships removed.
    """
    if isinstance(lead_ids, int):
        lead_ids = [lead_ids]
    lead_ids = [int(x) for x in lead_ids]
    if not lead_ids:
        return 0
    through = Lead.whatsapp_batches.through
    qs = through.objects.filter(
        lead_id__in=lead_ids,
        whatsappbatchschedule__status=WhatsAppBatchSchedule.Status.PENDING,
    )
    removed = qs.count()
    if removed:
        qs.delete()
    return removed


def dispatch_pending_batch(
    limit: int, *, template_name: str | None = None, priority: bool = False
) -> int:
    """Send the Meta template to up to ``limit`` oldest PENDING leads (ad-hoc).

    Returns the number of leads dispatched successfully. A lead that is blocked
    (gateway not ready) is returned to PENDING so it can be retried later.
    """
    sent = 0
    attempts = 0
    max_attempts = max(0, int(limit))
    while sent < max_attempts and attempts < max_attempts:
        attempts += 1
        lead = claim_next_pending_lead()
        if lead is None:
            break
        ok, detail = send_text_to_lead(lead, priority=priority, template_name=template_name)
        if ok:
            sent += 1
            continue
        if is_dispatch_blocked_detail(detail):
            # Gateway not ready — release the lead back to the queue and stop.
            lead.whatsapp_status = Lead.WhatsappStatus.PENDING
            lead.whatsapp_last_error = detail[:4000]
            lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
            break
        # Hard failure (mark_failed already applied inside send_text_to_lead).
    return sent


def dispatch_assigned_batch(batch: WhatsAppBatchSchedule) -> int:
    """Send the batch template to every PENDING lead assigned to this batch.

    Returns the number dispatched successfully. Stops early if the gateway is
    not ready (the remaining leads stay PENDING for the next run).
    """
    sent = 0
    template_name = batch.outbound_template_name
    while True:
        lead = claim_next_pending_lead_for_batch(batch.pk)
        if lead is None:
            break
        ok, detail = send_text_to_lead(lead, template_name=template_name)
        if ok:
            sent += 1
            continue
        if is_dispatch_blocked_detail(detail):
            lead.whatsapp_status = Lead.WhatsappStatus.PENDING
            lead.whatsapp_last_error = detail[:4000]
            lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
            break
    return sent


def run_due_scheduled_batches(now=None) -> dict[str, int]:
    """Execute every scheduled batch whose time has arrived.

    Scheduled batches run at their chosen time regardless of the allowed-days /
    send-window gate (the user picked an explicit datetime). Returns a summary.
    """
    now = now or timezone.now()
    summary = {"batches_run": 0, "leads_sent": 0}

    while True:
        with transaction.atomic():
            batch = (
                WhatsAppBatchSchedule.objects.select_for_update(skip_locked=True)
                .filter(
                    status=WhatsAppBatchSchedule.Status.PENDING,
                    scheduled_at__lte=now,
                )
                .order_by("scheduled_at", "id")
                .first()
            )
            if batch is None:
                break
            batch.status = WhatsAppBatchSchedule.Status.PROCESSING
            batch.started_at = timezone.now()
            batch.save(update_fields=["status", "started_at"])

        try:
            sent = dispatch_assigned_batch(batch)
            batch.sent_count = sent
            batch.status = WhatsAppBatchSchedule.Status.COMPLETED
            batch.completed_at = timezone.now()
            batch.save(update_fields=["sent_count", "status", "completed_at"])
            summary["batches_run"] += 1
            summary["leads_sent"] += sent
        except Exception as exc:  # noqa: BLE001 - record and move on
            batch.status = WhatsAppBatchSchedule.Status.FAILED
            batch.error = str(exc)[:4000]
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "error", "completed_at"])

    return summary
