"""WhatsApp outbound dispatch via YCloud BSP (https://api.ycloud.com/v2)."""

from __future__ import annotations

import inspect
import logging
import re
from datetime import datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from leads.chat_messages import record_outbound_chat_message, upsert_outbound_chat_message
from leads.display import lead_phone_list, whatsapp_me_url
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
    sink_lead_display_order,
)
from leads.ycloud_service import (
    build_template_payload,
    build_text_payload,
    e164_recipient,
    extract_ycloud_error,
    fetch_approved_templates,
    fetch_gateway_status as ycloud_fetch_gateway_status,
    message_id_from_response,
    delivery_status_from_response,
    resolve_ycloud_credentials,
    send_message_directly,
    whatsapp_from_number,
    ycloud_api_key,
    ycloud_waba_id,
)

logger = logging.getLogger(__name__)

OFFICIAL_API_MARKER = "[Official API]"
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
    "[CRITICAL WARNING] Dispatched blocked! YCloud WhatsApp credentials are "
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


def meta_access_token() -> str:
    """YCloud API key (legacy name kept for existing call sites)."""
    return ycloud_api_key()


def meta_phone_number_id() -> str:
    """Business sender E.164 (legacy name kept for dashboard display)."""
    return whatsapp_from_number()


def resolve_meta_dispatch_credentials() -> tuple[str, str]:
    """Live YCloud credentials at POST time: (api_key, from_number)."""
    return resolve_ycloud_credentials()


def whatsapp_access_token() -> str:
    return ycloud_api_key()


def whatsapp_phone_number_id() -> str:
    return whatsapp_from_number()


def whatsapp_graph_api_version() -> str:
    return "v2"


def meta_messages_url(*, phone_id: str = "") -> str:
    from leads.ycloud_service import YCLOUD_SEND_DIRECT_URL

    return YCLOUD_SEND_DIRECT_URL


def meta_graph_url(path: str) -> str:
    from leads.ycloud_service import YCLOUD_API_BASE

    return f"{YCLOUD_API_BASE}/{path.lstrip('/')}"


def meta_waba_id() -> str:
    return ycloud_waba_id()


def meta_dispatch_headers() -> dict[str, str]:
    from leads.ycloud_service import ycloud_headers

    return ycloud_headers()


def print_meta_http_tracking_debug(headers: dict[str, str]) -> None:
    """No-op — retained for call-site compatibility."""
    _ = headers


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


def _approved_templates_from_synced_config(
    config: WhatsAppConfig | None = None,
) -> list[dict[str, Any]]:
    cfg = config or WhatsAppConfig.load()
    return [
        t
        for t in _approved_templates_from_config(cfg)
        if (t.get("status") or "APPROVED").upper() == "APPROVED"
    ]


def known_meta_template_names() -> frozenset[str]:
    """Template names allowed for outbound send — synced YCloud catalog only."""
    return frozenset(
        str(t["name"]).strip()
        for t in _approved_templates_from_synced_config()
        if str(t.get("name") or "").strip()
    )


def _default_template_from_catalog(catalog: list[dict[str, Any]]) -> str:
    names = {str(t.get("name") or "").strip() for t in catalog}
    if DEFAULT_META_TEMPLATE_NAME in names:
        return DEFAULT_META_TEMPLATE_NAME
    if catalog:
        return str(catalog[0]["name"]).strip()
    return DEFAULT_META_TEMPLATE_NAME


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
    """Normalize Meta language codes for API send (keep en vs en_US distinct)."""
    lang = (language or "").strip().replace("-", "_")
    if not lang:
        return META_OUTBOUND_TEMPLATE_LANGUAGE
    return lang


def meta_template_choices_for_ui() -> tuple[tuple[str, str], ...]:
    """Dropdown choices from the synced YCloud template catalog."""
    templates = _approved_templates_from_synced_config()
    if not templates:
        return (("", "— Sync templates from YCloud (Update) —"),)

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
    ensure_ycloud_templates_synced()
    config = WhatsAppConfig.load()
    for item in _approved_templates_from_config(config):
        if str(item.get("name") or "").strip() == name:
            return _normalize_meta_template_language(str(item.get("language") or ""))
    return META_OUTBOUND_TEMPLATE_LANGUAGE


def _resolve_waba_id_for_templates(*, token: str, phone_id: str) -> str:
    waba = ycloud_waba_id()
    if waba:
        return waba
    raise ValueError("YCLOUD_WABA_ID (or WHATSAPP_BUSINESS_ACCOUNT_ID) is required for template sync.")


def fetch_meta_message_templates_from_api() -> list[dict[str, Any]]:
    """List APPROVED message templates from YCloud."""
    token, from_number = resolve_meta_dispatch_credentials()
    if not token or not from_number:
        raise ValueError("YCLOUD_API_KEY and WHATSAPP_FROM_NUMBER are required.")
    return fetch_approved_templates()


def sync_meta_message_templates_to_config() -> tuple[int, str | None]:
    """Refresh ``WhatsAppConfig.meta_message_templates`` from YCloud. Returns (count, error)."""
    try:
        catalog = fetch_meta_message_templates_from_api()
    except Exception as exc:
        logger.warning("YCloud template sync failed: %s", exc)
        return 0, str(exc)

    if not catalog:
        return 0, "No approved message templates returned by YCloud for this account."

    config = WhatsAppConfig.load()
    config.meta_message_templates = catalog
    config.meta_templates_synced_at = timezone.now()
    catalog_names = {str(t["name"]).strip() for t in catalog}
    active = (config.outbound_template_name or "").strip()
    if active not in catalog_names:
        config.outbound_template_name = _default_template_from_catalog(catalog)
    force_send = (config.force_send_template_name or "").strip()
    if force_send and force_send not in catalog_names:
        config.force_send_template_name = ""
    config.save(
        update_fields=[
            "meta_message_templates",
            "meta_templates_synced_at",
            "outbound_template_name",
            "force_send_template_name",
        ]
    )
    return len(catalog), None


def ensure_ycloud_templates_synced() -> tuple[bool, str]:
    """Load approved templates from YCloud when the local catalog is empty."""
    if _approved_templates_from_synced_config():
        return True, ""
    count, error = sync_meta_message_templates_to_config()
    if error:
        return False, f"Template sync failed: {error}"
    if count <= 0:
        return (
            False,
            "No approved templates found on YCloud. Create one in YCloud/Meta, then click Update.",
        )
    return True, ""


def normalize_outbound_template_name(name: str) -> str:
    """Return a synced YCloud template name, or the catalog default when unset."""
    cleaned = (name or "").strip()
    known = known_meta_template_names()
    if known:
        if cleaned in known:
            return cleaned
        return _default_template_from_catalog(_approved_templates_from_synced_config())
    return cleaned or DEFAULT_META_TEMPLATE_NAME


def validate_outbound_template_name(template_name: str | None) -> tuple[bool, str]:
    """Ensure the template exists in the synced YCloud catalog before send."""
    synced_ok, sync_error = ensure_ycloud_templates_synced()
    if not synced_ok:
        return False, sync_error

    known = known_meta_template_names()
    if not known:
        return False, "No approved templates found on YCloud."

    if template_name and str(template_name).strip():
        selected = str(template_name).strip()
    else:
        config = WhatsAppConfig.load()
        selected = normalize_outbound_template_name(config.outbound_template_name)

    if selected not in known:
        names = ", ".join(sorted(known)[:8])
        return (
            False,
            f"Template '{selected}' is not approved on YCloud. Sync templates and choose one of: {names}",
        )
    return True, ""


def get_active_config_template_name() -> str:
    """Active outbound template from ``WhatsAppConfig`` (default ``just_to_say_hi``)."""
    config = WhatsAppConfig.load()
    return normalize_outbound_template_name(config.outbound_template_name)


def get_force_send_template_name() -> str:
    """Template for the Send now (⚡) button; falls back to ``outbound_template_name``."""
    config = WhatsAppConfig.load()
    raw = (config.force_send_template_name or "").strip()
    if raw:
        return normalize_outbound_template_name(raw)
    return get_active_config_template_name()


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
    """Primary dispatch target — always from ``phone_numbers`` list when set."""
    phones = lead_phone_list(lead)
    return phones[0] if phones else ""


def reset_lead_whatsapp_after_phone_change(
    lead: Lead,
    *,
    old_phones: list[str],
    new_phones: list[str],
) -> bool:
    """Clear prior dispatch state when the contact number changes so Send now works again."""
    if old_phones == new_phones:
        return False

    from leads.models import ChatMessage

    in_queue = bool(lead.group and lead.group.name == QUEUE_GROUP_NAME)
    if lead.whatsapp_status == Lead.WhatsappStatus.PROCESSING:
        lead.whatsapp_status = (
            Lead.WhatsappStatus.PENDING if in_queue else Lead.WhatsappStatus.IDLE
        )
    elif lead.whatsapp_status in (
        Lead.WhatsappStatus.SENT,
        Lead.WhatsappStatus.FAILED,
    ):
        lead.whatsapp_status = (
            Lead.WhatsappStatus.PENDING if in_queue else Lead.WhatsappStatus.IDLE
        )

    lead.whatsapp_sent_at = None
    lead.whatsapp_last_error = ""
    lead.whatsapp_instance_id = ""
    ChatMessage.objects.filter(lead=lead).delete()
    return True


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
    """YCloud template payload for sendDirectly."""
    to_number = e164_recipient(primary_phone(lead))
    from_number = whatsapp_from_number()
    if template_name:
        selected_template = normalize_outbound_template_name(template_name)
    else:
        selected_template = get_active_config_template_name()
    language_code = meta_template_language_for_name(selected_template)
    return build_template_payload(
        from_number=from_number,
        to_number=to_number,
        template_name=selected_template,
        language_code=language_code,
    )


def is_dispatch_blocked_detail(detail: str) -> bool:
    message = (detail or "").strip()
    return (
        message.startswith(GATEWAY_NOT_READY_PREFIX)
        or message.startswith("[CRITICAL WARNING]")
    )


def fetch_gateway_status() -> dict[str, Any]:
    return ycloud_fetch_gateway_status()


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
    return extract_ycloud_error(response)


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


def build_official_dispatch_remark(
    lead: Lead,
    *,
    meta_message_id: str = "",
    delivery_status: str = "",
) -> str:
    phone = _mask_phone_for_activity_log(primary_phone(lead))
    status = (delivery_status or "accepted").strip().lower()
    if status in {"sent", "delivered", "read"}:
        status_label = "sent via WhatsApp"
    elif status == "accepted":
        status_label = "queued by YCloud (awaiting WhatsApp delivery)"
    else:
        status_label = "accepted by YCloud"
    remark = f"{OFFICIAL_API_MARKER} Template {status_label} for {phone}"
    msg_id = (meta_message_id or "").strip()
    if msg_id:
        short_id = msg_id if len(msg_id) <= 20 else f"{msg_id[:17]}…"
        remark = f"{remark} · {short_id}"
    return remark


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
    template_name: str | None = None,
    delivery_status: str = "",
) -> None:
    now = timezone.now()
    is_first_send = lead.whatsapp_sent_at is None
    lead.whatsapp_status = Lead.WhatsappStatus.SENT
    lead.whatsapp_sent_at = now
    lead.whatsapp_instance_id = phone_number_id
    lead.whatsapp_last_error = ""
    update_fields = [
        "whatsapp_status",
        "whatsapp_sent_at",
        "whatsapp_instance_id",
        "whatsapp_last_error",
    ]
    if is_first_send:
        lead.display_order = sink_lead_display_order(lead)
        update_fields.append("display_order")
    lead.save(update_fields=update_fields)
    remark = build_official_dispatch_remark(
        lead,
        meta_message_id=meta_message_id,
        delivery_status=delivery_status,
    )
    if priority:
        remark = f"Priority Force Trigger — {remark}"
    LeadConversationLog.objects.create(
        lead=lead,
        conversation_date=now.date(),
        remarks=remark,
    )
    selected_template = normalize_outbound_template_name(
        template_name or get_active_config_template_name()
    )
    upsert_outbound_chat_message(
        lead,
        template_name=selected_template,
        body=meta_template_preview_body(selected_template),
        meta_message_id=meta_message_id,
        created_at=now,
    )


def mark_failed(lead: Lead, error_message: str) -> None:
    lead.whatsapp_status = Lead.WhatsappStatus.FAILED
    lead.whatsapp_last_error = (error_message or "Unknown error")[:4000]
    lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])


def send_text_to_lead(
    lead: Lead, *, priority: bool = False, template_name: str | None = None
) -> tuple[bool, str]:
    """Dispatch a WhatsApp template via YCloud sendDirectly."""
    lead.refresh_from_db(fields=["phone_number", "phone_numbers"])
    token, from_number = resolve_meta_dispatch_credentials()
    if not token or not from_number:
        detail = "YCloud WhatsApp API is not configured."
        record_whatsapp_activity_warning(detail, lead=lead)
        mark_failed(lead, detail)
        return False, detail

    ready, guard_msg = gateway_send_ready()
    if not ready:
        record_whatsapp_activity_warning(guard_msg, lead=lead)
        return False, guard_msg

    to_number = e164_recipient(primary_phone(lead))
    if not to_number:
        mark_failed(lead, "No valid phone number on lead.")
        return False, "No valid phone number on lead."

    valid, template_error = validate_outbound_template_name(template_name)
    if not valid:
        detail = append_meta_dispatch_origin(template_error)
        record_whatsapp_activity_warning(detail, lead=lead)
        mark_failed(lead, detail)
        return False, detail

    payload = build_meta_template_payload(lead, template_name=template_name)
    logger.info("YCloud sendDirectly template to %s from %s", to_number, from_number)

    ok, detail, data = send_message_directly(payload)
    if not ok:
        detail = append_meta_dispatch_origin(detail)
        record_whatsapp_activity_warning(f"YCloud API error: {detail}", lead=lead)
        mark_failed(lead, detail)
        return False, detail

    meta_message_id = message_id_from_response(data)
    delivery_status = delivery_status_from_response(data)
    selected_template = str(payload.get("template", {}).get("name") or "").strip()
    mark_sent(
        lead,
        from_number,
        priority=priority,
        meta_message_id=meta_message_id,
        template_name=selected_template or template_name,
        delivery_status=delivery_status,
    )
    if delivery_status == "accepted":
        logger.info(
            "YCloud queued template for lead #%s (%s); status=accepted — "
            "delivery updates require YCloud webhooks.",
            lead.pk,
            to_number,
        )
    return True, ""


def build_meta_free_text_payload(lead: Lead, text: str) -> dict[str, Any]:
    """YCloud free-form text payload (24h session window)."""
    return build_text_payload(
        from_number=whatsapp_from_number(),
        to_number=e164_recipient(primary_phone(lead)),
        body=text,
    )


def send_free_text_to_lead(lead: Lead, text: str) -> tuple[bool, str, Optional["ChatMessage"]]:
    """
    Send free-form WhatsApp text via YCloud within the 24h customer service window.
    Returns (ok, error_detail, ChatMessage|None).
    """
    body = (text or "").strip()
    if not body:
        return False, "Message cannot be empty.", None

    token, from_number = resolve_meta_dispatch_credentials()
    if not token or not from_number:
        detail = "YCloud WhatsApp API is not configured."
        record_whatsapp_activity_warning(detail, lead=lead)
        return False, detail, None

    ready, guard_msg = gateway_send_ready()
    if not ready:
        record_whatsapp_activity_warning(guard_msg, lead=lead)
        return False, guard_msg, None

    to_number = e164_recipient(primary_phone(lead))
    if not to_number:
        return False, "No valid phone number on lead.", None

    payload = build_meta_free_text_payload(lead, body)
    ok, detail, data = send_message_directly(payload)
    if not ok:
        detail = append_meta_dispatch_origin(detail)
        record_whatsapp_activity_warning(f"YCloud API error: {detail}", lead=lead)
        return False, detail, None

    meta_message_id = message_id_from_response(data)
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
