"""Display helpers for lead UI (card titles, WhatsApp links, category badges)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from leads.models import Lead


def clinic_location_suffix(lead: "Lead") -> str:
    """Short area label for chain rows (search city or address tail)."""
    sc = (getattr(lead, "search_city", None) or "").strip()
    if sc:
        return sc
    addr = (getattr(lead, "address", None) or "").strip()
    if not addr:
        return ""
    if "," in addr:
        tail = addr.split(",")[-1].strip()
        if len(tail) > 1:
            return tail[:120]
    line = addr.split("\n")[0].strip()
    return line[:120] if line else ""


def clinic_card_title(lead: "Lead") -> str:
    """Bold card line: brand name plus area hint."""
    name = (getattr(lead, "name", None) or "").strip() or "Lead"
    sc = (getattr(lead, "search_city", None) or "").strip()
    if sc:
        return f"{name} – {sc}"
    addr = (getattr(lead, "address", None) or "").strip()
    if addr and "," in addr:
        tail = addr.split(",")[-1].strip()
        if len(tail) > 1:
            return f"{name} – {tail}"
    if addr:
        line = addr.split("\n")[0].strip()
        if line and line.lower() != name.lower():
            return f"{name} – {line[:80]}"
    return name


def _is_coordinate_maps_search_url(url: str) -> bool:
    """True when a Maps search URL query is lat,lng only (not a named place)."""
    from urllib.parse import parse_qs, urlparse

    low = (url or "").strip().lower()
    if "google.com/maps" not in low and "maps.google.com" not in low:
        return False
    query = parse_qs(urlparse(url).query).get("query", [""])[0].strip()
    if not query:
        return False
    parts = query.split(",")
    if len(parts) != 2:
        return False
    try:
        float(parts[0].strip())
        float(parts[1].strip())
    except ValueError:
        return False
    return True


def lead_google_maps_url(lead: "Lead") -> str:
    """URL to open this lead in Google Maps (saved place link, or search by name + address)."""
    src = (getattr(lead, "source_url", None) or "").strip()
    if src:
        low = src.lower()
        if any(
            frag in low
            for frag in (
                "google.com/maps",
                "maps.google.com",
                "goo.gl/maps",
                "maps.app.goo.gl",
            )
        ) and not _is_coordinate_maps_search_url(src):
            return src[:2000]
    name = (getattr(lead, "name", None) or "").strip()
    addr = (getattr(lead, "address", None) or "").strip()
    if name and addr:
        q = f"{name} {addr}"
    else:
        q = name or addr
    if not q:
        return "https://www.google.com/maps"
    return "https://www.google.com/maps/search/?api=1&query=" + quote(q, safe="")


def lead_phone_list(lead) -> list[str]:
    """
    All phones for a lead: JSON list when set, otherwise legacy ``phone_number`` only.
    Order preserved; duplicates removed.
    """
    raw = getattr(lead, "phone_numbers", None)
    if isinstance(raw, list) and raw:
        out: list[str] = []
        for p in raw:
            s = str(p).strip() if p is not None else ""
            if not s:
                continue
            normalized = normalize_manual_phone(s) or s
            if normalized and normalized not in out:
                out.append(normalized[:64])
        if out:
            return out
    one = (getattr(lead, "phone_number", None) or "").strip()
    if one:
        normalized = normalize_manual_phone(one) or one
        return [normalized[:64]]
    return []


def normalize_manual_phone(phone: str) -> str:
    """
    Normalize phone typed in the dashboard (create/edit): strip spaces, hyphens, parentheses, etc.
    Default country code +60 (Malaysia). Returns E.164-style ``+60…`` or ``+<cc>…`` for longer
    international numbers; empty string if no digits.
    """
    if not phone or not str(phone).strip():
        return ""
    digits = "".join(ch for ch in str(phone).strip() if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    # Repair double country prefix from prior normalization (e.g. +60607… → +607…).
    if digits.startswith("6060") and len(digits) >= 11:
        digits = "60" + digits[4:]
    if digits.startswith("60") and len(digits) >= 10:
        return "+" + digits[:15]
    if digits[0] == "0" and len(digits) >= 9:
        return "+60" + digits[1:15]
    if 8 <= len(digits) <= 10:
        return "+60" + digits[:15]
    if len(digits) >= 11:
        return "+" + digits[:15]
    return "+60" + digits[:15]


AUTOMATOR_LOG_MARKER = "Touchpoint Automator"


def lead_has_dispatchable_phone(lead: "Lead") -> bool:
    """True when at least one stored number normalizes to a wa.me dispatch target."""
    for raw in lead_phone_list(lead):
        if whatsapp_me_url(raw):
            return True
    return False


_ACTIVE_WHATSAPP_BATCH_STATUSES = frozenset({"pending", "processing"})


def lead_in_active_whatsapp_batch(lead: "Lead") -> bool:
    """True when the lead is assigned to a not-yet-finished WhatsApp batch."""
    cached = getattr(lead, "has_active_whatsapp_batch", None)
    if cached is not None:
        return bool(cached)
    batches = getattr(lead, "whatsapp_batches", None)
    if batches is None:
        return False
    cache = getattr(lead, "_prefetched_objects_cache", None)
    if cache is not None and "whatsapp_batches" in cache:
        return any(
            (getattr(batch, "status", "") or "").strip().lower()
            in _ACTIVE_WHATSAPP_BATCH_STATUSES
            for batch in cache["whatsapp_batches"]
        )
    from leads.models import WhatsAppBatchSchedule

    return batches.filter(
        status__in=[
            WhatsAppBatchSchedule.Status.PENDING,
            WhatsAppBatchSchedule.Status.PROCESSING,
        ]
    ).exists()


def lead_whatsapp_dispatched(lead: "Lead") -> bool:
    """True once the lead has a chat record (Sent chip next to the WhatsApp icon).

    A chat record exists after the first outbound WhatsApp was sent, but also for
    any lead that already has a WhatsApp chat thread (e.g. tested via the Meta
    Cloud API) regardless of the lead's ``whatsapp_status``.
    """
    if getattr(lead, "whatsapp_sent_at", None):
        return True
    status = (getattr(lead, "whatsapp_status", None) or "").strip().lower()
    if status == "sent":
        return True
    has_chat = getattr(lead, "has_chat_message", None)
    if has_chat is not None:
        return bool(has_chat)
    from leads.models import ChatMessage

    return ChatMessage.objects.filter(lead_id=lead.pk).exists()


def lead_whatsapp_active_chat(lead: "Lead") -> bool:
    """
    True when the client's latest chat message is still awaiting a staff reply
    (pulsing dot + Active Chat tab). Outbound-only threads are not active chat.
    """
    if not lead_whatsapp_dispatched(lead):
        return False
    awaiting = getattr(lead, "has_awaiting_client_reply", None)
    if awaiting is not None:
        return awaiting is True
    from leads.models import ChatMessage

    latest = (
        ChatMessage.objects.filter(lead_id=lead.pk)
        .order_by("-created_at", "-id")
        .only("is_outbound")
        .first()
    )
    return latest is not None and not latest.is_outbound


def whatsapp_me_url(phone: str) -> str:
    """Build https://wa.me/... for Malaysian-style numbers when possible."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) >= 9:
        digits = "60" + digits[1:]
    elif not digits.startswith("60") and 8 <= len(digits) <= 11:
        digits = "60" + digits
    return f"https://wa.me/{digits}"


def whatsapp_me_path(phone: str) -> str:
    """Clipboard form ``wa.me/<digits>`` (no scheme), same normalization as ``whatsapp_me_url``."""
    url = whatsapp_me_url(phone or "")
    if not url:
        return ""
    if url.startswith("https://"):
        return url[8:]
    if url.startswith("http://"):
        return url[7:]
    return url


def lead_tag_chip_modifier(slug: str) -> str:
    """CSS modifier for a tag chip (known categories get a tint; others share a default)."""
    key = (slug or "").strip().lower()
    known = {
        "gp",
        "aesthetic",
        "dental",
        "fitness",
        "cafe",
        "retail",
        "service",
        "unknown",
    }
    return key if key in known else "default"


def category_badge_html(category: str) -> str:
    """Pill HTML for a lead category slug (server-side list/grid and JSON patches)."""
    from leads.category_types import UNKNOWN_SLUG, category_label_for

    t = (category or UNKNOWN_SLUG).strip().lower()
    mod = lead_tag_chip_modifier(t)
    label_esc = html.escape(category_label_for(t))
    return f'<span class="lead-tag-chip lead-tag-chip--{mod}">{label_esc}</span>'
