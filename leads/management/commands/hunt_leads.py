from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from leads.services import (
    create_search_query_record,
    fetch_leads,
    normalize_hunt_provider,
    record_search_query_outcome,
)


class Command(BaseCommand):
    help = "Hunt business leads via Serper or Outscraper Maps."

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
            help="Maps query fragment (optional; defaults to --shop-keyword when empty).",
        )
        parser.add_argument(
            "--country",
            type=str,
            default="",
            help="Optional country appended after the city in the Maps query (disambiguation).",
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
            help="Max Maps places to request per hunt (default: 20, max: 100).",
        )
        parser.add_argument(
            "--provider",
            type=str,
            default="serper",
            help="Maps provider: serper or outscraper (default: serper).",
        )
        parser.add_argument(
            "--require-website",
            action="store_true",
            help="Only import listings that have a website or social URL (skip Maps-only links).",
        )
        parser.add_argument(
            "--exclude-keyword",
            action="append",
            dest="exclude_keywords",
            default=[],
            help="Skip listings whose name/address contains this term (repeatable). Applied locally after import.",
        )

    def handle(self, *args, **options) -> None:
        city = (options["city"] or "").strip()
        if not city:
            raise CommandError("--city is required.")

        shop_keyword = (options["shop_keyword"] or "").strip()
        if not shop_keyword:
            raise CommandError("--shop-keyword is required (non-empty).")

        try:
            provider = normalize_hunt_provider(options.get("provider"))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        query = (options["query"] or "").strip()
        country = (options["country"] or "").strip()
        limit = max(1, min(int(options["limit"] or 100), 100))
        require_website = bool(options["require_website"])

        self.stdout.write(
            f'Hunting {provider} Maps (keyword={shop_keyword!r}) for "{query or shop_keyword}" in "{city}" (limit={limit})…'
        )
        rec = create_search_query_record(
            keyword=shop_keyword,
            maps_query=query,
            city=city,
            country=country,
            provider=provider,
            exclude_keywords=options.get("exclude_keywords"),
        )
        result = fetch_leads(
            city,
            query,
            provider=provider,
            num=limit,
            shop_keyword=shop_keyword,
            country=country,
            search_query_record=rec,
            require_website=require_website,
            exclude_keywords=options.get("exclude_keywords"),
        )
        record_search_query_outcome(
            rec,
            created=result.created,
            exclude_keywords=options.get("exclude_keywords"),
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
                    f"; no website/social skipped: {result.skipped_no_website}"
                    if result.skipped_no_website
                    else ""
                )
                + (
                    f"; excluded keyword skipped: {result.skipped_excluded}"
                    if result.skipped_excluded
                    else ""
                )
                + "."
            )
        )

        self.stdout.write(self.style.SUCCESS("Done."))
