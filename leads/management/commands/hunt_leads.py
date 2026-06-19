from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from leads.models import SearchQueryRecord
from leads.services import fetch_leads_from_serper


class Command(BaseCommand):
    help = "Hunt business leads via Serper Maps."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--city",
            type=str,
            required=True,
            help='Target city or area, e.g. "Kuala Lumpur"',
        )
        parser.add_argument(
            "--query",
            type=str,
            default="",
            help="Serper Maps query fragment (optional; defaults to --shop-keyword when empty).",
        )
        parser.add_argument(
            "--country",
            type=str,
            default="",
            help="Optional country appended after the city in the Serper query (disambiguation).",
        )
        parser.add_argument(
            "--shop-keyword",
            type=str,
            default="",
            dest="shop_keyword",
            help='Hunt keyword stored on leads and default Maps fragment when --query is empty (e.g. "medical clinic").',
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Max Serper Maps places to request per hunt (default: 20, max: 100).",
        )
        parser.add_argument(
            "--require-website",
            action="store_true",
            help="Only import listings that have a website or social URL in Serper (skip Maps-only links).",
        )

    def handle(self, *args, **options) -> None:
        city = (options["city"] or "").strip()
        if not city:
            raise CommandError("--city is required.")

        shop_keyword = (options["shop_keyword"] or "").strip()
        if not shop_keyword:
            raise CommandError("--shop-keyword is required (non-empty).")

        query = (options["query"] or "").strip()
        country = (options["country"] or "").strip()
        limit = max(1, min(int(options["limit"] or 20), 100))
        require_website = bool(options["require_website"])

        self.stdout.write(
            f'Hunting Serper Maps (keyword={shop_keyword!r}) for "{query or shop_keyword}" in "{city}" (limit={limit})…'
        )
        rec = SearchQueryRecord.objects.create(
            keyword=shop_keyword[:160],
            maps_search_query=(query or shop_keyword)[:255],
            search_city=city[:255],
            search_country=country[:255],
        )
        result = fetch_leads_from_serper(
            city,
            query,
            num=limit,
            shop_keyword=shop_keyword,
            country=country,
            search_query_record=rec,
            require_website=require_website,
        )
        if result.errors:
            for err in result.errors:
                self.stderr.write(self.style.WARNING(err))
        self.stdout.write(
            self.style.NOTICE(
                f"Places seen: {result.places_seen}; "
                f"created: {result.created}; existing skipped: {result.skipped_existing}"
                + (
                    f"; duplicate phone skipped: {result.skipped_duplicate_phone}"
                    if result.skipped_duplicate_phone
                    else ""
                )
                + (
                    f"; no website/social skipped: {result.skipped_no_website}."
                    if getattr(result, "skipped_no_website", 0)
                    else "."
                )
            )
        )

        self.stdout.write(self.style.SUCCESS("Done."))
