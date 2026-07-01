"""Persist and load Meta WhatsApp chat rows for the lead inbox drawer."""

from __future__ import annotations

import re

from django.db import transaction

from leads.models import ChatMessage, Lead, LeadConversationLog

_CLIENT_LOG_RE = re.compile(r"^\[WhatsApp · client\]\s*(.*)$", re.DOTALL)
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
        name = whatsapp_template_name()
    else:
        name = template_name.strip()
    if body is not None:
        snapshot = body.strip()
    else:
        snapshot = meta_template_preview_body(name or whatsapp_template_name()).strip()
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
        if existing is not None:
            updates: dict[str, object] = {}
            if snapshot and existing.body.strip() != snapshot:
                updates["body"] = snapshot
            if tpl and existing.template_name != tpl:
                updates["template_name"] = tpl
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
        template_name=tpl or None,
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


def _repair_outbound_template_rows(lead: Lead) -> None:
    """Align stored outbound copy with synced Meta template catalog."""
    from leads.whatsapp_service import meta_template_preview_body

    for msg in ChatMessage.objects.filter(lead=lead, is_outbound=True):
        name = (msg.template_name or "").strip()
        if not name:
            continue
        expected = meta_template_preview_body(name).strip()
        if expected and msg.body.strip() != expected:
            ChatMessage.objects.filter(pk=msg.pk).update(body=expected)


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
            outbound = (
                ChatMessage.objects.filter(lead=lead, is_outbound=True)
                .order_by("created_at", "id")
                .first()
            )
            tpl = (outbound.template_name if outbound else "") or default_template
            preview = meta_template_preview_body(tpl)
            if outbound is None:
                msg = record_outbound_chat_message(
                    lead,
                    template_name=tpl,
                    body=preview,
                    created_at=log.created_at,
                )
                ChatMessage.objects.filter(pk=msg.pk).update(created_at=log.created_at)
            else:
                updates: dict[str, object] = {}
                if preview and outbound.body.strip() != preview.strip():
                    updates["body"] = preview
                if tpl and not outbound.template_name:
                    updates["template_name"] = tpl
                if updates:
                    ChatMessage.objects.filter(pk=outbound.pk).update(**updates)
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


def chat_messages_for_lead(lead: Lead) -> list[ChatMessage]:
    sync_chat_messages_from_logs(lead)
    _repair_outbound_template_rows(lead)
    return list(
        ChatMessage.objects.filter(lead=lead).order_by("created_at", "id")
    )


# Backwards-compatible alias
backfill_chat_messages_for_lead = sync_chat_messages_from_logs
