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
) -> ChatMessage:
    from leads.whatsapp_service import (
        build_message_body,
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
        snapshot = (
            build_message_body(lead) or meta_template_preview_body(name or whatsapp_template_name())
        ).strip()
    return ChatMessage.objects.create(
        lead=lead,
        body=snapshot,
        is_outbound=True,
        template_name=name,
        meta_message_id=(meta_message_id or "").strip(),
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


@transaction.atomic
def sync_chat_messages_from_logs(lead: Lead) -> None:
    """Import missing rows from ``LeadConversationLog`` and refresh stub outbound copy."""
    from leads.whatsapp_service import (
        OFFICIAL_API_MARKER,
        build_message_body,
        meta_template_preview_body,
        whatsapp_template_name,
    )

    template_name = whatsapp_template_name()
    rich_body = build_message_body(lead)
    preview_stub = meta_template_preview_body(template_name)

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
            if outbound is None:
                msg = record_outbound_chat_message(
                    lead,
                    template_name=template_name,
                    body=rich_body,
                )
                ChatMessage.objects.filter(pk=msg.pk).update(created_at=log.created_at)
            elif rich_body and outbound.body in {preview_stub, "Hello"} and outbound.body != rich_body:
                outbound.body = rich_body
                outbound.template_name = template_name
                outbound.save(update_fields=["body", "template_name"])
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
    return list(
        ChatMessage.objects.filter(lead=lead).order_by("created_at", "id")
    )


# Backwards-compatible alias
backfill_chat_messages_for_lead = sync_chat_messages_from_logs
