"""YCloud + legacy Meta WhatsApp webhook parsing and chat sync."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any, Optional

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime

from leads.chat_messages import (
    inbound_chat_message_exists,
    outbound_chat_message_exists,
    record_inbound_chat_message,
    record_outbound_chat_message,
)
from leads.display import normalize_manual_phone
from leads.models import Lead, LeadConversationLog
from leads.pipeline import (
    TRASH_GROUP_NAME,
    find_lead_by_phone,
)
from leads.ycloud_service import whatsapp_from_number, ycloud_webhook_secret

logger = logging.getLogger(__name__)

WEBHOOK_MSG_ID_PREFIX = "wa-id:"


@dataclass(frozen=True)
class ParsedWebhookMessage:
    remote_phone: str
    text_body: str
    from_me: bool
    message_id: str
    timestamp: datetime


def _is_trusted_webhook_source(ip: str) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def _webhook_remote_addr(request: HttpRequest) -> str:
    return (request.META.get("REMOTE_ADDR") or "").strip()


def _meta_app_secret() -> str:
    return (getattr(settings, "WHATSAPP_APP_SECRET", None) or "").strip()


def _meta_webhook_verify_token() -> str:
    return (getattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", None) or "").strip()


def verify_ycloud_webhook_signature(request: HttpRequest, raw_body: bytes) -> bool:
    """Validate ``YCloud-Signature: t={ts},s={hex}`` using ``YCLOUD_WEBHOOK_SECRET``."""
    secret = ycloud_webhook_secret()
    if not secret:
        remote = _webhook_remote_addr(request)
        if _is_trusted_webhook_source(remote):
            return True
        logger.warning(
            "YCLOUD_WEBHOOK_SECRET unset; rejected unsigned webhook from %s.",
            remote,
        )
        return False

    header = (request.headers.get("YCloud-Signature") or "").strip()
    if not header:
        return False

    timestamp = ""
    signature = ""
    for part in header.split(","):
        part = part.strip()
        if part.startswith("t="):
            timestamp = part[2:].strip()
        elif part.startswith("s="):
            signature = part[2:].strip()
    if not timestamp or not signature:
        return False

    try:
        body_text = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return False

    signed_payload = f"{timestamp}.{body_text}"
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def verify_meta_webhook_signature(request: HttpRequest, raw_body: bytes) -> bool:
    """Validate legacy Meta ``X-Hub-Signature-256`` (optional fallback)."""
    app_secret = _meta_app_secret()
    if not app_secret:
        remote = _webhook_remote_addr(request)
        if _is_trusted_webhook_source(remote):
            return True
        if getattr(settings, "DEBUG", False):
            return True
        return False

    header = (request.headers.get("X-Hub-Signature-256") or "").strip()
    if not header.startswith("sha256="):
        return False
    digest = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(header[7:], digest)


def webhook_request_authenticated(request: HttpRequest, raw_body: bytes) -> bool:
    """YCloud signature first; fall back to legacy Meta verification."""
    if verify_ycloud_webhook_signature(request, raw_body):
        return True
    return verify_meta_webhook_signature(request, raw_body)


def handle_meta_webhook_verify(request: HttpRequest) -> HttpResponse:
    """Legacy Meta GET handshake; also accepts plain GET for tunnel health checks."""
    mode = (request.GET.get("hub.mode") or "").strip()
    token = (request.GET.get("hub.verify_token") or "").strip()
    challenge = (request.GET.get("hub.challenge") or "").strip()
    expected = _meta_webhook_verify_token()

    if mode == "subscribe" and expected and token == expected and challenge:
        return HttpResponse(challenge, content_type="text/plain")
    if request.method == "GET" and not mode:
        return HttpResponse("ok", content_type="text/plain")
    return HttpResponse("Forbidden", status=403)


def _iso_timestamp(raw_ts: Any) -> datetime:
    if isinstance(raw_ts, str) and raw_ts.strip():
        parsed = parse_datetime(raw_ts.strip())
        if parsed is not None:
            if dj_timezone.is_naive(parsed):
                parsed = dj_timezone.make_aware(parsed, dt_timezone.utc)
            return dj_timezone.localtime(parsed)
    return dj_timezone.now()


def _meta_timestamp(raw_ts: Any) -> datetime:
    if raw_ts is not None:
        try:
            ts = int(str(raw_ts).strip())
            if ts > 0:
                aware = datetime.fromtimestamp(ts, tz=dt_timezone.utc)
                return dj_timezone.localtime(aware)
        except (TypeError, ValueError, OSError):
            pass
    return dj_timezone.now()


def _extract_text(message: dict[str, Any]) -> str:
    msg_type = (message.get("type") or "").strip().lower()
    if msg_type == "text":
        text = message.get("text")
        if isinstance(text, dict):
            body = text.get("body")
            if isinstance(body, str) and body.strip():
                return body.strip()
    if msg_type == "button":
        button = message.get("button")
        if isinstance(button, dict):
            text = button.get("text") or button.get("payload")
            if isinstance(text, str) and text.strip():
                return text.strip()
    if msg_type == "interactive":
        interactive = message.get("interactive")
        if isinstance(interactive, dict):
            reply = interactive.get("button_reply") or interactive.get("list_reply")
            if isinstance(reply, dict):
                title = reply.get("title") or reply.get("id")
                if isinstance(title, str) and title.strip():
                    return title.strip()
    return ""


def _extract_text_or_placeholder(message: dict[str, Any]) -> str:
    body = _extract_text(message)
    if body:
        return body
    msg_type = (message.get("type") or "").strip().lower()
    if msg_type in ("revoke", "edit"):
        return ""
    if msg_type in (
        "image",
        "video",
        "audio",
        "document",
        "sticker",
        "location",
        "contacts",
        "reaction",
    ):
        return f"[{msg_type}]"
    return ""


def _message_id(message: dict[str, Any]) -> str:
    return str(message.get("wamid") or message.get("id") or "").strip()


def _phones_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return normalize_manual_phone(a) == normalize_manual_phone(b)


def _parse_ycloud_inbound(inbound: dict[str, Any]) -> list[ParsedWebhookMessage]:
    raw_from = (inbound.get("from") or "").strip()
    remote_phone = normalize_manual_phone(raw_from)
    if not remote_phone:
        return []
    text_body = _extract_text_or_placeholder(inbound)
    if not text_body:
        return []
    return [
        ParsedWebhookMessage(
            remote_phone=remote_phone,
            text_body=text_body,
            from_me=False,
            message_id=_message_id(inbound),
            timestamp=_iso_timestamp(inbound.get("sendTime") or inbound.get("createTime")),
        )
    ]


def _parse_ycloud_outbound_update(message: dict[str, Any]) -> list[ParsedWebhookMessage]:
    """Mobile-app / API outbound echoes via ``whatsapp.message.updated``."""
    status = (message.get("status") or "").strip().lower()
    if status and status not in {"sent"}:
        return []

    business = whatsapp_from_number()
    msg_from = (message.get("from") or "").strip()
    msg_to = (message.get("to") or "").strip()
    if not business or not _phones_match(msg_from, business):
        return []

    remote_phone = normalize_manual_phone(msg_to)
    if not remote_phone:
        return []
    text_body = _extract_text_or_placeholder(message)
    if not text_body:
        return []

    return [
        ParsedWebhookMessage(
            remote_phone=remote_phone,
            text_body=text_body,
            from_me=True,
            message_id=_message_id(message),
            timestamp=_iso_timestamp(
                message.get("sendTime") or message.get("createTime") or message.get("updateTime")
            ),
        )
    ]


def parse_ycloud_webhook(payload: dict[str, Any]) -> list[ParsedWebhookMessage]:
    """Normalize YCloud webhook events into chat rows."""
    event_type = (payload.get("type") or "").strip()
    if event_type == "whatsapp.inbound_message.received":
        inbound = payload.get("whatsappInboundMessage")
        if isinstance(inbound, dict):
            return _parse_ycloud_inbound(inbound)
        return []

    if event_type == "whatsapp.message.updated":
        message = payload.get("whatsappMessage")
        if isinstance(message, dict):
            return _parse_ycloud_outbound_update(message)
        return []

    return []


def _parse_message_list(
    messages: list[Any],
    *,
    phone_field: str,
    from_me: bool,
) -> list[ParsedWebhookMessage]:
    parsed: list[ParsedWebhookMessage] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        raw_phone = (message.get(phone_field) or "").strip()
        if not raw_phone:
            continue
        remote_phone = normalize_manual_phone(raw_phone)
        if not remote_phone:
            continue
        text_body = _extract_text_or_placeholder(message)
        if not text_body:
            continue
        message_id = str(message.get("id") or "").strip()
        timestamp = _meta_timestamp(message.get("timestamp"))
        parsed.append(
            ParsedWebhookMessage(
                remote_phone=remote_phone,
                text_body=text_body,
                from_me=from_me,
                message_id=message_id,
                timestamp=timestamp,
            )
        )
    return parsed


def parse_meta_cloud_webhook(payload: dict[str, Any]) -> list[ParsedWebhookMessage]:
    """Legacy Meta Cloud API envelope (optional fallback)."""
    if (payload.get("object") or "").strip() != "whatsapp_business_account":
        return []

    parsed: list[ParsedWebhookMessage] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return parsed

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            field = (change.get("field") or "").strip()
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            if field == "messages":
                messages = value.get("messages")
                if isinstance(messages, list):
                    parsed.extend(
                        _parse_message_list(messages, phone_field="from", from_me=False)
                    )
            elif field == "smb_message_echoes":
                echoes = value.get("message_echoes")
                if isinstance(echoes, list):
                    parsed.extend(
                        _parse_message_list(echoes, phone_field="to", from_me=True)
                    )
    return parsed


def parse_whatsapp_webhook(payload: dict[str, Any]) -> list[ParsedWebhookMessage]:
    """Dispatch to YCloud or legacy Meta parser based on payload shape."""
    if (payload.get("type") or "").startswith("whatsapp."):
        return parse_ycloud_webhook(payload)
    return parse_meta_cloud_webhook(payload)


def _format_log_remarks(sender: str, text_body: str, message_id: str) -> str:
    label = "agent" if sender == "agent" else "client"
    header = f"{WEBHOOK_MSG_ID_PREFIX}{message_id}\n" if message_id else ""
    return f"{header}[WhatsApp · {label}] {text_body}"


def _log_already_synced(lead: Lead, message_id: str) -> bool:
    if not message_id:
        return False
    prefix = f"{WEBHOOK_MSG_ID_PREFIX}{message_id}\n"
    return LeadConversationLog.objects.filter(lead=lead, remarks__startswith=prefix).exists()


@transaction.atomic
def sync_webhook_message(msg: ParsedWebhookMessage) -> bool:
    lead = find_lead_by_phone(msg.remote_phone)
    if lead is None:
        return False

    if lead.group and lead.group.name == TRASH_GROUP_NAME:
        return False

    if _log_already_synced(lead, msg.message_id):
        return False

    if msg.from_me:
        if not outbound_chat_message_exists(lead, msg.message_id):
            record_outbound_chat_message(
                lead,
                body=msg.text_body,
                meta_message_id=msg.message_id,
                template_name="",
            )
    elif not inbound_chat_message_exists(lead, msg.message_id):
        record_inbound_chat_message(
            lead,
            body=msg.text_body,
            meta_message_id=msg.message_id,
            created_at=msg.timestamp,
        )

    sender = "agent" if msg.from_me else "client"
    remarks = _format_log_remarks(sender, msg.text_body, msg.message_id)
    log = LeadConversationLog(
        lead=lead,
        conversation_date=msg.timestamp.date(),
        remarks=remarks,
    )
    log.save()
    if msg.timestamp:
        LeadConversationLog.objects.filter(pk=log.pk).update(created_at=msg.timestamp)

    return True


def decode_webhook_body(request: HttpRequest) -> tuple[dict[str, Any], Optional[str]]:
    raw = request.body
    if not raw:
        return {}, None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, "Invalid JSON body."
    if not isinstance(payload, dict):
        return {}, "Webhook body must be a JSON object."
    return payload, None


def process_whatsapp_webhook(request: HttpRequest) -> tuple[dict[str, Any], int]:
    """Handle one YCloud (or legacy Meta) webhook POST."""
    raw_body = request.body or b""
    if not webhook_request_authenticated(request, raw_body):
        return {"status": "error", "detail": "Unauthorized."}, 403

    payload, decode_error = decode_webhook_body(request)
    if decode_error:
        return {"status": "error", "detail": decode_error}, 400

    messages = parse_whatsapp_webhook(payload)
    if not messages:
        return {"status": "success", "synced": 0}, 200

    synced = 0
    for msg in messages:
        try:
            if sync_webhook_message(msg):
                synced += 1
        except Exception:
            logger.exception(
                "Failed to sync WhatsApp webhook message for %s",
                msg.remote_phone,
            )
    return {"status": "success", "synced": synced}, 200
