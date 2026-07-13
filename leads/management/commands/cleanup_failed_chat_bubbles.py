from __future__ import annotations

from django.core.management.base import BaseCommand

from leads.chat_messages import (
    DELIVERY_FAILED_MARKER,
    FAILED_DELIVERY_STATUS,
    _FAILED_LOG_ID_RE,
    _FAILED_LOG_TEMPLATE_RE,
    mark_outbound_delivery_failed,
)
from leads.models import ChatMessage, Lead, LeadConversationLog


class Command(BaseCommand):
    help = (
        "Hide outbound chat bubbles for WhatsApp sends that failed delivery. "
        "Correlates existing '[WhatsApp delivery failed]' logs to outbound "
        "ChatMessage rows (by message id, then by time window) and flags them so "
        "they no longer appear in the Active Chat feed. Safe to re-run."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many bubbles would be flagged without saving changes.",
        )

    def handle(self, *args, **options) -> None:
        dry_run = bool(options.get("dry_run"))
        lead_ids = (
            LeadConversationLog.objects.filter(remarks__contains=DELIVERY_FAILED_MARKER)
            .values_list("lead_id", flat=True)
            .distinct()
        )

        total_flagged = 0
        for lead in Lead.objects.filter(pk__in=list(lead_ids)):
            logs = LeadConversationLog.objects.filter(
                lead=lead, remarks__contains=DELIVERY_FAILED_MARKER
            ).order_by("created_at", "id")
            for log in logs:
                remarks = (log.remarks or "").strip()
                id_match = _FAILED_LOG_ID_RE.search(remarks)
                message_id = id_match.group(1).strip() if id_match else ""
                tpl_match = _FAILED_LOG_TEMPLATE_RE.match(remarks)
                template_name = tpl_match.group(1).strip() if tpl_match else ""
                if dry_run:
                    total_flagged += self._would_flag(
                        lead, message_id=message_id, template_name=template_name,
                        failed_at=log.created_at,
                    )
                    continue
                total_flagged += mark_outbound_delivery_failed(
                    lead,
                    message_id=message_id,
                    template_name=template_name,
                    failed_at=log.created_at,
                )

        prefix = "[dry-run] would flag" if dry_run else "Flagged"
        self.stdout.write(
            self.style.SUCCESS(f"{prefix} {total_flagged} failed outbound chat bubble(s).")
        )

    def _would_flag(self, lead, *, message_id, template_name, failed_at) -> int:
        from django.db.models import Q

        mid = (message_id or "").strip()
        if mid:
            matched = ChatMessage.objects.filter(lead=lead, is_outbound=True).filter(
                Q(meta_message_id=mid) | Q(meta_message_id__startswith=mid)
            )
            pending = matched.exclude(delivery_status=FAILED_DELIVERY_STATUS).count()
            if matched.exists():
                return pending
        anchor = failed_at
        qs = ChatMessage.objects.filter(
            lead=lead,
            is_outbound=True,
            created_at__lte=anchor,
        ).exclude(delivery_status=FAILED_DELIVERY_STATUS)
        tpl = (template_name or "").strip()
        qs = qs.filter(template_name=tpl) if tpl else qs.filter(template_name="")
        return 1 if qs.exists() else 0
