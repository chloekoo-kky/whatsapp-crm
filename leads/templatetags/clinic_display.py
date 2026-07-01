from django import template
from django.utils.safestring import mark_safe

from leads.display import (
    category_badge_html,
    clinic_card_title,
    clinic_location_suffix,
    lead_google_maps_url,
    lead_whatsapp_active_chat,
    lead_whatsapp_dispatched,
    whatsapp_me_path,
    whatsapp_me_url,
)
from leads.whatsapp_service import campaign_timezone

register = template.Library()


@register.filter
def card_title(clinic):
    return clinic_card_title(clinic)


@register.filter
def wa_me_url(phone):
    return whatsapp_me_url(phone or "")


@register.filter
def wa_me_path(phone):
    return whatsapp_me_path(phone or "")


@register.filter
def location_suffix(clinic):
    return clinic_location_suffix(clinic)


@register.filter
def category_badge(cat):
    return mark_safe(category_badge_html(cat or ""))


@register.filter
def google_maps_url(clinic):
    return lead_google_maps_url(clinic)


@register.filter
def whatsapp_active_chat(clinic):
    return lead_whatsapp_active_chat(clinic)


@register.filter
def whatsapp_dispatched(clinic):
    return lead_whatsapp_dispatched(clinic)


@register.filter
def chat_outbound_is_template(msg):
    from leads.chat_messages import outbound_message_is_template

    return outbound_message_is_template(msg)


@register.filter
def chat_time(value):
    """Render chat timestamps in the campaign timezone (not UTC)."""
    if value is None:
        return ""
    try:
        local = value.astimezone(campaign_timezone())
    except (TypeError, ValueError, OSError):
        return ""
    return local.strftime("%H:%M")
