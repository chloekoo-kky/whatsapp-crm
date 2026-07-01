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


def lead_google_maps_url(lead: "Lead") -> str:
    """URL to open this lead in Google Maps (saved Maps link, or search by name + address)."""
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
        ):
            return src[:2000]
    name = (getattr(lead, "name", None) or "").strip()
    addr = (getattr(lead, "address", None) or "").strip()
    q = f"{name} {addr}".strip() or name
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
            if s and s not in out:
                out.append(s[:64])
        if out:
            return out
    one = (getattr(lead, "phone_number", None) or "").strip()
    return [one] if one else []


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
    if digits.startswith("60") and len(digits) >= 11:
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


def lead_whatsapp_dispatched(lead: "Lead") -> bool:
    """True once the lead has a chat record (permanent green-frame card chrome).

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


def category_badge_html(category: str) -> str:
    """Tailwind pill HTML for a lead category slug (server-side list/grid and JSON patches)."""
    from leads.category_types import UNKNOWN_SLUG, category_label_for

    t = (category or UNKNOWN_SLUG).strip().lower()
    palette = {
        "gp": ("bg-sky-100", "text-sky-900"),
        "aesthetic": ("bg-fuchsia-100", "text-fuchsia-900"),
        "dental": ("bg-teal-100", "text-teal-900"),
        "fitness": ("bg-violet-100", "text-violet-900"),
        "cafe": ("bg-amber-100", "text-amber-950"),
        "retail": ("bg-lime-100", "text-lime-900"),
        "service": ("bg-indigo-100", "text-indigo-900"),
        "invalid": ("bg-red-100", "text-red-900"),
        "unknown": ("bg-slate-100", "text-slate-700"),
    }
    bg, fg = palette.get(t, ("bg-slate-100", "text-slate-800"))
    label = category_label_for(t)
    label_esc = html.escape(label)
    return (
        f'<span class="inline-flex rounded-full {bg} px-2.5 py-0.5 text-xs '
        f"font-semibold {fg}\">{label_esc}</span>"
    )
