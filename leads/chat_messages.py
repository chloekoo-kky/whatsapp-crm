"""Persist and load Meta WhatsApp chat rows for the lead inbox drawer."""

from __future__ import annotations

import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from leads.models import ChatMessage, Lead, LeadConversationLog

_OUTBOUND_MERGE_WINDOW = timedelta(minutes=15)

_CLIENT_LOG_RE = re.compile(r"^\[WhatsApp · client\]\s*(.*)$", re.DOTALL)
_AGENT_LOG_RE = re.compile(r"^\[WhatsApp · agent\]\s*(.*)$", re.DOTALL)
_WA_ID_PREFIX = "wa-id:"


def _meta_id_from_remarks(remarks: str) -> str:
    text = (remarks or "").strip()
    if text.startswith(_WA_ID_PREFIX):
        return text.split("\n", 1)[0].replace(_WA_ID_PREFIX, "").strip()
    return ""


def _parse_client_remarks(remarks: str) -> str:
    text = (remarks or "").strip()
    if text.startswith(_WA_ID_PREFIX):
        parts = text.split("\n", 1)
        text = parts[1].strip() if len(parts) > 1 else ""
    match = _CLIENT_LOG_RE.match(text)
    return (match.group(1).strip() if match else text).strip()


def _parse_agent_remarks(remarks: str) -> str:
    text = (remarks or "").strip()
    if text.startswith(_WA_ID_PREFIX):
        parts = text.split("\n", 1)
        text = parts[1].strip() if len(parts) > 1 else ""
    match = _AGENT_LOG_RE.match(text)
    return (match.group(1).strip() if match else text).strip()


def lead_already_received_template(lead: Lead, template_name: str) -> bool:
    """True when this lead already has an outbound row for the template name."""
    from leads.whatsapp_service import normalize_outbound_template_name

    name = normalize_outbound_template_name(template_name)
    if not name:
        return False
    return ChatMessage.objects.filter(
        lead=lead,
        is_outbound=True,
        template_name=name,
    ).exists()


def outbound_message_is_template(msg: ChatMessage) -> bool:
    """True only for Meta template sends, not Business-app free-text replies."""
    name = (msg.template_name or "").strip()
    if not name:
        return False
    from leads.whatsapp_service import meta_template_preview_body

    expected = meta_template_preview_body(name).strip()
    if not expected:
        return False
    return msg.body.strip() == expected


def _outbound_merge_window_start(created_at):
    anchor = created_at or timezone.now()
    return anchor - _OUTBOUND_MERGE_WINDOW


def _pick_canonical_outbound_duplicate(a: ChatMessage, b: ChatMessage) -> tuple[ChatMessage, ChatMessage]:
    """Prefer the row with a Meta wamid, then any id, then the earliest row."""

    def score(msg: ChatMessage) -> tuple[int, float]:
        mid = (msg.meta_message_id or "").strip()
        rank = 0
        if mid.startswith("wamid."):
            rank += 4
        elif mid:
            rank += 2
        ts = msg.created_at.timestamp() if msg.created_at else 0.0
        return (rank, -ts)

    if score(a) >= score(b):
        return a, b
    return b, a


def _find_outbound_merge_candidate(
    lead: Lead,
    *,
    body: str,
    template_name: str,
    meta_message_id: str,
    created_at=None,
) -> ChatMessage | None:
    """Match API send rows (YCloud id) with later webhook rows (wamid)."""
    mid = (meta_message_id or "").strip()
    snapshot = (body or "").strip()
    tpl = (template_name or "").strip()
    if not mid or not snapshot:
        return None

    qs = ChatMessage.objects.filter(
        lead=lead,
        is_outbound=True,
        body=snapshot,
        created_at__gte=_outbound_merge_window_start(created_at),
    )
    qs = qs.filter(template_name=tpl) if tpl else qs.filter(template_name="")

    for msg in qs.order_by("-created_at", "-id"):
        existing_mid = (msg.meta_message_id or "").strip()
        if existing_mid == mid:
            return None
        if not existing_mid or existing_mid != mid:
            return msg
    return None


def _dedupe_duplicate_outbound_rows(lead: Lead) -> int:
    """Drop duplicate outbound rows created by API send + webhook ID mismatch."""
    msgs = list(
        ChatMessage.objects.filter(lead=lead, is_outbound=True).order_by("created_at", "id")
    )
    to_delete: set[int] = set()
    for i, msg in enumerate(msgs):
        if msg.pk in to_delete:
            continue
        for other in msgs[i + 1 :]:
            if other.pk in to_delete:
                continue
            if (msg.template_name or "") != (other.template_name or ""):
                continue
            if msg.body.strip() != other.body.strip():
                continue
            delta = abs((other.created_at - msg.created_at).total_seconds())
            if delta > _OUTBOUND_MERGE_WINDOW.total_seconds():
                continue
            keep, drop = _pick_canonical_outbound_duplicate(msg, other)
            to_delete.add(drop.pk)
            if keep.pk == other.pk:
                msg = keep
    if not to_delete:
        return 0
    deleted, _ = ChatMessage.objects.filter(pk__in=to_delete).delete()
    return deleted


def record_outbound_chat_message(
    lead: Lead,
    *,
    template_name: str | None = None,
    body: str | None = None,
    meta_message_id: str = "",
    created_at=None,
) -> ChatMessage:
    from leads.whatsapp_service import (
        meta_template_preview_body,
        whatsapp_template_name,
    )

    if template_name is None:
        name = "" if body is not None else whatsapp_template_name()
    else:
        name = template_name.strip()
    if body is not None:
        snapshot = body.strip()
    elif name:
        snapshot = meta_template_preview_body(name).strip()
    else:
        snapshot = ""
    msg = ChatMessage.objects.create(
        lead=lead,
        body=snapshot,
        is_outbound=True,
        template_name=name,
        meta_message_id=(meta_message_id or "").strip(),
    )
    if created_at is not None:
        ChatMessage.objects.filter(pk=msg.pk).update(created_at=created_at)
        msg.created_at = created_at
    return msg


def upsert_outbound_chat_message(
    lead: Lead,
    *,
    body: str | None = None,
    meta_message_id: str = "",
    template_name: str = "",
    created_at=None,
) -> ChatMessage:
    """Create or refresh an outbound row (API send + YCloud webhook echoes)."""
    from leads.whatsapp_service import meta_template_preview_body

    mid = (meta_message_id or "").strip()
    tpl = (template_name or "").strip()
    snapshot = (body or "").strip()
    if not snapshot and tpl:
        snapshot = meta_template_preview_body(tpl).strip()

    if mid:
        existing = ChatMessage.objects.filter(
            lead=lead,
            is_outbound=True,
            meta_message_id=mid,
        ).first()
        if existing is None:
            existing = _find_outbound_merge_candidate(
                lead,
                body=snapshot,
                template_name=tpl,
                meta_message_id=mid,
                created_at=created_at,
            )
        if existing is not None:
            updates: dict[str, object] = {}
            if snapshot and existing.body.strip() != snapshot:
                updates["body"] = snapshot
            if tpl:
                if existing.template_name != tpl:
                    updates["template_name"] = tpl
            elif snapshot and existing.template_name:
                updates["template_name"] = ""
            if (existing.meta_message_id or "").strip() != mid:
                updates["meta_message_id"] = mid
            if updates:
                ChatMessage.objects.filter(pk=existing.pk).update(**updates)
                for field, value in updates.items():
                    setattr(existing, field, value)
            if created_at is not None:
                ChatMessage.objects.filter(pk=existing.pk).update(created_at=created_at)
                existing.created_at = created_at
            return existing

    return record_outbound_chat_message(
        lead,
        template_name=tpl,
        body=snapshot or None,
        meta_message_id=mid,
        created_at=created_at,
    )


def record_inbound_chat_message(
    lead: Lead,
    *,
    body: str,
    meta_message_id: str = "",
    created_at=None,
) -> ChatMessage:
    msg = ChatMessage.objects.create(
        lead=lead,
        body=(body or "").strip(),
        is_outbound=False,
        meta_message_id=(meta_message_id or "").strip(),
    )
    if created_at is not None:
        ChatMessage.objects.filter(pk=msg.pk).update(created_at=created_at)
        msg.created_at = created_at
    return msg


def inbound_chat_message_exists(lead: Lead, meta_message_id: str) -> bool:
    mid = (meta_message_id or "").strip()
    if not mid:
        return False
    return ChatMessage.objects.filter(lead=lead, meta_message_id=mid).exists()


def outbound_chat_message_exists(lead: Lead, meta_message_id: str) -> bool:
    mid = (meta_message_id or "").strip()
    if not mid:
        return False
    return ChatMessage.objects.filter(
        lead=lead, is_outbound=True, meta_message_id=mid
    ).exists()


def _inbound_body_exists(lead: Lead, body: str, *, created_at) -> bool:
    if not body:
        return True
    return ChatMessage.objects.filter(
        lead=lead,
        is_outbound=False,
        body=body,
        created_at=created_at,
    ).exists()


def _repair_outbound_template_rows(lead: Lead) -> int:
    """Clear mis-tagged template labels on free-text Business app / agent replies."""
    repaired = 0
    for msg in ChatMessage.objects.filter(lead=lead, is_outbound=True):
        if outbound_message_is_template(msg):
            continue
        if (msg.template_name or "").strip():
            ChatMessage.objects.filter(pk=msg.pk).update(template_name="")
            repaired += 1
    return repaired


@transaction.atomic
def sync_chat_messages_from_logs(lead: Lead) -> None:
    """Import missing rows from ``LeadConversationLog`` and refresh outbound copy."""
    from leads.whatsapp_service import (
        OFFICIAL_API_MARKER,
        meta_template_preview_body,
        whatsapp_template_name,
    )

    default_template = whatsapp_template_name()

    for log in LeadConversationLog.objects.filter(lead=lead).order_by("created_at", "id"):
        remarks = (log.remarks or "").strip()
        if not remarks:
            continue

        if OFFICIAL_API_MARKER in remarks:
            # mark_sent and YCloud webhooks already persist template rows — do not
            # rewrite the first outbound message on every drawer open.
            if ChatMessage.objects.filter(lead=lead, is_outbound=True).exists():
                continue
            tpl = default_template
            preview = meta_template_preview_body(tpl)
            msg = record_outbound_chat_message(
                lead,
                template_name=tpl,
                body=preview,
                created_at=log.created_at,
            )
            ChatMessage.objects.filter(pk=msg.pk).update(created_at=log.created_at)
            continue

        if "[WhatsApp · client]" in remarks:
            mid = _meta_id_from_remarks(remarks)
            body = _parse_client_remarks(remarks)
            if not body:
                continue
            if mid and inbound_chat_message_exists(lead, mid):
                continue
            if not mid and _inbound_body_exists(lead, body, created_at=log.created_at):
                continue
            msg = record_inbound_chat_message(
                lead,
                body=body,
                meta_message_id=mid,
                created_at=log.created_at,
            )
            ChatMessage.objects.filter(pk=msg.pk).update(created_at=log.created_at)
            continue

        if "[WhatsApp · agent]" in remarks:
            mid = _meta_id_from_remarks(remarks)
            body = _parse_agent_remarks(remarks)
            if not body:
                continue
            if mid and outbound_chat_message_exists(lead, mid):
                continue
            if not mid and ChatMessage.objects.filter(
                lead=lead,
                is_outbound=True,
                body=body,
            ).exists():
                continue
            msg = upsert_outbound_chat_message(
                lead,
                body=body,
                meta_message_id=mid,
                template_name="",
                created_at=log.created_at,
            )
            ChatMessage.objects.filter(pk=msg.pk).update(created_at=log.created_at)


def chat_messages_for_lead(lead: Lead) -> list[ChatMessage]:
    sync_chat_messages_from_logs(lead)
    _dedupe_duplicate_outbound_rows(lead)
    _repair_outbound_template_rows(lead)
    return list(
        ChatMessage.objects.filter(lead=lead).order_by("created_at", "id")
    )


@transaction.atomic
def refresh_chat_messages_for_lead(lead: Lead) -> dict[str, int]:
    """Re-import WhatsApp conversation logs and relabel free-text outbound as You."""
    before = ChatMessage.objects.filter(lead=lead).count()
    sync_chat_messages_from_logs(lead)
    after_sync = ChatMessage.objects.filter(lead=lead).count()
    deduped = _dedupe_duplicate_outbound_rows(lead)
    repaired = _repair_outbound_template_rows(lead)
    return {
        "added": max(0, after_sync - before),
        "deduped": deduped,
        "repaired": repaired,
        "total": ChatMessage.objects.filter(lead=lead).count(),
    }


# Backwards-compatible alias
backfill_chat_messages_for_lead = sync_chat_messages_from_logs
