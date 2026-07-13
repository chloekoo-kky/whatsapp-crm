"""Aggregate external API configuration and local usage for the sidebar widget."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from leads.models import Lead, SearchQueryRecord
from leads.whatsapp_service import fetch_gateway_status, queue_counts


def _serper_configured() -> bool:
    return bool((getattr(settings, "SERPER_API_KEY", "") or "").strip())


def get_api_sidebar_context() -> dict:
    """Build status + usage snapshot for YCloud WhatsApp and Serper Maps."""
    connection = fetch_gateway_status()
    ycloud_connected = bool(connection.get("connected"))
    counts = queue_counts()
    today = timezone.localdate()

    wa_today = (
        Lead.objects.filter(whatsapp_sent_at__date=today)
        .exclude(phone_number="")
        .count()
    )
    hunts_total = SearchQueryRecord.objects.count()
    hunts_today = SearchQueryRecord.objects.filter(created_at__date=today).count()

    return {
        "ycloud": {
            "configured": ycloud_connected,
            "status_label": "Connected" if ycloud_connected else "Not configured",
            "sent_total": counts["sent"],
            "sent_today": wa_today,
            "pending": counts["pending"],
            "error": connection.get("error"),
        },
        "serper": {
            "configured": _serper_configured(),
            "status_label": "Ready" if _serper_configured() else "Not configured",
            "hunts_total": hunts_total,
            "hunts_today": hunts_today,
        },
        "refreshed_at": timezone.localtime().strftime("%H:%M"),
    }
