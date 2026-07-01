"""
Leads UI views.

The dashboard **Run hunt** action POSTs JSON to ``POST /hunt/?limit=…`` with
``city``, ``shop_keyword`` (required: free-text keyword before scraping), ``query`` (optional
Maps fragment; defaults to the keyword when empty), and optional ``require_website`` in the body;
``limit`` is from the query string (default 20, max 100). Hunts import via Serper only.
"""

import html
import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.db.models import Case, Count, Exists, Max, OuterRef, Prefetch, Subquery, Value, When, BooleanField
from django.db.models.functions import Lower
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone as django_timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.generic import ListView, TemplateView

from leads.display import (
    AUTOMATOR_LOG_MARKER,
    category_badge_html,
    clinic_card_title,
    clinic_location_suffix,
    lead_google_maps_url,
    lead_has_dispatchable_phone,
    lead_phone_list,
    lead_whatsapp_active_chat,
    lead_whatsapp_dispatched,
    normalize_manual_phone,
    whatsapp_me_path,
    whatsapp_me_url,
)
from leads.models import (
    ChainBrandStatus,
    ChatMessage,
    Lead,
    LeadConversationLog,
    LeadGroup,
    SearchQueryRecord,
    WhatsAppBatchSchedule,
    WhatsAppConfig,
    WhatsAppScriptTemplate,
)
from leads.chat_messages import chat_messages_for_lead
from leads.whatsapp_webhook import (
    DELIVERY_FAILED_MARKER,
    handle_meta_webhook_verify,
    process_whatsapp_webhook,
)
from leads.whatsapp_service import (
    DEFAULT_OUTREACH_SCRIPT,
    OFFICIAL_API_MARKER,
    SCRIPT_TEMPLATE_FALLBACK_GROUP,
    campaign_metrics,
    clear_pending_batch_memberships,
    campaign_timezone,
    fetch_gateway_status,
    GATEWAY_GUARD_LOG_PREFIX,
    get_active_config_template_name,
    is_dispatch_blocked_detail,
    meta_access_token,
    meta_template_preview_body,
    meta_template_choices_for_ui,
    get_force_send_template_name,
    normalize_outbound_template_name,
    reset_lead_whatsapp_after_phone_change,
    sync_meta_message_templates_to_config,
    primary_phone,
    queue_counts,
    record_whatsapp_activity_warning,
    reset_campaign_metrics_snapshot,
    send_free_text_to_lead,
    send_text_to_lead,
    whatsapp_phone_number_id,
    whatsapp_template_language,
)
from leads.pipeline import (
    QUEUE_GROUP_NAME,
    SYSTEM_GROUP_SORT_ORDERS,
    TRASH_GROUP_NAME,
    UNCATEGORIZED_GROUP_NAME,
    WHATSAPP_CHATS_GROUP_NAME,
    apply_group_assignment_side_effects,
    enqueue_leads_for_whatsapp,
    ensure_pipeline_system_groups,
    get_or_create_queue_group,
    get_or_create_trash_group,
    get_or_create_uncategorized_group,
    get_or_create_whatsapp_chats_group,
    uncategorized_group_filter,
)
from leads.services import (
    fetch_leads_from_serper,
    sync_chain_flags_for_name,
)
TRASH_STATUS_MESSAGE = "Moved to trash — excluded from pipeline."
SYSTEM_LEAD_GROUP_NAMES = (
    UNCATEGORIZED_GROUP_NAME,
    QUEUE_GROUP_NAME,
    WHATSAPP_CHATS_GROUP_NAME,
    TRASH_GROUP_NAME,
)

MAX_PHONES_PER_LEAD = 8

WHATSAPP_PROTECTED_STATUSES = frozenset(
    {
        Lead.WhatsappStatus.PROCESSING,
    }
)

WHATSAPP_WEEKDAY_CHOICES = [
    (1, "Mon"),
    (2, "Tue"),
    (3, "Wed"),
    (4, "Thu"),
    (5, "Fri"),
    (6, "Sat"),
    (7, "Sun"),
]

logger = logging.getLogger(__name__)


def _normalize_phone_numbers_body(body: dict) -> list[str]:
    """Parse ``phone_numbers`` array from JSON; fallback to legacy ``phone_number`` string."""
    out: list[str] = []
    raw = body.get("phone_numbers")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            n = normalize_manual_phone(item.strip())
            if n and n not in out:
                out.append(n)
    if len(out) > MAX_PHONES_PER_LEAD:
        out = out[:MAX_PHONES_PER_LEAD]
    if out:
        return out
    legacy = body.get("phone_number")
    if isinstance(legacy, str):
        n = normalize_manual_phone(legacy.strip())
        if n:
            return [n]
    return []

HUNT_LIMIT_CHOICES = (10, 20, 50, 100)
DEFAULT_HUNT_LIMIT = 20
DEFAULT_HUNT_COUNTRY = "Malaysia"


def _normalize_brand_key(name: str) -> str:
    return (name or "").strip().lower()


def _leads_for_group_id(group_id_raw: str):
    """Resolve a tab key or numeric pk to a Lead queryset."""
    gid = (group_id_raw or "uncategorized").strip().lower()
    if gid.isdigit():
        return Lead.objects.filter(group_id=int(gid))
    return Lead.objects.filter(uncategorized_group_filter())


def _queueable_lead_ids(qs) -> list[int]:
    """Leads that may enter the pending queue without disrupting in-flight sends."""
    ids: list[int] = []
    for lead in qs.exclude(whatsapp_status__in=WHATSAPP_PROTECTED_STATUSES).iterator():
        if lead_has_dispatchable_phone(lead):
            ids.append(lead.pk)
    return ids


def _is_htmx(request) -> bool:
    return (request.headers.get("HX-Request") or "").lower() == "true"


def _funnel_metrics(qs) -> dict[str, int]:
    """Pipeline counters for the active folder tab (or filtered queryset)."""
    base = qs
    with_phone = base.exclude(phone_number="").exclude(phone_number__isnull=True)
    return {
        "total_pipeline": base.count(),
        "in_queue": with_phone.filter(
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        ).count(),
        "outbound_sent": with_phone.filter(whatsapp_status=Lead.WhatsappStatus.SENT).count(),
        "live_responses": with_phone.filter(
            whatsapp_status=Lead.WhatsappStatus.SENT,
            has_awaiting_client_reply=True,
        ).count(),
    }


def _lead_group_counts() -> dict:
    """Total lead counts keyed by each tab's ``data-group-id`` (live tab badges)."""
    queue_group = get_or_create_queue_group()
    trash_group = get_or_create_trash_group()
    counts = {
        "uncategorized": _leads_qs_for_tab("uncategorized", None).count(),
        str(queue_group.pk): _leads_qs_for_tab(str(queue_group.pk), None).count(),
        str(trash_group.pk): _leads_qs_for_tab(str(trash_group.pk), None).count(),
    }
    for g in LeadGroup.objects.exclude(name__in=SYSTEM_LEAD_GROUP_NAMES).annotate(
        total_leads=Count("leads")
    ):
        counts[str(g.pk)] = g.total_leads
    return counts


def _dashboard_enrich_clinics(qs):
    """Attach dashboard-only annotations (brand counts, location suffix)."""
    clinics_list = list(qs)
    brand_counts = {
        row["ln"]: row["c"]
        for row in Lead.objects.annotate(ln=Lower("name"))
        .values("ln")
        .annotate(c=Count("id"))
    }
    for c in clinics_list:
        c.dashboard_location_suffix = clinic_location_suffix(c)
        c.dashboard_phones = lead_phone_list(c)
        key = _normalize_brand_key(c.name)
        c.dashboard_same_brand_count = brand_counts.get(key, 0)
        c.whatsapp_dispatched = lead_whatsapp_dispatched(c)
        c.whatsapp_active_chat = lead_whatsapp_active_chat(c)
    name_keys = [_normalize_brand_key(c.name) for c in clinics_list]
    counts = Counter(k for k in name_keys if k)
    multi_location_brands = {k for k, v in counts.items() if v > 1}
    return clinics_list, multi_location_brands


def _dashboard_prepare_clinics(qs):
    """Enrich dashboard lead rows with display-only annotations."""
    return _dashboard_enrich_clinics(qs)


def _leads_tab_base_qs():
    latest_chat_outbound = Subquery(
        ChatMessage.objects.filter(lead_id=OuterRef("pk"))
        .order_by("-created_at", "-id")
        .values("is_outbound")[:1]
    )
    return Lead.objects.prefetch_related(
        Prefetch(
            "whatsapp_batches",
            queryset=WhatsAppBatchSchedule.objects.order_by("scheduled_at", "id"),
        )
    ).annotate(
        has_conversation_log=Exists(
            LeadConversationLog.objects.filter(lead_id=OuterRef("pk"))
        ),
        has_human_conversation_log=Exists(
            LeadConversationLog.objects.filter(lead_id=OuterRef("pk")).exclude(
                remarks__icontains=AUTOMATOR_LOG_MARKER
            )
        ),
        has_client_conversation_log=Exists(
            LeadConversationLog.objects.filter(
                lead_id=OuterRef("pk"),
                remarks__icontains="[WhatsApp · client]",
            )
        ),
        has_inbound_chat_message=Exists(
            ChatMessage.objects.filter(lead_id=OuterRef("pk"), is_outbound=False)
        ),
        has_chat_message=Exists(
            ChatMessage.objects.filter(lead_id=OuterRef("pk"))
        ),
        _latest_chat_is_outbound=latest_chat_outbound,
        has_awaiting_client_reply=Case(
            When(_latest_chat_is_outbound=False, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
    )


def _lead_chat_indicator_map(qs) -> dict[str, dict[str, bool]]:
    """Build per-lead chat chrome flags for dashboard polling."""
    enriched, _ = _dashboard_prepare_clinics(qs)
    return {
        str(lead.pk): {
            "awaiting": lead_whatsapp_active_chat(lead),
            "dispatched": lead_whatsapp_dispatched(lead),
        }
        for lead in enriched
    }


def _leads_tab_sink_order(qs):
    """Respect manual ``display_order`` (higher = lower on page); newest first among ties."""
    return qs.order_by("display_order", "-created_at", "id")


def _leads_qs_for_tab(group_id_key: Optional[str], search_record_id: Optional[int]):
    """Leads for a dashboard tab, with pending outreach cards sunk to the bottom."""
    qs = _leads_tab_base_qs()
    if search_record_id is not None:
        qs = qs.filter(search_query_record_id=int(search_record_id))
    g = (group_id_key or "uncategorized").strip().lower()
    queue_group = get_or_create_queue_group()
    trash_group = get_or_create_trash_group()
    whatsapp_chats_group = get_or_create_whatsapp_chats_group()
    if g.isdigit() and int(g) == queue_group.pk:
        qs = qs.exclude(group_id=trash_group.pk).filter(
            whatsapp_status__in=[
                Lead.WhatsappStatus.PENDING,
                Lead.WhatsappStatus.PROCESSING,
            ]
        )
        return qs.order_by("created_at", "id")
    if g.isdigit() and int(g) == whatsapp_chats_group.pk:
        qs = qs.exclude(group_id=trash_group.pk).filter(
            has_awaiting_client_reply=True
        )
        return qs.order_by("-created_at", "id")
    if g.isdigit():
        qs = qs.filter(group_id=int(g))
    else:
        qs = qs.filter(uncategorized_group_filter())
    return _leads_tab_sink_order(qs)


def _folder_context_for_group(grp: LeadGroup) -> dict:
    return {
        "current_group_name": grp.name,
        "current_group_id": grp.pk,
        "is_trash_view": grp.name == TRASH_GROUP_NAME,
        "is_uncategorized_view": grp.name == UNCATEGORIZED_GROUP_NAME,
        "is_queue_view": grp.name == QUEUE_GROUP_NAME,
        "is_whatsapp_chats_view": grp.name == WHATSAPP_CHATS_GROUP_NAME,
        "force_send_template_name": get_force_send_template_name(),
    }


def _lead_grid_action_context(request, lead: Lead) -> dict:
    """Template context for grid card bottom action partials."""
    gid_raw = (
        request.GET.get("group_id") or request.POST.get("group_id") or ""
    ).strip().lower()
    if gid_raw.isdigit():
        ctx = _active_folder_context(request)
    elif lead.group_id:
        ctx = _folder_context_for_group(lead.group)
    else:
        ctx = _active_folder_context(request)
    return {"lead": lead, **ctx}


def _active_folder_context(request) -> dict:
    """Resolve the active dashboard tab folder for grid card action conditionals."""
    gid_raw = (
        request.GET.get("group_id") or request.POST.get("group_id") or "uncategorized"
    ).strip().lower()
    if gid_raw.isdigit():
        grp = LeadGroup.objects.filter(pk=int(gid_raw)).first()
        if grp:
            return _folder_context_for_group(grp)
    uncategorized = get_or_create_uncategorized_group()
    return {
        "current_group_name": UNCATEGORIZED_GROUP_NAME,
        "current_group_id": uncategorized.pk,
        "is_trash_view": False,
        "is_uncategorized_view": True,
        "is_queue_view": False,
        "is_whatsapp_chats_view": False,
        "force_send_template_name": get_force_send_template_name(),
    }


def _leads_queryset_for_table(request):
    """Apply optional hunt filter and lead group tab (uncategorized = group is null)."""
    srid = request.GET.get("search_record")
    srid_int = int(srid) if srid and str(srid).isdigit() else None
    gid_raw = (request.GET.get("group_id") or "").strip().lower()
    if gid_raw.isdigit():
        return _leads_qs_for_tab(gid_raw, srid_int)
    return _leads_qs_for_tab("uncategorized", srid_int)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class LeadDashboardView(ListView):
    """Template dashboard listing all leads."""

    model = Lead
    template_name = "leads/dashboard.html"
    context_object_name = "clinics"

    def get_queryset(self):
        srid = self.request.GET.get("search_record")
        srid_int = int(srid) if srid and str(srid).isdigit() else None
        gid_raw = (self.request.GET.get("group_id") or "").strip().lower()
        tab_key = gid_raw if gid_raw.isdigit() else "uncategorized"
        return _leads_qs_for_tab(tab_key, srid_int)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        clinics_list, multi_brands = _dashboard_prepare_clinics(context["clinics"])
        context["multi_location_brands"] = multi_brands
        context["clinics"] = clinics_list
        context["hunt_limit_choices"] = HUNT_LIMIT_CHOICES
        context["hunt_limit_default"] = DEFAULT_HUNT_LIMIT
        context["hunt_default_country"] = DEFAULT_HUNT_COUNTRY
        context["hunt_api_path"] = reverse("hunt_trigger")
        context["export_xlsx_url"] = reverse("clinics_export_xlsx")
        context["export_full_backup_url"] = reverse("export_full_backup")
        context["import_full_backup_url"] = reverse("import_full_backup")
        context["bulk_manual_url"] = reverse("leads_bulk_manual")
        context["bulk_whatsapp_queue_url"] = reverse("leads_bulk_whatsapp_queue")
        context["bulk_assign_batch_url"] = reverse("leads_bulk_assign_batch")
        context["whatsapp_batches_json_url"] = reverse("whatsapp_batches_json")
        context["get_leads_table_url"] = reverse("get_leads_table")
        context["get_lead_chat_indicators_url"] = reverse("get_lead_chat_indicators")
        context["create_lead_group_url"] = reverse("create_lead_group")
        context["bulk_assign_group_url"] = reverse("leads_bulk_assign_group")
        context["reorder_lead_groups_url"] = reverse("reorder_lead_groups")
        context["reorder_leads_url"] = reverse("reorder_leads")
        context["lead_manual_create_url"] = reverse("lead_manual_create")
        context["workspace_fragment_dashboard_url"] = reverse("workspace_fragment_dashboard")
        context["workspace_fragment_whatsapp_url"] = reverse("workspace_fragment_whatsapp")
        context["queue_group"] = get_or_create_queue_group()
        context["whatsapp_chats_group"] = get_or_create_whatsapp_chats_group()
        context["active_chat_count"] = _leads_qs_for_tab(
            str(context["whatsapp_chats_group"].pk), None
        ).count()
        context["trash_group"] = get_or_create_trash_group()
        context["lead_groups"] = (
            LeadGroup.objects.exclude(name__in=SYSTEM_LEAD_GROUP_NAMES)
            .annotate(total_leads=Count("leads"))
            .order_by("sort_order", "name")
        )
        context["uncategorized_lead_count"] = _leads_qs_for_tab(
            "uncategorized", None
        ).count()
        context["queue_lead_count"] = _leads_qs_for_tab(
            str(context["queue_group"].pk), None
        ).count()
        context["trash_lead_count"] = _leads_qs_for_tab(
            str(context["trash_group"].pk), None
        ).count()
        context["funnel_metrics"] = _funnel_metrics(self.get_queryset())
        rid = self.request.GET.get("search_record")
        context["active_search_record_id"] = (
            int(rid) if rid and str(rid).isdigit() else None
        )
        gid_raw = (self.request.GET.get("group_id") or "").strip().lower()
        if gid_raw.isdigit():
            context["active_group_pk"] = int(gid_raw)
            context["active_group_tab_id"] = str(context["active_group_pk"])
        else:
            context["active_group_pk"] = None
            context["active_group_tab_id"] = "uncategorized"
        context.update(_active_folder_context(self.request))
        return context


def _dashboard_workspace_context(request):
    view = LeadDashboardView()
    view.request = request
    view.kwargs = {}
    view.object_list = view.get_queryset()
    context = view.get_context_data(object_list=view.object_list)
    context["workspace_fragment"] = True
    return context


@require_GET
def workspace_fragment_dashboard(request):
    """AJAX workspace panel for Leads (dashboard) without full page reload."""
    context = _dashboard_workspace_context(request)
    html = render_to_string(
        "leads/partials/_workspace_dashboard_fragment.html",
        context,
        request=request,
    )
    return JsonResponse({"ok": True, "html": html, "title": "Lead CRM"})


def _whatsapp_script_template_rows() -> list[dict]:
    """Industry folder script editors for the WhatsApp control dashboard."""
    saved = {
        row.group_name: row.template_text
        for row in WhatsAppScriptTemplate.objects.all()
    }
    system_names = set(SYSTEM_LEAD_GROUP_NAMES)
    rows: list[dict] = [
        {
            "group_name": SCRIPT_TEMPLATE_FALLBACK_GROUP,
            "template_text": saved.get(SCRIPT_TEMPLATE_FALLBACK_GROUP, ""),
            "is_fallback": True,
        }
    ]
    seen = {SCRIPT_TEMPLATE_FALLBACK_GROUP}
    for group in LeadGroup.objects.exclude(name__in=system_names).order_by(
        "sort_order", "name"
    ):
        if group.name in seen:
            continue
        seen.add(group.name)
        rows.append(
            {
                "group_name": group.name,
                "template_text": saved.get(group.name, ""),
                "is_fallback": False,
            }
        )
    return rows


def _gateway_status_label(connection: dict) -> str:
    """Explicit gateway label for templates and conditional HTMX polling."""
    if connection.get("connected"):
        return "CONNECTED"
    return "UNCONFIGURED"


def _whatsapp_activity_log_queryset():
    return LeadConversationLog.objects.filter(
        Q(remarks__icontains=OFFICIAL_API_MARKER)
        | Q(remarks__icontains=DELIVERY_FAILED_MARKER)
        | Q(remarks__icontains="Touchpoint")
        | Q(remarks__icontains=GATEWAY_GUARD_LOG_PREFIX)
    )


def _activity_log_cleared_after(request) -> Optional[datetime]:
    raw = (request.session.get("wa_activity_log_cleared_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if django_timezone.is_naive(parsed):
        return django_timezone.make_aware(
            parsed, django_timezone.get_current_timezone()
        )
    return parsed


def _activity_log_suppress_active(request) -> bool:
    """True while a recent Reset must force empty poll payloads (race guard)."""
    raw = (request.session.get("wa_activity_log_suppress_until") or "").strip()
    if not raw:
        return False
    try:
        until = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if django_timezone.is_naive(until):
        until = django_timezone.make_aware(
            until, django_timezone.get_current_timezone()
        )
    return django_timezone.now() < until


def _mask_phone_for_activity_log(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) <= 6:
        return digits or "unknown"
    if len(digits) <= 8:
        return f"{digits[:4]}XXXX"
    return f"{digits[:4]}{'X' * (len(digits) - 7)}{digits[-3:]}"


def _activity_timestamp_hms(value: datetime) -> str:
    local = value.astimezone(campaign_timezone())
    return local.strftime("%H:%M:%S")


def _activity_display_line(
    *,
    kind: str,
    timestamp: str,
    lead_name: str,
    message: str,
    lead: Lead | None = None,
) -> str:
    if kind == "dispatch":
        if OFFICIAL_API_MARKER in message:
            body = message
            if body.startswith("Priority Force Trigger — "):
                body = body.split("Priority Force Trigger — ", 1)[-1]
        else:
            phone = _mask_phone_for_activity_log(primary_phone(lead) if lead else "")
            body = f"Message successfully sent to {phone}"
    elif kind == "failed":
        body = message or f"Dispatch failed for {lead_name}"
    else:
        body = message
        if GATEWAY_GUARD_LOG_PREFIX in body:
            body = body.split(GATEWAY_GUARD_LOG_PREFIX, 1)[-1].lstrip(" —-")
        if body.startswith("YCloud API error:") or body.startswith("Meta API error:"):
            body = body
        elif body.startswith("[CRITICAL WARNING]"):
            body = body.replace(
                "[CRITICAL WARNING] Dispatched blocked!",
                "Cloud API not ready:",
                1,
            ).strip()
    emoji = {"dispatch": "🟢", "warning": "⚠️", "failed": "🔴"}.get(kind, "ℹ️")
    return f"[{timestamp}] {emoji} {body}"


def _whatsapp_dashboard_context(*, request=None) -> dict:
    config = WhatsAppConfig.load()
    connection = fetch_gateway_status()
    metrics = campaign_metrics()
    gateway_status = _gateway_status_label(connection)
    return {
        "config": config,
        "connection": connection,
        "gateway_status": gateway_status,
        "counts": queue_counts(),
        "metrics": metrics,
        "phone_number_id": whatsapp_phone_number_id(),
        "template_name": get_active_config_template_name(),
        "template_language": whatsapp_template_language(),
        "meta_template_choices": meta_template_choices_for_ui(),
        "meta_templates_synced_at": config.meta_templates_synced_at,
        "active_template_preview_body": meta_template_preview_body(),
        "force_send_template_name": get_force_send_template_name(),
        "force_send_template_preview_body": meta_template_preview_body(
            get_force_send_template_name()
        ),
        "weekday_choices": WHATSAPP_WEEKDAY_CHOICES,
        "allowed_days_set": set(config.normalized_allowed_days()),
        "campaign_timezone": str(campaign_timezone()),
        "script_template_rows": _whatsapp_script_template_rows(),
        "default_outreach_script": DEFAULT_OUTREACH_SCRIPT,
        "activity": _whatsapp_activity_entries(request=request),
        "batch_schedules": _batch_schedule_rows(),
        "batch_pending_count": metrics.get("pending", 0),
        "batch_now": django_timezone.now(),
    }


def _batch_schedule_rows(limit: int = 12):
    """Recent + upcoming scheduled WhatsApp batches with per-batch lead counts."""
    return list(
        WhatsAppBatchSchedule.objects.annotate(
            total_leads=Count("leads"),
            c_pending=Count(
                "leads",
                filter=Q(leads__whatsapp_status=Lead.WhatsappStatus.PENDING),
            ),
            c_processing=Count(
                "leads",
                filter=Q(leads__whatsapp_status=Lead.WhatsappStatus.PROCESSING),
            ),
            c_sent=Count(
                "leads",
                filter=Q(leads__whatsapp_status=Lead.WhatsappStatus.SENT),
            ),
            c_failed=Count(
                "leads",
                filter=Q(leads__whatsapp_status=Lead.WhatsappStatus.FAILED),
            ),
        ).order_by("-scheduled_at", "-id")[:limit]
    )


def _batch_schedule_card_context(*, request=None, message: str = "", ok: bool = True) -> dict:
    config = WhatsAppConfig.load()
    return {
        "batch_schedules": _batch_schedule_rows(),
        "batch_pending_count": queue_counts().get("pending", 0),
        "campaign_timezone": str(campaign_timezone()),
        "batch_now": django_timezone.now(),
        "batch_message": message,
        "batch_ok": ok,
        "config": config,
        "meta_template_choices": meta_template_choices_for_ui(),
        "meta_templates_synced_at": config.meta_templates_synced_at,
    }


def _normalize_activity_remark(message: str) -> str:
    text = (message or "").strip()
    if not text:
        return text
    return text.replace(
        "Template successfully delivered to",
        "Template queued by YCloud for",
    ).replace(
        "Template accepted by YCloud for",
        "Template queued by YCloud for",
    )


def _whatsapp_activity_entries(limit: int = 10, *, request=None) -> list[dict]:
    if request is not None and _activity_log_suppress_active(request):
        return []

    entries: list[dict] = []
    cleared_after = _activity_log_cleared_after(request) if request is not None else None
    logs = _whatsapp_activity_log_queryset().select_related("lead").order_by("-created_at")
    if cleared_after is not None:
        logs = logs.filter(created_at__gt=cleared_after)
    logs = logs[:limit]
    for log in logs:
        remarks = _normalize_activity_remark((log.remarks or "").strip())
        is_guard = GATEWAY_GUARD_LOG_PREFIX in remarks
        is_failed = DELIVERY_FAILED_MARKER in remarks
        if is_failed:
            kind = "failed"
        elif is_guard:
            kind = "warning"
        else:
            kind = "dispatch"
        timestamp = _activity_timestamp_hms(log.created_at)
        message = remarks[:240]
        entries.append(
            {
                "sort_ts": log.created_at.timestamp(),
                "when": timestamp,
                "kind": kind,
                "lead_name": log.lead.name,
                "message": message,
                "display_line": _activity_display_line(
                    kind=kind,
                    timestamp=timestamp,
                    lead_name=log.lead.name,
                    message=message,
                    lead=log.lead,
                ),
                "badge_class": "bg-rose-900 text-rose-200"
                if is_failed
                else "bg-amber-900 text-amber-200"
                if is_guard
                else "bg-emerald-900 text-emerald-200",
            }
        )

    entries.sort(key=lambda item: item["sort_ts"], reverse=True)
    return entries[:limit]


def _batch_report_choices() -> list[dict]:
    """Dropdown options for the batch-assigned leads report."""
    tz = campaign_timezone()
    choices = []
    qs = (
        WhatsAppBatchSchedule.objects.annotate(
            assigned_leads=Count("leads"),
        )
        .order_by("-scheduled_at", "-id")
    )
    for batch in qs:
        local = batch.scheduled_at.astimezone(tz)
        choices.append(
            {
                "id": batch.pk,
                "label": (
                    f"{local:%b %d, %Y · %I:%M %p} · {batch.outbound_template_name} "
                    f"· {batch.assigned_leads} lead(s) · {batch.get_status_display()}"
                ),
            }
        )
    return choices


def _resolve_batch_report_id(request) -> int | None:
    raw = (request.GET.get("batch_id") or "").strip()
    if raw.isdigit():
        batch_id = int(raw)
        if WhatsAppBatchSchedule.objects.filter(pk=batch_id).exists():
            return batch_id
    batch = (
        WhatsAppBatchSchedule.objects.annotate(assigned_leads=Count("leads"))
        .filter(assigned_leads__gt=0)
        .order_by("-scheduled_at", "-id")
        .first()
    )
    if batch:
        return batch.pk
    latest = WhatsAppBatchSchedule.objects.order_by("-scheduled_at", "-id").first()
    return latest.pk if latest else None


def _batch_report_leads_qs(batch_id: int):
    return (
        Lead.objects.filter(whatsapp_batches__pk=batch_id)
        .order_by("name", "pk")
        .distinct()
    )


def _batch_report_context(request) -> dict:
    batch_id = _resolve_batch_report_id(request)
    batch = None
    report_leads: list[Lead] = []
    if batch_id is not None:
        batch = WhatsAppBatchSchedule.objects.filter(pk=batch_id).first()
        if batch:
            report_leads = list(_batch_report_leads_qs(batch_id))
            for lead in report_leads:
                phones = lead_phone_list(lead)
                lead.report_phone_display = " · ".join(phones) if phones else ""
    return {
        "nav_active": "reports",
        "batch_choices": _batch_report_choices(),
        "selected_batch": batch,
        "selected_batch_id": batch.pk if batch else None,
        "report_leads": report_leads,
        "report_lead_count": len(report_leads),
        "batch_report_export_url": reverse("batch_report_export_xlsx"),
        "campaign_timezone": str(campaign_timezone()),
    }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class ReportsView(TemplateView):
    """Batch report — all leads assigned to a chosen WhatsApp batch."""

    template_name = "leads/reports.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_batch_report_context(self.request))
        return context


@require_GET
def batch_report_export_xlsx(request):
    """Download name + phone for leads assigned to a WhatsApp batch."""
    raw = (request.GET.get("batch_id") or "").strip()
    if not raw.isdigit():
        return HttpResponse(
            "batch_id is required.",
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    batch = get_object_or_404(WhatsAppBatchSchedule, pk=int(raw))
    try:
        from openpyxl import Workbook
    except ImportError:
        return HttpResponse(
            "openpyxl is not installed. Run: pip install openpyxl",
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Batch report"
    local = batch.scheduled_at.astimezone(campaign_timezone())
    ws.append(["Batch", f"{local:%Y-%m-%d %H:%M} · {batch.outbound_template_name}"])
    ws.append(["Batch status", batch.get_status_display()])
    ws.append([])
    ws.append(["Name", "Contact number", "Status"])
    for lead in _batch_report_leads_qs(batch.pk).iterator(chunk_size=400):
        phones = lead_phone_list(lead)
        ws.append(
            [
                lead.name,
                " ; ".join(phones) if phones else "",
                lead.get_whatsapp_status_display(),
            ]
        )

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"batch_{batch.pk}_assigned_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@method_decorator(ensure_csrf_cookie, name="dispatch")
class WhatsAppDashboardView(TemplateView):
    """WhatsApp campaign monitor — Meta Cloud API metrics and schedule controls."""

    template_name = "leads/whatsapp_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nav_active"] = "whatsapp"
        context.update(_whatsapp_dashboard_context(request=self.request))
        context["workspace_fragment_dashboard_url"] = reverse("workspace_fragment_dashboard")
        context["workspace_fragment_whatsapp_url"] = reverse("workspace_fragment_whatsapp")
        return context


@require_GET
def workspace_fragment_whatsapp(request):
    """AJAX workspace panel for WhatsApp CRM without full page reload."""
    context = _whatsapp_dashboard_context(request=request)
    context["workspace_fragment"] = True
    html = render_to_string(
        "leads/partials/_workspace_whatsapp_fragment.html",
        context,
        request=request,
    )
    return JsonResponse({"ok": True, "html": html, "title": "WhatsApp CRM — Lead CRM"})


@require_GET
def chat_inbox(request, pk: int):
    """HTMX partial: live chat drawer shell or message list fragment for a lead."""
    lead = get_object_or_404(Lead, pk=pk)
    phone = primary_phone(lead) or "—"
    messages = chat_messages_for_lead(lead)
    context = {
        "lead": lead,
        "phone_display": phone,
        "messages": messages,
    }
    list_only = (request.GET.get("fragment") or "").strip().lower() == "messages"
    template_name = (
        "leads/partials/_chat_inbox_messages.html"
        if list_only
        else "leads/partials/_chat_inbox_panel.html"
    )
    html = render_to_string(template_name, context, request=request)
    return HttpResponse(html)


@csrf_protect
@require_POST
def send_free_text(request, pk: int):
    """HTMX: send a free-form WhatsApp text reply within the Meta 24h session window."""
    lead = get_object_or_404(Lead, pk=pk)
    text = (request.POST.get("message") or "").strip()
    if not text:
        return HttpResponse(
            '<p class="px-1 text-xs text-red-600">Message cannot be empty.</p>',
            status=400,
        )

    ok, detail, chat_msg = send_free_text_to_lead(lead, text)
    if not ok:
        return HttpResponse(
            f'<p class="px-1 text-xs text-red-600">{html.escape(detail)}</p>',
            status=422,
        )

    bubble_html = render_to_string(
        "leads/partials/_chat_inbox_message_bubble.html",
        {"msg": chat_msg},
        request=request,
    )
    return HttpResponse(bubble_html)


@require_GET
def whatsapp_pending_count(request):
    """HTMX partial: sidebar badge with pending queue count."""
    trash_group = get_or_create_trash_group()
    count = Lead.objects.filter(
        whatsapp_status=Lead.WhatsappStatus.PENDING,
    ).exclude(group_id=trash_group.pk).count()
    html = render_to_string(
        "leads/partials/_whatsapp_pending_badge.html",
        {"count": count},
        request=request,
    )
    return HttpResponse(html)


@require_GET
def whatsapp_activity_log(request):
    """HTMX partial: scrollable mini-terminal of recent dispatch / failure events."""
    config = WhatsAppConfig.load()
    connected = (request.GET.get("connected") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    live_refresh = connected
    if _activity_log_suppress_active(request):
        activity = []
    else:
        activity = _whatsapp_activity_entries(request=request)
    list_only = (request.GET.get("fragment") or "").strip().lower() == "list"
    template_name = (
        "leads/partials/_whatsapp_activity_log_list.html"
        if list_only
        else "leads/partials/_whatsapp_activity_log.html"
    )
    html = render_to_string(
        template_name,
        {
            "activity": activity,
            "live_refresh": live_refresh,
            "campaign_paused": config.is_paused,
        },
        request=request,
    )
    return HttpResponse(html)


@csrf_protect
@require_POST
def clear_live_activity_logs(request):
    """HTMX: purge activity rows, reset campaign counters, and OOB-sync metric cards."""
    now = django_timezone.now()
    request.session["wa_activity_log_cleared_at"] = now.isoformat()
    request.session["wa_activity_log_suppress_until"] = (
        now + timedelta(seconds=12)
    ).isoformat()
    request.session.modified = True
    request.session.save()

    with transaction.atomic():
        _whatsapp_activity_log_queryset().delete()
    connection.commit()

    reset_campaign_metrics_snapshot()
    metrics = campaign_metrics()
    counts = queue_counts()
    gateway_status = _gateway_status_label(fetch_gateway_status())
    panel_context = _whatsapp_dashboard_context(request=request)
    panel_context.update(
        {
            "activity": [],
            "suppress_polling": True,
        }
    )
    list_html = render_to_string(
        "leads/partials/_whatsapp_activity_log_list.html",
        {"activity": [], "cleared": True},
        request=request,
    )
    panel_oob = render_to_string(
        "leads/partials/_live_activity_log_panel.html",
        {**panel_context, "oob": True},
        request=request,
    )
    counters_oob = render_to_string(
        "leads/partials/_whatsapp_dashboard_counters_oob.html",
        {
            "metrics": metrics,
            "counts": counts,
            "gateway_connected": gateway_status == "CONNECTED",
        },
        request=request,
    )
    response = HttpResponse(list_html + panel_oob + counters_oob)
    response["HX-Trigger"] = json.dumps(
        {"waActivityLogCleared": True, "waSidebarBadgeRefresh": True}
    )
    return response


def _render_batch_schedule_card(request, message: str = "", ok: bool = True) -> HttpResponse:
    html = render_to_string(
        "leads/partials/_whatsapp_batch_schedule_card.html",
        _batch_schedule_card_context(request=request, message=message, ok=ok),
        request=request,
    )
    return HttpResponse(html)


def _parse_batch_datetime(date_raw: str, time_raw: str):
    """Combine a ``YYYY-MM-DD`` date and ``HH:MM`` time into a future aware datetime.

    Returns ``(scheduled_at, error_message)``; ``scheduled_at`` is ``None`` on error.
    """
    try:
        naive = datetime.strptime(f"{(date_raw or '').strip()} {(time_raw or '').strip()}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None, "Pick a valid date and time."
    scheduled_at = django_timezone.make_aware(naive, campaign_timezone())
    if scheduled_at <= django_timezone.now():
        return None, "Choose a date and time in the future."
    return scheduled_at, ""


@csrf_protect
@require_POST
def whatsapp_schedule_batch(request):
    """HTMX: create an empty scheduled batch (date + time + template). Leads are
    assigned to it later from the Queue tab."""
    scheduled_at, error = _parse_batch_datetime(
        request.POST.get("scheduled_date"), request.POST.get("scheduled_time")
    )
    if error:
        return _render_batch_schedule_card(request, message=error, ok=False)

    template_name = normalize_outbound_template_name(
        request.POST.get("outbound_template_name")
    )
    WhatsAppBatchSchedule.objects.create(
        scheduled_at=scheduled_at,
        outbound_template_name=template_name,
    )
    local = scheduled_at.astimezone(campaign_timezone())
    return _render_batch_schedule_card(
        request,
        message=f"Batch scheduled for {local:%b %d, %Y · %I:%M %p}. Assign leads from the Queue tab.",
    )


@require_GET
def whatsapp_batches_json(request):
    """JSON list of upcoming (still-pending) batches + template choices for the
    'Choose batch' modal on the leads dashboard."""
    batches = []
    qs = (
        WhatsAppBatchSchedule.objects.filter(
            status=WhatsAppBatchSchedule.Status.PENDING
        )
        .annotate(total_leads=Count("leads"))
        .order_by("scheduled_at", "id")
    )
    tz = campaign_timezone()
    for b in qs:
        local = b.scheduled_at.astimezone(tz)
        batches.append(
            {
                "id": b.pk,
                "label": (
                    f"{local:%b %d, %Y · %I:%M %p} · {b.outbound_template_name} "
                    f"· {b.total_leads} lead(s)"
                ),
            }
        )
    config = WhatsAppConfig.load()
    return JsonResponse(
        {
            "ok": True,
            "batches": batches,
            "templates": list(meta_template_choices_for_ui()),
            "default_template": config.outbound_template_name or "just_to_say_hi",
        }
    )


@csrf_protect
@require_POST
def leads_bulk_assign_batch(request):
    """Assign selected leads to a batch (existing ``batch_id`` or a new one)."""
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON body."}, status=400)

    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        return JsonResponse(
            {"ok": False, "detail": "ids must be a non-empty list."}, status=400
        )
    id_list: list[int] = []
    for x in ids:
        try:
            id_list.append(int(x))
        except (TypeError, ValueError):
            continue
    if not id_list:
        return JsonResponse({"ok": False, "detail": "No valid ids."}, status=400)

    batch = None
    raw_batch_id = body.get("batch_id")
    if raw_batch_id not in (None, "", "new"):
        try:
            batch = WhatsAppBatchSchedule.objects.get(
                pk=int(raw_batch_id),
                status=WhatsAppBatchSchedule.Status.PENDING,
            )
        except (WhatsAppBatchSchedule.DoesNotExist, TypeError, ValueError):
            return JsonResponse(
                {"ok": False, "detail": "That batch is no longer available."},
                status=400,
            )
    else:
        new_batch = body.get("new_batch") or {}
        scheduled_at, error = _parse_batch_datetime(
            new_batch.get("scheduled_date"), new_batch.get("scheduled_time")
        )
        if error:
            return JsonResponse({"ok": False, "detail": error}, status=400)
        batch = WhatsAppBatchSchedule.objects.create(
            scheduled_at=scheduled_at,
            outbound_template_name=normalize_outbound_template_name(
                new_batch.get("outbound_template_name")
            ),
        )

    # A lead that already sits in a still-pending batch is skipped (it is
    # already queued). Leads whose batches are all historical (sent/cancelled)
    # — or that have none — get added to this batch, accumulating history.
    eligible_ids = list(
        Lead.objects.filter(pk__in=id_list)
        .exclude(whatsapp_batches__status=WhatsAppBatchSchedule.Status.PENDING)
        .values_list("pk", flat=True)
    )
    if eligible_ids:
        batch.leads.add(*eligible_ids)
    skipped = len(set(id_list)) - len(eligible_ids)
    return JsonResponse(
        {
            "ok": True,
            "updated": len(eligible_ids),
            "skipped": skipped,
            "batch_id": batch.pk,
        }
    )


@csrf_protect
@require_POST
def whatsapp_cancel_batch(request, pk: int):
    """HTMX: cancel a still-pending scheduled batch and release its leads."""
    updated = WhatsAppBatchSchedule.objects.filter(
        pk=pk, status=WhatsAppBatchSchedule.Status.PENDING
    ).update(status=WhatsAppBatchSchedule.Status.CANCELLED)
    if updated:
        cancelled = WhatsAppBatchSchedule.objects.filter(pk=pk).first()
        if cancelled is not None:
            cancelled.leads.clear()
        return _render_batch_schedule_card(request, message="Scheduled batch cancelled.")
    return _render_batch_schedule_card(
        request, message="That batch can no longer be cancelled.", ok=False
    )


@csrf_protect
@require_POST
def whatsapp_refresh_meta_templates(request):
    """HTMX: pull approved message templates from Meta and refresh the dropdown."""
    count, error = sync_meta_message_templates_to_config()
    context = _whatsapp_dashboard_context(request=request)
    if error:
        toast_html = render_to_string(
            "leads/partials/_whatsapp_config_toast.html",
            {"ok": False, "message": f"Template sync failed: {error}"},
            request=request,
        )
        return HttpResponse(toast_html)

    toast_html = render_to_string(
        "leads/partials/_whatsapp_config_toast.html",
        {"message": f"Synced {count} approved template(s) from YCloud."},
        request=request,
    )
    field_oob = render_to_string(
        "leads/partials/_outbound_template_field.html",
        {**context, "oob": True},
        request=request,
    )
    force_send_oob = render_to_string(
        "leads/partials/_force_send_template_settings.html",
        {**context, "oob": True},
        request=request,
    )
    card_oob = render_to_string(
        "leads/partials/_whatsapp_script_templates_section.html",
        {**context, "oob": True},
        request=request,
    )
    return HttpResponse(toast_html + field_oob + force_send_oob + card_oob)


@csrf_protect
@require_POST
def save_force_send_template(request):
    """HTMX: persist the Meta template used by Send now (⚡) on group folder cards."""
    from leads.whatsapp_service import validate_outbound_template_name

    template_name = normalize_outbound_template_name(
        request.POST.get("force_send_template_name")
    )
    valid, error = validate_outbound_template_name(template_name)
    if not valid:
        toast_html = render_to_string(
            "leads/partials/_whatsapp_config_toast.html",
            {"ok": False, "message": error},
            request=request,
        )
        return HttpResponse(toast_html, status=400)

    config = WhatsAppConfig.load()
    config.force_send_template_name = template_name
    config.save(update_fields=["force_send_template_name"])

    context = _whatsapp_dashboard_context(request=request)
    toast_html = render_to_string(
        "leads/partials/_whatsapp_config_toast.html",
        {"message": f"Send now template set to {template_name}."},
        request=request,
    )
    settings_oob = render_to_string(
        "leads/partials/_force_send_template_settings.html",
        {**context, "oob": True},
        request=request,
    )
    return HttpResponse(toast_html + settings_oob)


@csrf_protect
@require_POST
def save_script_template(request):
    """HTMX: upsert a per-folder WhatsApp outreach script template."""
    group_name = (request.POST.get("group_name") or "").strip()[:100]
    if not group_name:
        return HttpResponse("", status=400)
    template_text = (request.POST.get("template_text") or "").strip()
    WhatsAppScriptTemplate.objects.update_or_create(
        group_name=group_name,
        defaults={"template_text": template_text},
    )
    html = render_to_string(
        "leads/partials/_whatsapp_script_template_saved.html",
        request=request,
    )
    return HttpResponse(html)


def _lead_grid_cell_fade_out_response(request, lead_id: int) -> HttpResponse:
    """Empty 200 for hx-swap=\"delete\" on the grid cell target."""
    response = HttpResponse("")
    response["HX-Trigger"] = json.dumps({"funnelMetricsRefresh": True})
    return response


def _force_send_grid_response(
    request, lead: Lead, *, ok: bool, sink_card: bool = False
) -> HttpResponse:
    """HTMX response after Send now: remove queue row on success, else refresh actions."""
    ctx = _lead_grid_action_context(request, lead)
    enriched, _ = _dashboard_prepare_clinics(_leads_tab_base_qs().filter(pk=lead.pk))
    if enriched:
        ctx["lead"] = enriched[0]

    trigger = {"waRowFlash": lead.pk, "funnelMetricsRefresh": True}
    if ok and sink_card and not ctx.get("is_queue_view"):
        trigger["leadCardSink"] = lead.pk
    if ok and ctx.get("is_queue_view"):
        response = _lead_grid_cell_fade_out_response(request, lead.pk)
        response["HX-Trigger"] = json.dumps(trigger)
        response["HX-Retarget"] = f"#lead-grid-cell-{lead.pk}"
        response["HX-Reswap"] = "delete swap:300ms"
        return response

    html = render_to_string(
        "leads/partials/_lead_grid_bottom_actions.html",
        ctx,
        request=request,
    )
    response = HttpResponse(html)
    response["HX-Trigger"] = json.dumps(trigger)
    response["HX-Retarget"] = f"#lead-bottom-actions-{lead.pk}"
    response["HX-Reswap"] = "outerHTML"
    return response


@csrf_protect
@require_POST
def whatsapp_force_send(request, pk: int):
    """HTMX: priority Meta Cloud API template dispatch for a single lead row."""
    lead = get_object_or_404(Lead, pk=pk)
    if lead.whatsapp_status == Lead.WhatsappStatus.PROCESSING:
        return _force_send_grid_response(request, lead, ok=False)
    if not lead_has_dispatchable_phone(lead):
        lead.whatsapp_status = Lead.WhatsappStatus.FAILED
        lead.whatsapp_last_error = "No valid phone number on lead."
        lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
        return _force_send_grid_response(request, lead, ok=False)

    if not meta_access_token():
        lead.whatsapp_status = Lead.WhatsappStatus.FAILED
        lead.whatsapp_last_error = "YCLOUD_API_KEY and WHATSAPP_FROM_NUMBER are not configured."
        lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
        return _force_send_grid_response(request, lead, ok=False)

    template_name = get_force_send_template_name()
    from leads.chat_messages import lead_already_received_template

    if lead_already_received_template(lead, template_name):
        detail = f"Template '{template_name}' was already sent to this lead."
        record_whatsapp_activity_warning(detail, lead=lead)
        return _force_send_grid_response(request, lead, ok=False)

    was_unsent = lead.whatsapp_sent_at is None
    lead.whatsapp_status = Lead.WhatsappStatus.PROCESSING
    lead.whatsapp_last_error = ""
    lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])

    print(
        f"\n[TRACKING DETECTED] whatsapp_force_send initiating Meta dispatch "
        f"for lead #{lead.pk} ({lead.name})\n"
    )
    ok, detail = send_text_to_lead(
        lead,
        priority=True,
        template_name=template_name,
    )
    if not ok and is_dispatch_blocked_detail(detail):
        lead.whatsapp_status = Lead.WhatsappStatus.PENDING
        lead.whatsapp_last_error = detail[:4000]
        lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
    lead.refresh_from_db()
    return _force_send_grid_response(
        request,
        lead,
        ok=ok,
        sink_card=ok and was_unsent,
    )


@require_GET
def get_lead_chat_indicators(request):
    """JSON map of chat pulse / dispatched flags for the active leads tab (dashboard polling)."""
    qs = _leads_queryset_for_table(request)
    whatsapp_chats_group = get_or_create_whatsapp_chats_group()
    active_chat_count = _leads_qs_for_tab(str(whatsapp_chats_group.pk), None).count()
    return JsonResponse(
        {
            "ok": True,
            "leads": _lead_chat_indicator_map(qs),
            "funnel_metrics": _funnel_metrics(qs),
            "active_chat_count": active_chat_count,
            "group_counts": _lead_group_counts(),
        },
        json_dumps_params={"ensure_ascii": False},
    )


@require_GET
def get_leads_table(request):
    """
    Return HTML fragments for the leads list/grid for AJAX tab switching.
    GET ``group_id``: numeric LeadGroup pk, or ``uncategorized`` (default) for ungrouped leads.
    GET ``search_record``: optional hunt filter (same as dashboard).
    """
    qs = _leads_queryset_for_table(request)
    clinics_list, multi_location_brands = _dashboard_prepare_clinics(qs)
    ctx = {
        "clinics": clinics_list,
        "multi_location_brands": multi_location_brands,
        **_active_folder_context(request),
    }
    tbody_html = render_to_string(
        "leads/partials/_leads_table_body.html",
        ctx,
        request=request,
    )
    grid_html = render_to_string(
        "leads/partials/_leads_grid_body.html",
        ctx,
        request=request,
    )
    return JsonResponse(
        {
            "ok": True,
            "tbody_html": tbody_html,
            "grid_html": grid_html,
            "funnel_metrics": _funnel_metrics(qs),
            "group_counts": _lead_group_counts(),
        },
        json_dumps_params={"ensure_ascii": False},
    )


@csrf_protect
@require_POST
def leads_bulk_whatsapp_queue(request):
    """Push selected leads into the outbound WhatsApp pending queue."""
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON body."}, status=400)

    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        return JsonResponse({"ok": False, "detail": "ids must be a non-empty list."}, status=400)

    id_list: list[int] = []
    for x in ids:
        try:
            id_list.append(int(x))
        except (TypeError, ValueError):
            continue
    if not id_list:
        return JsonResponse({"ok": False, "detail": "No valid ids."}, status=400)

    updated = enqueue_leads_for_whatsapp(id_list)
    return JsonResponse({"ok": True, "updated": updated, "action": "queue"})


@csrf_protect
@require_POST
def leads_bulk_whatsapp_pause(request):
    """Hold selected leads out of the automator queue (pending/processing → paused failed state)."""
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON body."}, status=400)

    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        return JsonResponse({"ok": False, "detail": "ids must be a non-empty list."}, status=400)

    id_list: list[int] = []
    for x in ids:
        try:
            id_list.append(int(x))
        except (TypeError, ValueError):
            continue
    if not id_list:
        return JsonResponse({"ok": False, "detail": "No valid ids."}, status=400)

    qs = Lead.objects.filter(
        pk__in=id_list,
        whatsapp_status__in=[
            Lead.WhatsappStatus.PENDING,
            Lead.WhatsappStatus.PROCESSING,
        ],
    )
    paused_ids = list(qs.values_list("pk", flat=True))
    updated = Lead.objects.filter(pk__in=paused_ids).update(
        whatsapp_status=Lead.WhatsappStatus.FAILED,
        whatsapp_last_error="Paused by operator (bulk hold).",
    )
    clear_pending_batch_memberships(paused_ids)
    return JsonResponse({"ok": True, "updated": updated, "action": "pause"})


@csrf_protect
@require_POST
def bulk_action_by_group(request):
    """
    Apply a funnel rule to every lead in a folder tab.
    POST ``group_id`` (pk or ``uncategorized``) and ``action``:
    ``activate_queue`` or ``mark_junk``.
    """
    if request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode() or "{}")
        except json.JSONDecodeError:
            body = {}
        group_id_raw = body.get("group_id")
        action = (body.get("action") or "").strip().lower()
    else:
        group_id_raw = request.POST.get("group_id")
        action = (request.POST.get("action") or "").strip().lower()

    if action not in ("activate_queue", "mark_junk"):
        detail = "action must be activate_queue or mark_junk."
        if _is_htmx(request):
            return HttpResponse(
                render_to_string(
                    "leads/partials/_pipeline_trigger_toast.html",
                    {"ok": False, "message": detail},
                    request=request,
                ),
                status=400,
            )
        return JsonResponse({"ok": False, "detail": detail}, status=400)

    qs = _leads_for_group_id(str(group_id_raw or "uncategorized"))
    group_label = "Uncategorized"
    if group_id_raw and str(group_id_raw).strip().isdigit():
        grp = LeadGroup.objects.filter(pk=int(group_id_raw)).first()
        if grp:
            group_label = grp.name

    if action == "activate_queue":
        ids = _queueable_lead_ids(qs)
        updated = enqueue_leads_for_whatsapp(ids) if ids else 0
        message = f"Moved {updated} lead(s) from “{group_label}” into queue."
        payload = {"ok": True, "updated": updated, "action": action, "group": group_label}
    else:
        trash = get_or_create_trash_group()
        trashed_ids = list(qs.values_list("pk", flat=True))
        updated = Lead.objects.filter(pk__in=trashed_ids).update(
            group=trash,
            whatsapp_status=Lead.WhatsappStatus.FAILED,
            whatsapp_last_error=TRASH_STATUS_MESSAGE,
        )
        clear_pending_batch_memberships(trashed_ids)
        message = f"Moved {updated} lead(s) from “{group_label}” to trash."
        payload = {
            "ok": True,
            "updated": updated,
            "action": action,
            "group": group_label,
            "trash_group_id": trash.pk,
        }

    if _is_htmx(request):
        response = HttpResponse(
            render_to_string(
                "leads/partials/_pipeline_trigger_toast.html",
                {"ok": True, "message": message},
                request=request,
            )
        )
        response["HX-Trigger"] = json.dumps({"funnelMetricsRefresh": True})
        return response
    return JsonResponse(payload)


@csrf_protect
@require_POST
def enqueue_lead(request, pk: int):
    """HTMX: enqueue a lead for WhatsApp outreach while keeping its native folder."""
    lead = get_object_or_404(Lead, pk=pk)
    ctx = _lead_grid_action_context(request, lead)
    if lead.whatsapp_status in WHATSAPP_PROTECTED_STATUSES:
        html = render_to_string(
            "leads/partials/_lead_grid_queue_slot.html",
            ctx,
            request=request,
        )
        return HttpResponse(html)

    if not lead_has_dispatchable_phone(lead):
        html = render_to_string(
            "leads/partials/_lead_grid_queue_slot.html",
            ctx,
            request=request,
        )
        return HttpResponse(html, status=422)

    if lead.whatsapp_status != Lead.WhatsappStatus.PENDING:
        lead.whatsapp_status = Lead.WhatsappStatus.PENDING
        lead.whatsapp_last_error = ""
        lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
        lead.refresh_from_db()
        ctx["lead"] = lead

    html = render_to_string(
        "leads/partials/_lead_grid_queue_slot.html",
        ctx,
        request=request,
    )
    response = HttpResponse(html)
    response["HX-Trigger"] = json.dumps(
        {
            "waRowFlash": lead.pk,
            "funnelMetricsRefresh": True,
            "leadCardUndim": lead.pk,
        }
    )
    return response


@csrf_protect
@require_POST
def dequeue_lead(request, pk: int):
    """HTMX: remove a lead from the WhatsApp outreach queue (revert to idle)."""
    lead = get_object_or_404(Lead, pk=pk)
    ctx = _lead_grid_action_context(request, lead)

    if lead.whatsapp_status == Lead.WhatsappStatus.PROCESSING:
        html = render_to_string(
            "leads/partials/_lead_grid_queue_slot.html",
            ctx,
            request=request,
        )
        return HttpResponse(html, status=422)

    if lead.whatsapp_status != Lead.WhatsappStatus.PENDING:
        html = render_to_string(
            "leads/partials/_lead_grid_queue_slot.html",
            ctx,
            request=request,
        )
        return HttpResponse(html)

    lead.whatsapp_status = Lead.WhatsappStatus.IDLE
    lead.whatsapp_last_error = ""
    lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
    # Leaving the queue drops any not-yet-sent batch assignment; re-adding the
    # lead later requires choosing a batch again.
    clear_pending_batch_memberships(lead.pk)
    lead.refresh_from_db()
    ctx["lead"] = lead

    if ctx["is_queue_view"]:
        html = render_to_string(
            "leads/partials/_lead_grid_queue_slot.html",
            ctx,
            request=request,
        )
        response = HttpResponse(html)
        response["HX-Trigger"] = json.dumps({"funnelMetricsRefresh": True})
        return response

    html = render_to_string(
        "leads/partials/_lead_grid_queue_slot.html",
        ctx,
        request=request,
    )
    response = HttpResponse(html)
    response["HX-Trigger"] = json.dumps({"funnelMetricsRefresh": True})
    return response


@csrf_protect
@require_POST
def lead_join_whatsapp_queue(request, pk: int):
    """Backward-compatible alias for ``enqueue_lead``."""
    return enqueue_lead(request, pk)


@csrf_protect
@require_POST
def move_to_trash_group(request, pk: int):
    """HTMX: soft-trash a lead into the Trash folder and fade its grid cell out."""
    lead = get_object_or_404(Lead, pk=pk)
    if lead.whatsapp_status == Lead.WhatsappStatus.PROCESSING:
        html = render_to_string(
            "leads/partials/_lead_grid_junk_error.html",
            {"detail": "Cannot move to trash while message is processing."},
            request=request,
        )
        return HttpResponse(html, status=422)

    trash = get_or_create_trash_group()
    lead.group = trash
    lead.whatsapp_status = Lead.WhatsappStatus.FAILED
    lead.whatsapp_last_error = TRASH_STATUS_MESSAGE
    lead.save(update_fields=["group", "whatsapp_status", "whatsapp_last_error"])
    clear_pending_batch_memberships(lead.pk)
    return _lead_grid_cell_fade_out_response(request, lead.pk)


@csrf_protect
@require_POST
def lead_mark_junk(request, pk: int):
    """Backward-compatible alias for move_to_trash_group."""
    return move_to_trash_group(request, pk=pk)


@csrf_protect
@require_http_methods(["DELETE", "POST"])
def delete_lead_permanently(request, pk: int):
    """HTMX: permanently delete a lead from the database (Trash folder view)."""
    lead = get_object_or_404(Lead, pk=pk)
    name_for_sync = (lead.name or "").strip()
    lead_id = lead.pk
    try:
        lead.delete()
    except ProtectedError:
        html = render_to_string(
            "leads/partials/_lead_grid_junk_error.html",
            {"detail": "Cannot delete — other records still reference this lead."},
            request=request,
        )
        return HttpResponse(html, status=400)
    if name_for_sync:
        sync_chain_flags_for_name(name_for_sync)
    return _lead_grid_cell_fade_out_response(request, lead_id)


@csrf_protect
@require_POST
def create_lead_group(request):
    """Create a LeadGroup; JSON body ``{\"name\": \"...\"}``."""
    try:
        data = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON."}, status=400)
    name = (data.get("name") or "").strip()[:100]
    if not name:
        return JsonResponse({"ok": False, "detail": "name is required."}, status=400)
    try:
        next_ord = (LeadGroup.objects.aggregate(m=Max("sort_order"))["m"] or 0) + 1
        g = LeadGroup.objects.create(name=name, sort_order=next_ord)
    except IntegrityError:
        return JsonResponse(
            {"ok": False, "detail": "A group with this name already exists."},
            status=400,
        )
    return JsonResponse({"ok": True, "id": g.pk, "name": g.name})


@csrf_protect
@require_POST
def reorder_lead_groups(request):
    """Persist custom folder tab order (system tabs stay pinned at the front)."""
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON."}, status=400)
    order = body.get("order")
    if not isinstance(order, list):
        return JsonResponse({"ok": False, "detail": "order must be a list."}, status=400)
    try:
        provided = [int(x) for x in order]
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "detail": "order must be a list of integers."}, status=400)
    ensure_pipeline_system_groups()
    reorderable_ids = set(
        LeadGroup.objects.exclude(name__in=SYSTEM_LEAD_GROUP_NAMES).values_list("pk", flat=True)
    )
    if set(provided) != reorderable_ids or len(provided) != len(reorderable_ids):
        return JsonResponse(
            {"ok": False, "detail": "order must list every custom lead group exactly once."},
            status=400,
        )
    base_sort = max(SYSTEM_GROUP_SORT_ORDERS.values()) + 1
    with transaction.atomic():
        for idx, pk in enumerate(provided):
            LeadGroup.objects.filter(pk=pk).update(sort_order=base_sort + idx)
    return JsonResponse({"ok": True})


@csrf_protect
@require_POST
def reorder_leads(request):
    """
    Persist card order for the current folder tab. JSON:
    ``group_id`` (``\"uncategorized\"`` or numeric string), optional ``search_record`` (int),
    ``order`` (list of lead ids — must match the same filtered queryset as the table).
    """
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON."}, status=400)
    order = body.get("order")
    if not isinstance(order, list) or not order:
        return JsonResponse({"ok": False, "detail": "order must be a non-empty list."}, status=400)
    try:
        provided = [int(x) for x in order]
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "detail": "order must be a list of integers."}, status=400)
    gid_key = body.get("group_id")
    if gid_key is None:
        gid_key = "uncategorized"
    srid = body.get("search_record")
    srid_int = int(srid) if srid is not None and str(srid).isdigit() else None
    qs = _leads_qs_for_tab(str(gid_key), srid_int)
    expected_ids = set(qs.values_list("pk", flat=True))
    if set(provided) != expected_ids or len(provided) != len(expected_ids):
        return JsonResponse(
            {
                "ok": False,
                "detail": "order must include exactly the leads in this tab (same search / folder filter).",
            },
            status=400,
        )
    with transaction.atomic():
        for idx, pk in enumerate(provided):
            Lead.objects.filter(pk=pk).update(display_order=idx)
    return JsonResponse({"ok": True})


@csrf_protect
@require_POST
def leads_bulk_assign_group(request):
    """
    Assign many leads to one group or back to uncategorized.

    JSON: ``ids`` (list of int, required), ``group_id`` (int or JSON ``null``).
    Use ``null`` to clear ``group`` (leads show under Uncategorized only).
    """
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON body."}, status=400)

    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        return JsonResponse({"ok": False, "detail": "ids must be a non-empty list."}, status=400)

    id_list: list[int] = []
    for x in ids:
        try:
            id_list.append(int(x))
        except (TypeError, ValueError):
            continue
    if not id_list:
        return JsonResponse({"ok": False, "detail": "No valid ids."}, status=400)

    if "group_id" not in body:
        return JsonResponse({"ok": False, "detail": "group_id is required (integer or null)."}, status=400)

    raw_gid = body.get("group_id")
    leads_before = list(Lead.objects.filter(pk__in=id_list))
    if not leads_before:
        return JsonResponse({"ok": False, "detail": "No matching leads."}, status=404)

    if raw_gid is None:
        uncategorized = get_or_create_uncategorized_group()
        apply_group_assignment_side_effects(leads_before, uncategorized)
        updated = Lead.objects.filter(pk__in=id_list).update(group=uncategorized)
        return JsonResponse(
            {
                "ok": True,
                "updated": updated,
                "group_id": uncategorized.pk,
                "group_name": uncategorized.name,
            }
        )

    try:
        gid = int(raw_gid)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "detail": "group_id must be an integer or null."}, status=400)

    group = get_object_or_404(LeadGroup, pk=gid)
    apply_group_assignment_side_effects(leads_before, group)
    updated = Lead.objects.filter(pk__in=id_list).update(group=group)
    return JsonResponse({"ok": True, "updated": updated, "group_id": group.pk, "group_name": group.name})


def clinics_export_xlsx(request):
    """Download leads as ``.xlsx``.

    Query params:
    - ``group_id``: ``uncategorized`` or a LeadGroup primary key — only rows in that folder (required from dashboard).
    - ``ids``: optional comma-separated primary keys; further restricts to that subset (e.g. checked rows).
    If ``group_id`` is omitted, all leads are eligible (legacy); the dashboard always sends ``group_id``.
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        return HttpResponse(
            "openpyxl is not installed. Run: pip install openpyxl\n"
            "With Docker: rebuild the web image so requirements.txt is applied (docker compose up --build).",
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    qs = Lead.objects.all().order_by("display_order", "-created_at")
    group_id = (request.GET.get("group_id") or "").strip().lower()
    if group_id:
        if group_id == "uncategorized":
            qs = qs.filter(uncategorized_group_filter())
        elif group_id.isdigit():
            qs = qs.filter(group_id=int(group_id))
        else:
            return HttpResponse(
                "Invalid group_id. Use uncategorized or a numeric folder id.",
                status=400,
                content_type="text/plain; charset=utf-8",
            )

    raw_ids = (request.GET.get("ids") or "").strip()
    if raw_ids:
        id_list = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
        if id_list:
            qs = qs.filter(pk__in=id_list)

    first_outbound = ChatMessage.objects.filter(
        lead_id=OuterRef("pk"), is_outbound=True
    ).order_by("created_at", "id")
    qs = qs.annotate(
        _first_sent_at=Subquery(first_outbound.values("created_at")[:1]),
    ).annotate(
        first_sent_body=Subquery(first_outbound.values("body")[:1]),
        has_first_response=Exists(
            ChatMessage.objects.filter(
                lead_id=OuterRef("pk"),
                is_outbound=False,
                created_at__gt=OuterRef("_first_sent_at"),
            )
        ),
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(
        [
            "ID",
            "Name",
            "Phone",
            "Address",
            "Website",
            "Keyword",
            "Category",
            "Search city",
            "Search country",
            "Maps query",
            "Chain",
            "Very important",
            "Processed",
            "Source URL",
            "First message sent",
            "Response",
            "Created",
        ]
    )
    for c in qs.iterator(chunk_size=400):
        plist = lead_phone_list(c)
        ws.append(
            [
                c.pk,
                c.name,
                " ; ".join(plist) if plist else "",
                c.address or "",
                c.website or "",
                c.shop_keyword or "",
                c.category,
                c.search_city or "",
                c.search_country or "",
                c.search_query or "",
                c.is_chain,
                c.is_very_important,
                c.is_processed,
                c.source_url or "",
                (c.first_sent_body or "")[:32000],
                bool(c.has_first_response),
                (
                    django_timezone.localtime(c.created_at).strftime("%Y-%m-%d %H:%M")
                    if c.created_at
                    else ""
                ),
            ]
        )

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"business_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@require_GET
def export_full_backup_xlsx(request):
    """Download a full multi-sheet ``.xlsx`` backup of all leads across every folder.

    Includes leads (with group membership), groups, WhatsApp chats, conversation
    logs, the campaign config, and script templates — re-importable after deploy.
    """
    try:
        from leads.backup import build_backup_workbook

        wb = build_backup_workbook()
    except ImportError:
        return HttpResponse(
            "openpyxl is not installed. Run: pip install openpyxl",
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"clinic_crm_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@csrf_protect
@require_POST
def import_full_backup_xlsx(request):
    """Restore a backup workbook (multipart upload, field ``backup``).

    Existing leads (matched by name + address) are skipped; only missing leads
    and their history are created.
    """
    upload = request.FILES.get("backup")
    if not upload:
        return JsonResponse(
            {"ok": False, "detail": "No backup file uploaded."}, status=400
        )
    name = (upload.name or "").lower()
    if not name.endswith(".xlsx"):
        return JsonResponse(
            {"ok": False, "detail": "Please upload an .xlsx backup file."}, status=400
        )
    try:
        from leads.backup import restore_from_workbook

        summary = restore_from_workbook(upload)
    except ImportError:
        return JsonResponse(
            {"ok": False, "detail": "openpyxl is not installed."}, status=503
        )
    except Exception as exc:  # noqa: BLE001 - surface any parse/restore error to UI
        return JsonResponse(
            {"ok": False, "detail": f"Restore failed: {exc}"}, status=400
        )
    return JsonResponse({"ok": True, **summary})


@csrf_protect
@require_POST
def hunt_trigger(request):
    """
    Serper hunt entrypoint for the dashboard: ``limit`` from query string,
    ``city`` and ``query`` from JSON body.
    """
    try:
        raw_limit = request.GET.get("limit", "20")
        limit = max(1, min(int(raw_limit), 100))
    except (TypeError, ValueError):
        limit = 20

    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    city = (body.get("city") or "").strip()
    state = (body.get("state") or "").strip()
    country = (body.get("country") or "").strip()
    query = (body.get("query") or "").strip()
    shop_keyword = (body.get("shop_keyword") or body.get("shop_type") or "").strip()
    require_website = body.get("require_website", False)
    if isinstance(require_website, str):
        require_website = require_website.strip().lower() in ("1", "true", "yes", "on")
    if not isinstance(require_website, bool):
        require_website = bool(require_website)
    if not city:
        return JsonResponse({"detail": "city is required."}, status=400)
    if not state:
        return JsonResponse({"detail": "state is required."}, status=400)
    if not shop_keyword:
        return JsonResponse({"detail": "shop_keyword is required."}, status=400)

    rec = SearchQueryRecord.objects.create(
        keyword=shop_keyword[:160],
        maps_search_query=(query or shop_keyword)[:255],
        search_city=city[:255],
        search_state=state[:255],
        search_country=country[:255],
    )

    try:
        result = fetch_leads_from_serper(
            city,
            query,
            num=limit,
            shop_keyword=shop_keyword,
            state=state,
            country=country,
            search_query_record=rec,
            require_website=require_website,
        )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    if result.errors and result.places_seen == 0 and result.created == 0:
        return JsonResponse(
            {"detail": "; ".join(result.errors[:3]) or "Hunt failed."},
            status=502,
        )

    message = (
        f"Processed {result.places_seen} place(s). "
        f"Created {result.created}, already had {result.skipped_existing}."
    )
    if result.skipped_duplicate_phone:
        message += f" Skipped {result.skipped_duplicate_phone} duplicate phone(s)."
    if getattr(result, "skipped_no_website", 0):
        message += f" Skipped {result.skipped_no_website} with no website/social link."
    return JsonResponse(
        {
            "ok": True,
            "created": result.created,
            "skipped_existing": result.skipped_existing,
            "skipped_duplicate_phone": result.skipped_duplicate_phone,
            "skipped_no_website": getattr(result, "skipped_no_website", 0),
            "places_seen": result.places_seen,
            "errors": result.errors,
            "message": message,
            "search_record_id": rec.pk,
        }
    )


def _same_brand_row_count(lead: Lead) -> int:
    name = (lead.name or "").strip()
    if not name:
        return 0
    return Lead.objects.filter(name__iexact=name).count()


def _branches_line_inner_html(lead: Lead, same_brand_count: int) -> str:
    """HTML fragment for `.clinic-branches-line` (empty if no branch signal to show)."""
    if same_brand_count >= 2:
        return f"{same_brand_count} locations in CRM"
    est = lead.location_count_estimate
    if est is not None and est >= 1:
        n = int(est)
        return f"~{n} branches <span class=\"text-slate-400\">(estimate)</span>"
    return ""


def _category_badges_html(lead: Lead) -> str:
    return category_badge_html(lead.category)


def _name_cell_html(lead: Lead) -> str:
    """Inner HTML for `.clinic-name-cell-inner` (name → Google Maps + optional chain suffix)."""
    suffix = clinic_location_suffix(lead)
    suffix_html = ""
    if lead.is_chain and suffix:
        suffix_html = (
            '<span class="text-xs text-gray-400">'
            f"(@ {html.escape(suffix)})"
            "</span>"
        )
    name_esc = html.escape(lead.name or "")
    maps_esc = html.escape(lead_google_maps_url(lead), quote=True)
    return (
        f'<a href="{maps_esc}" class="clinic-name-link text-sm font-bold text-slate-900 '
        "underline decoration-slate-300 decoration-1 underline-offset-2 transition "
        'hover:text-indigo-600 hover:decoration-indigo-300" target="_blank" rel="noopener" '
        'title="Open in Google Maps">'
        f"{name_esc}{suffix_html}</a>"
    )


def _wa_icon_link_html(phone_number: str, *, for_grid: bool = False) -> str:
    """WhatsApp icon control: copies ``wa.me/<digits>`` to clipboard (see dashboard JS)."""
    path = whatsapp_me_path(phone_number or "")
    if not path:
        return ""
    path_e = html.escape(path, quote=True)
    if for_grid:
        btn_cls = (
            "wa-me-link-copy-btn inline-flex rounded-lg p-1.5 text-emerald-600 transition hover:bg-emerald-50"
        )
    else:
        btn_cls = (
            "wa-me-link-copy-btn inline-flex shrink-0 rounded-lg p-1.5 text-emerald-600 transition "
            "hover:bg-emerald-50 hover:text-emerald-700"
        )
    return (
        f'<button type="button" class="{btn_cls}" data-wa-me-copy="{path_e}" title="Copy WhatsApp link">'
        '<span class="sr-only">Copy WhatsApp link</span>'
        '<svg class="h-5 w-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.435 9.884-9.881 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"/></svg>'
        "</button>"
    )


def _phone_contact_stack_html(phones: list[str], *, for_grid: bool) -> str:
    """Stack of phone lines (number + WhatsApp icon); used in list table and grid."""
    inner_cls = (
        "clinic-phone-inner min-w-0 text-sm font-medium text-slate-700"
        if for_grid
        else "clinic-phone-inner min-w-0 whitespace-normal break-words text-sm font-medium tabular-nums text-slate-800"
    )
    if not phones:
        wa = _wa_icon_link_html("", for_grid=for_grid)
        dash = wa if wa else '<span class="text-xs text-slate-400">—</span>'
        row = (
            f'<div class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">'
            f'<p class="{inner_cls}">—</p>'
            f'<span class="clinic-phone-wa-row inline-flex shrink-0 items-center leading-none">{dash}</span>'
            f"</div>"
        )
        return f'<div class="space-y-1">{row}</div>'
    parts: list[str] = []
    for ph in phones:
        esc = html.escape(ph)
        wa = _wa_icon_link_html(ph, for_grid=for_grid)
        wa_html = wa if wa else '<span class="text-xs text-slate-400">—</span>'
        parts.append(
            f'<div class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">'
            f'<p class="{inner_cls}">{esc}</p>'
            f'<span class="clinic-phone-wa-row inline-flex shrink-0 items-center leading-none">{wa_html}</span>'
            f"</div>"
        )
    return f'<div class="space-y-1">{"".join(parts)}</div>'


def _phone_td_inner_list_html(phones: list[str]) -> str:
    return (
        f'<div class="clinic-phone-cell-contents">{_phone_contact_stack_html(phones, for_grid=False)}</div>'
    )


def _phone_slot_inner_grid_html(phones: list[str]) -> str:
    return f'<div class="mt-2 clinic-phone-slot">{_phone_contact_stack_html(phones, for_grid=True)}</div>'


def _actions_cell_html_list(lead: Lead) -> str:
    """List table: edit, move to group, conversation log."""
    return render_to_string(
        "leads/partials/_lead_list_row_actions.html",
        {"c": lead},
    )


def _actions_cell_html_grid(_lead: Lead) -> str:
    """Grid: no action footer (WhatsApp under phone; edit is top-right)."""
    return ""


def _clinic_edit_payload(lead: Lead, request=None) -> dict:
    """Shared JSON shape for PATCH lead and incremental dashboard DOM updates."""
    brand_n = _same_brand_row_count(lead)
    branches_html = _branches_line_inner_html(lead, brand_n)
    cat = lead.category
    phones = lead_phone_list(lead)
    primary = phones[0] if phones else ""
    payload = {
        "ok": True,
        "id": lead.pk,
        "name": lead.name,
        "phone_numbers": phones,
        "phone_number": primary,
        "address": lead.address or "",
        "website": lead.website or "",
        "category": cat,
        "clinic_type": cat,
        "search_city": lead.search_city or "",
        "search_state": lead.search_state or "",
        "search_country": lead.search_country or "",
        "shop_keyword": lead.shop_keyword or "",
        "search_query": lead.search_query or "",
        "is_chain": lead.is_chain,
        "is_very_important": lead.is_very_important,
        "is_processed": lead.is_processed,
        "location_count_estimate": lead.location_count_estimate,
        "same_brand_count": brand_n,
        "whatsapp_draft": lead.whatsapp_draft or "",
        "whatsapp_status": lead.whatsapp_status,
        "whatsapp_dispatched": lead_whatsapp_dispatched(lead),
        "card_title": clinic_card_title(lead),
        "whatsapp_me_url": whatsapp_me_url(lead.phone_number or ""),
        "name_cell_html": _name_cell_html(lead),
        "actions_cell_html": _actions_cell_html_list(lead),
        "grid_actions_cell_html": _actions_cell_html_grid(lead),
        "phone_td_inner_list": _phone_td_inner_list_html(phones),
        "phone_slot_inner_grid": _phone_slot_inner_grid_html(phones),
        "type_html": _category_badges_html(lead),
        "branches_line_html": branches_html,
    }
    if request is not None:
        payload["grid_bottom_actions_html"] = render_to_string(
            "leads/partials/_lead_grid_bottom_actions.html",
            _lead_grid_action_context(request, lead),
            request=request,
        )
    return payload


@csrf_protect
@require_http_methods(["PATCH"])
def clinic_update(request, pk: int):
    """Update a lead from the dashboard edit modal (JSON body)."""
    lead = get_object_or_404(Lead, pk=pk)
    previous_name = lead.name
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"detail": "Name is required."}, status=400)

    raw_type = (body.get("category") or body.get("clinic_type") or "unknown").strip().lower()
    _allowed_types = {c[0] for c in Lead.Category.choices}
    if raw_type not in _allowed_types:
        return JsonResponse({"detail": "Invalid category."}, status=400)

    lead.name = name[:255]
    old_phones = lead_phone_list(lead)
    phones = _normalize_phone_numbers_body(body)
    reset_lead_whatsapp_after_phone_change(
        lead, old_phones=old_phones, new_phones=phones
    )
    lead.phone_numbers = phones
    lead.phone_number = phones[0][:64] if phones else ""
    lead.address = (body.get("address") or "").strip()
    website = (body.get("website") or "").strip()
    lead.website = website[:500] if website else ""
    lead.category = raw_type
    sc = (body.get("search_city") or "").strip()
    ss = (body.get("search_state") or "").strip()
    sco = (body.get("search_country") or "").strip()
    sq = (body.get("search_query") or "").strip()
    lead.search_city = sc or None
    lead.search_state = ss or None
    lead.search_country = sco or None
    lead.search_query = sq or None
    lead.is_chain = bool(body.get("is_chain"))
    if "is_very_important" in body:
        lead.is_very_important = bool(body.get("is_very_important"))
    if "whatsapp_draft" in body:
        lead.whatsapp_draft = (body.get("whatsapp_draft") or "").strip()
    lead.is_processed = True

    try:
        lead.save()
    except IntegrityError:
        return JsonResponse(
            {
                "detail": "A lead with this name and address already exists.",
            },
            status=400,
        )

    sync_chain_flags_for_name(previous_name)
    sync_chain_flags_for_name(lead.name)

    lead.refresh_from_db()
    return JsonResponse(_clinic_edit_payload(lead, request=request))


@csrf_protect
@require_POST
def lead_manual_create(request):
    """Create a lead from the dashboard; optional ``group_id`` (folder) or uncategorized."""
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"detail": "Name is required."}, status=400)

    raw_type = (body.get("category") or body.get("clinic_type") or "unknown").strip().lower()
    _allowed_types = {c[0] for c in Lead.Category.choices}
    if raw_type not in _allowed_types:
        return JsonResponse({"detail": "Invalid category."}, status=400)

    group = get_or_create_uncategorized_group()
    raw_gid = body.get("group_id", "uncategorized")
    if raw_gid not in (None, "", "uncategorized", "all"):
        try:
            gid = int(raw_gid)
        except (TypeError, ValueError):
            return JsonResponse({"detail": "Invalid group_id."}, status=400)
        resolved = LeadGroup.objects.filter(pk=gid).first()
        if not resolved:
            return JsonResponse({"detail": "Folder not found."}, status=400)
        group = resolved

    address = (body.get("address") or "").strip()
    phones = _normalize_phone_numbers_body(body)
    phone_number = phones[0][:64] if phones else ""
    website_raw = (body.get("website") or "").strip()
    website = website_raw[:500] if website_raw else ""

    next_order = (
        Lead.objects.filter(group=group).aggregate(m=Max("display_order"))["m"] or 0
    ) + 1

    lead = Lead(
        name=name[:255],
        address=address,
        phone_number=phone_number,
        phone_numbers=list(phones),
        website=website,
        category=raw_type,
        group=group,
        whatsapp_status=Lead.WhatsappStatus.IDLE,
        display_order=next_order,
        is_processed=True,
    )
    try:
        lead.save()
    except IntegrityError:
        return JsonResponse(
            {"detail": "A lead with this name and address already exists."},
            status=400,
        )

    if group.name == QUEUE_GROUP_NAME and lead_has_dispatchable_phone(lead):
        lead.whatsapp_status = Lead.WhatsappStatus.PENDING
        lead.save(update_fields=["whatsapp_status"])

    sync_chain_flags_for_name(lead.name)
    lead.refresh_from_db()
    return JsonResponse(_clinic_edit_payload(lead))


def _lead_conversation_log_payload(log: LeadConversationLog) -> dict:
    return {
        "id": log.pk,
        "lead_id": log.lead_id,
        "conversation_date": log.conversation_date.isoformat(),
        "remarks": log.remarks,
        "created_at": log.created_at.isoformat(),
    }


@csrf_protect
@require_http_methods(["GET", "POST"])
def create_lead_conversation_log(request, pk: int):
    """Read or append dated conversation remarks for one lead."""
    lead = get_object_or_404(Lead, pk=pk)
    if request.method == "GET":
        logs = list(
            LeadConversationLog.objects.filter(lead=lead).order_by(
                "-conversation_date", "-created_at", "-id"
            )[:30]
        )
        return JsonResponse(
            {"ok": True, "lead_id": lead.pk, "logs": [_lead_conversation_log_payload(x) for x in logs]}
        )

    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    raw_date = (body.get("conversation_date") or "").strip()
    raw_remarks = (body.get("remarks") or "").strip()
    if not raw_date:
        return JsonResponse({"detail": "Date is required."}, status=400)
    if not raw_remarks:
        return JsonResponse({"detail": "Remarks are required."}, status=400)
    try:
        parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"detail": "Date must use YYYY-MM-DD format."}, status=400)

    log = LeadConversationLog.objects.create(
        lead=lead,
        conversation_date=parsed_date,
        remarks=raw_remarks,
    )
    return JsonResponse(
        {
            "ok": True,
            **_lead_conversation_log_payload(log),
        }
    )


@csrf_protect
@require_http_methods(["DELETE"])
def delete_lead_conversation_log(request, pk: int, log_id: int):
    """Delete a single conversation log for a lead."""
    lead = get_object_or_404(Lead, pk=pk)
    log = get_object_or_404(LeadConversationLog, pk=log_id, lead=lead)
    deleted_id = log.pk
    log.delete()
    return JsonResponse({"ok": True, "id": deleted_id, "lead_id": lead.pk})


@csrf_protect
@require_http_methods(["PATCH"])
def patch_lead_very_important(request, pk: int):
    """Set dashboard \"very important\" (star); JSON ``{\"is_very_important\": true|false}``."""
    lead = get_object_or_404(Lead, pk=pk)
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)
    if "is_very_important" not in body:
        return JsonResponse({"detail": "is_very_important is required."}, status=400)
    val = body.get("is_very_important")
    if not isinstance(val, bool):
        return JsonResponse({"detail": "is_very_important must be a boolean."}, status=400)
    lead.is_very_important = val
    lead.save(update_fields=["is_very_important"])
    return JsonResponse({"ok": True, "id": lead.pk, "is_very_important": lead.is_very_important})


@csrf_protect
@require_http_methods(["DELETE"])
def lead_delete(request, pk: int):
    """Permanently delete a lead (dashboard grid / list)."""
    lead = get_object_or_404(Lead, pk=pk)
    name_for_sync = (lead.name or "").strip()
    lead_id = lead.pk
    try:
        lead.delete()
    except ProtectedError:
        return JsonResponse(
            {"detail": "Cannot delete this lead because other records reference it."},
            status=400,
        )
    if name_for_sync:
        sync_chain_flags_for_name(name_for_sync)
    return JsonResponse({"ok": True, "id": lead_id})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    """Meta Cloud API webhook — GET verify handshake, POST inbound message sync."""
    if request.method == "GET":
        return handle_meta_webhook_verify(request)
    body, status = process_whatsapp_webhook(request)
    return JsonResponse(body, status=status)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook_receiver(request):
    """
    Meta Cloud API webhook at ``/whatsapp/webhook/``.

  GET — ``hub.challenge`` verification (``WHATSAPP_WEBHOOK_VERIFY_TOKEN``).
  POST — ingest inbound client text into ``ChatMessage`` + ``LeadConversationLog``.
    """
    if request.method == "GET":
        return handle_meta_webhook_verify(request)
    body, status = process_whatsapp_webhook(request)
    return JsonResponse(body, status=status)


@csrf_protect
@require_POST
def chain_brand_mark_contacted(request):
    """
    Mark every lead sharing a brand name as contacted.

    JSON: ``brand_key`` or ``name`` (required), optional ``remarks`` (default bulk message).
    Creates a conversation log on each branch that has none yet; sets ``ChainBrandStatus.chain_contacted``.
    """
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON body."}, status=400)

    brand_key = _normalize_brand_key(body.get("brand_key") or body.get("name") or "")
    if not brand_key:
        return JsonResponse({"ok": False, "detail": "brand_key or name is required."}, status=400)

    remarks = (body.get("remarks") or "Chain marked as contacted (bulk).").strip()
    if not remarks:
        remarks = "Chain marked as contacted (bulk)."

    leads = list(Lead.objects.annotate(ln=Lower("name")).filter(ln=brand_key))
    if not leads:
        return JsonResponse({"ok": False, "detail": "No leads found for this brand."}, status=404)

    today = django_timezone.localdate()
    logs_created = 0
    with transaction.atomic():
        status, _ = ChainBrandStatus.objects.update_or_create(
            brand_key=brand_key,
            defaults={
                "chain_contacted": True,
                "contacted_at": django_timezone.now(),
            },
        )
        for lead in leads:
            if LeadConversationLog.objects.filter(lead=lead).exists():
                continue
            LeadConversationLog.objects.create(
                lead=lead,
                conversation_date=today,
                remarks=remarks,
            )
            logs_created += 1

    return JsonResponse(
        {
            "ok": True,
            "brand_key": brand_key,
            "chain_contacted": True,
            "leads_in_chain": len(leads),
            "logs_created": logs_created,
            "contacted_at": (
                django_timezone.localtime(status.contacted_at).isoformat()
                if status.contacted_at
                else None
            ),
        }
    )


@csrf_protect
@require_POST
def chain_brand_exempt(request):
    """
    Exempt (or clear exemption for) an entire chain brand from further spamming.

    JSON: ``brand_key`` or ``name`` (required), ``exempt_from_spam`` (bool, default true).
    """
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "detail": "Invalid JSON body."}, status=400)

    brand_key = _normalize_brand_key(body.get("brand_key") or body.get("name") or "")
    if not brand_key:
        return JsonResponse({"ok": False, "detail": "brand_key or name is required."}, status=400)

    raw_exempt = body.get("exempt_from_spam", True)
    if isinstance(raw_exempt, str):
        exempt = raw_exempt.strip().lower() in ("1", "true", "yes", "on")
    else:
        exempt = bool(raw_exempt)

    leads_count = Lead.objects.annotate(ln=Lower("name")).filter(ln=brand_key).count()
    if not leads_count:
        return JsonResponse({"ok": False, "detail": "No leads found for this brand."}, status=404)

    status, _ = ChainBrandStatus.objects.update_or_create(
        brand_key=brand_key,
        defaults={"exempt_from_spam": exempt},
    )
    return JsonResponse(
        {
            "ok": True,
            "brand_key": brand_key,
            "exempt_from_spam": status.exempt_from_spam,
            "leads_in_chain": leads_count,
        }
    )


@csrf_protect
@require_POST
def leads_bulk_manual_category(request):
    """Set ``category`` and ``is_processed`` for many leads without external API calls."""
    try:
        body = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    ids = body.get("ids")
    if not isinstance(ids, list):
        return JsonResponse({"detail": "ids must be a list."}, status=400)

    raw_cat = (body.get("category") or body.get("clinic_type") or "").strip().lower()
    allowed = {c[0] for c in Lead.Category.choices}
    if raw_cat not in allowed:
        return JsonResponse({"detail": "Invalid category."}, status=400)

    id_list: list[int] = []
    for x in ids:
        try:
            id_list.append(int(x))
        except (TypeError, ValueError):
            continue
    if not id_list:
        return JsonResponse({"detail": "No valid ids."}, status=400)

    updated = Lead.objects.filter(pk__in=id_list).update(
        category=raw_cat,
        is_processed=True,
    )
    return JsonResponse({"ok": True, "updated": updated, "category": raw_cat})
