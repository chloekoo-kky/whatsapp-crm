from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from leads.whatsapp_service import (
    dispatch_pending_batch,
    resolve_meta_dispatch_credentials,
    run_due_scheduled_batches,
)


class Command(BaseCommand):
    help = (
        "One-shot WhatsApp batch sender for cron (e.g. Railway). Runs every due "
        "scheduled batch and sends the configured Meta template to the oldest "
        "PENDING leads, then exits. Use --leads to dispatch an ad-hoc batch now."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--leads",
            type=int,
            default=None,
            help=(
                "Ad-hoc mode: immediately send to this many oldest PENDING leads "
                "instead of (or in addition to) processing scheduled batches."
            ),
        )

    def handle(self, *args, **options) -> None:
        token, phone_id = resolve_meta_dispatch_credentials()
        if not token:
            raise CommandError("YCLOUD_API_KEY is not configured.")
        if not phone_id:
            raise CommandError("WHATSAPP_FROM_NUMBER is not configured.")

        ad_hoc = options.get("leads")
        if ad_hoc is not None:
            if ad_hoc <= 0:
                raise CommandError("--leads must be a positive integer.")
            sent = dispatch_pending_batch(ad_hoc)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Ad-hoc batch: dispatched {sent}/{ad_hoc} pending lead(s)."
                )
            )
            return

        summary = run_due_scheduled_batches()
        if summary["batches_run"] == 0:
            self.stdout.write("No scheduled batches are due.")
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Ran {summary['batches_run']} scheduled batch(es); "
                f"dispatched {summary['leads_sent']} lead(s)."
            )
        )
