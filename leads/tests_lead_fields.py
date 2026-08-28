"""Grid card and list row share field partials and keep view-specific wrappers."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from leads.models import Lead, Tag, WhatsAppBatchSchedule
from leads.pipeline import get_or_create_uncategorized_group
from leads.views import _annotate_lead_dashboard_qs, _dashboard_prepare_clinics


class LeadFieldPartialTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "fields_admin", "fields@t.test", "pass"
        )
        self.group = get_or_create_uncategorized_group()
        self.lead = Lead.objects.create(
            name="Shared Fields Clinic",
            address="12 Test Road, Petaling Jaya",
            website="https://fields.example",
            group=self.group,
            phone_number="+60123456789",
            phone_numbers=["+60123456789", "+60129876543"],
            is_chain=True,
            is_very_important=True,
            shop_keyword="dentist",
            search_state="Selangor",
            search_city="PJ",
            search_query="dentist near me",
            location_count_estimate=4,
        )
        pending = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=2),
            status=WhatsAppBatchSchedule.Status.PENDING,
        )
        done = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() - timedelta(days=1),
            status=WhatsAppBatchSchedule.Status.COMPLETED,
        )
        self.lead.whatsapp_batches.add(pending, done)
        dental = Tag.objects.get(slug="dental")
        gp = Tag.objects.get(slug="gp")
        self.lead.tags.add(dental, gp)
        self.request = RequestFactory().get("/")
        self.request.user = self.user
        qs = _annotate_lead_dashboard_qs(Lead.objects.filter(pk=self.lead.pk))
        clinics, brands = _dashboard_prepare_clinics(qs, request=self.request)
        self.clinic = clinics[0]
        self.ctx = {
            "c": self.clinic,
            "request": self.request,
            "multi_location_brands": brands,
            "show_folder_badge": False,
            "is_trash_view": False,
            "is_uncategorized_view": True,
            "is_whatsapp_chats_view": False,
            "is_queue_view": False,
            "current_group_id": "uncategorized",
            "force_send_template_name": "",
        }

    def _card(self):
        return render_to_string(
            "leads/partials/_lead_grid_card.html", self.ctx, request=self.request
        )

    def _row(self):
        return render_to_string(
            "leads/partials/_lead_table_row.html", self.ctx, request=self.request
        )

    def test_wrappers_stay_view_specific(self):
        card = self._card()
        row = self._row()
        self.assertIn("<article", card)
        self.assertIn("clinic-card", card)
        self.assertNotIn("<tr", card)
        self.assertIn("<tr", row)
        self.assertIn("clinic-row", row)
        self.assertNotIn("<article", row)
        self.assertNotIn("clinic-card", row)

    def test_shared_field_content_matches_in_both_views(self):
        card = self._card()
        row = self._row()
        shared = [
            "Shared Fields Clinic",
            "12 Test Road, Petaling Jaya",
            "+60123456789",
            "+60129876543",
            "https://fields.example",
            "Selangor",
            "dentist near me",
            "address-copy-trigger",
            "clinic-phone-inner",
            "wa-me-open-btn",
            "clinic-source-line",
            "clinic-branches-line",
            "clinic-created-line",
            "clinic-batch-lines",
            "Batch ·",
            "Sent ·",
            "~4 branches",
            "lead-tag-chip",
            'data-tag-slug="gp"',
            'data-tags="',
        ]
        for needle in shared:
            with self.subTest(needle=needle):
                self.assertIn(needle, card)
                self.assertIn(needle, row)
        self.assertNotIn('data-tag-slug="dental"', card)
        self.assertNotIn('data-tag-slug="dental"', row)
        self.assertIn("lead-vip-star-btn", card)
        self.assertNotIn("lead-vip-star-btn", row)

    def test_layout_class_differences_are_preserved(self):
        card = self._card()
        row = self._row()
        self.assertIn("line-clamp-3", card)
        self.assertIn("clinic-address-cell", card)
        self.assertIn("-ml-1", card)
        self.assertIn("line-clamp-4", row)
        self.assertNotIn("clinic-address-cell", row)
        self.assertIn("clinic-phone-slot", card)
        self.assertIn("clinic-phone-cell-contents", row)
        self.assertIn("tabular-nums", row)
        self.assertNotIn("tabular-nums", card)

    def test_dashboard_renders_both_views_with_shared_fields(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("clinic-card", html)
        self.assertIn("clinic-row--selectable", html)
        self.assertIn("address-copy-trigger", html)
        self.assertIn("Shared Fields Clinic", html)
        self.assertIn("+60123456789", html)
        self.assertIn("clinic-created-line", html)
        self.assertIn("clinic-batch-lines", html)
        self.assertGreaterEqual(html.count("address-copy-trigger"), 2)
        self.assertGreaterEqual(html.count("clinic-phone-inner"), 2)

    def test_folder_badge_renders_in_both_views_when_enabled(self):
        from leads.views import _attach_global_search_lead_context

        _attach_global_search_lead_context(self.clinic)
        self.ctx["show_folder_badge"] = True
        card = self._card()
        row = self._row()
        self.assertIn("lead-folder-badge", card)
        self.assertIn("lead-folder-badge", row)
        self.assertIn("Uncategorized", card)
        self.assertIn("Uncategorized", row)

    def test_leads_table_ajax_keeps_grid_and_list_fields(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("get_leads_table"), {"group_id": "uncategorized"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Shared Fields Clinic", payload["tbody_html"])
        self.assertIn("Shared Fields Clinic", payload["grid_html"])
        self.assertIn("address-copy-trigger", payload["tbody_html"])
        self.assertIn("address-copy-trigger", payload["grid_html"])
        self.assertIn("clinic-card", payload["grid_html"])
        self.assertIn("<tr", payload["tbody_html"])
        self.assertIn("clinic-created-line", payload["tbody_html"])
        self.assertIn("clinic-created-line", payload["grid_html"])
        self.assertIn('data-tags="', payload["tbody_html"])
        self.assertIn('data-tags="', payload["grid_html"])
        self.assertIn("lead-tag-chip", payload["tbody_html"])
        self.assertIn("lead-tag-chip", payload["grid_html"])
        self.assertIn("dental", payload["tbody_html"])
        self.assertIn("dental", payload["grid_html"])


def _prefetch_names(qs):
    names = []
    for lookup in qs._prefetch_related_lookups:
        names.append(lookup.prefetch_to if hasattr(lookup, "prefetch_to") else str(lookup))
    return names


class DashboardTagFilterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "tagfilter_admin", "tagfilter@t.test", "pass"
        )
        self.group = get_or_create_uncategorized_group()
        self.request = RequestFactory().get("/")
        self.request.user = self.user
        dental = Tag.objects.get(slug="dental")
        gp = Tag.objects.get(slug="gp")
        aesthetic = Tag.objects.get(slug="aesthetic")
        self.both = Lead.objects.create(
            name="Both Tags Clinic",
            address="1 Filter St",
            group=self.group,
        )
        self.both.tags.add(dental, gp)
        self.aes = Lead.objects.create(
            name="Aesthetic Only Clinic",
            address="2 Filter St",
            group=self.group,
        )
        self.aes.tags.add(aesthetic)
        self.none = Lead.objects.create(
            name="No Tags Clinic",
            address="3 Filter St",
            group=self.group,
        )

    def test_queryset_prefetches_tags(self):
        qs = _annotate_lead_dashboard_qs(Lead.objects.all())
        self.assertIn("tags", _prefetch_names(qs))

    def test_prefetch_avoids_n_plus_one_when_reading_tags(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        qs = _annotate_lead_dashboard_qs(
            Lead.objects.filter(pk__in=[self.both.pk, self.aes.pk, self.none.pk])
        )
        with CaptureQueriesContext(connection) as ctx:
            clinics, _ = _dashboard_prepare_clinics(qs, request=self.request)
            slugs = []
            for clinic in clinics:
                slugs.extend([tag.slug for tag in clinic.tags.all()])
        tag_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if "leads_tag" in q["sql"].lower() or "leads_lead_tags" in q["sql"].lower()
        ]
        self.assertIn("dental", slugs)
        self.assertIn("gp", slugs)
        self.assertLessEqual(len(tag_sql), 2)

    def test_filter_control_lists_live_tags(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="lead-tag-filter"', html)
        self.assertIn('id="lead-tag-filter-toggle"', html)
        self.assertIn('id="content-toolbar"', html)
        self.assertRegex(html, r'id="content-toolbar"[^>]*\bz-30\b')
        self.assertRegex(html, r'id="leads-scroll-container"[^>]*\bz-0\b')
        self.assertIn('z-[200]', html)
        self.assertIn('class="lead-tag-filter-cb', html)
        self.assertIn('value="dental"', html)
        self.assertIn('value="gp"', html)
        self.assertIn('value="aesthetic"', html)
        self.assertIn("Match any selected", html)

    def test_or_semantics_from_row_data_tags_in_both_views(self):
        qs = _annotate_lead_dashboard_qs(
            Lead.objects.filter(pk__in=[self.both.pk, self.aes.pk, self.none.pk])
        )
        clinics, brands = _dashboard_prepare_clinics(qs, request=self.request)
        by_name = {c.name: c for c in clinics}

        def tags_of(name):
            return set(by_name[name].tags.values_list("slug", flat=True))

        def matches(name, selected):
            if not selected:
                return True
            return bool(tags_of(name) & set(selected))

        self.assertTrue(matches("Both Tags Clinic", ["dental"]))
        self.assertTrue(matches("Both Tags Clinic", ["gp"]))
        self.assertTrue(matches("Both Tags Clinic", ["dental", "aesthetic"]))
        self.assertFalse(matches("Aesthetic Only Clinic", ["dental"]))
        self.assertTrue(matches("Aesthetic Only Clinic", ["dental", "aesthetic"]))
        self.assertFalse(matches("No Tags Clinic", ["dental"]))
        self.assertTrue(matches("No Tags Clinic", []))

        ctx = {
            "c": by_name["Both Tags Clinic"],
            "request": self.request,
            "multi_location_brands": brands,
            "show_folder_badge": False,
            "is_trash_view": False,
            "is_uncategorized_view": True,
            "is_whatsapp_chats_view": False,
            "is_queue_view": False,
            "current_group_id": "uncategorized",
            "force_send_template_name": "",
        }
        row = render_to_string(
            "leads/partials/_lead_table_row.html", ctx, request=self.request
        )
        card = render_to_string(
            "leads/partials/_lead_grid_card.html", ctx, request=self.request
        )
        self.assertRegex(row, r'data-tags="[^"]*\bdental\b')
        self.assertRegex(row, r'data-tags="[^"]*\bgp\b')
        self.assertRegex(card, r'data-tags="[^"]*\bdental\b')
        self.assertRegex(card, r'data-tags="[^"]*\bgp\b')
        self.assertIn('data-tag-slug="gp"', row)
        self.assertIn('data-tag-slug="gp"', card)
        self.assertNotIn('data-tag-slug="dental"', row)
        self.assertNotIn('data-tag-slug="dental"', card)

        aes_ctx = dict(ctx)
        aes_ctx["c"] = by_name["Aesthetic Only Clinic"]
        aes_row = render_to_string(
            "leads/partials/_lead_table_row.html", aes_ctx, request=self.request
        )
        aes_card = render_to_string(
            "leads/partials/_lead_grid_card.html", aes_ctx, request=self.request
        )
        self.assertRegex(aes_row, r'data-tags="[^"]*\baesthetic\b')
        self.assertRegex(aes_card, r'data-tags="[^"]*\baesthetic\b')
        self.assertNotIn("lead-tag-chip", aes_row)
        self.assertNotIn("lead-tag-chip", aes_card)

    def test_js_persists_selected_tags_under_dashboard_key(self):
        from pathlib import Path

        boot = Path(__file__).resolve().parent / "static" / "leads" / "js" / "dashboard-boot.js"
        listing = Path(__file__).resolve().parent / "static" / "leads" / "js" / "lead-list.js"
        boot_src = boot.read_text(encoding="utf-8")
        list_src = listing.read_text(encoding="utf-8")
        self.assertIn("clinic_crm_lead_tag_filter", boot_src)
        self.assertIn("clinic_crm_lead_tag_filter", list_src)
        self.assertIn("leadRowMatchesTagFilter", list_src)
        self.assertIn("getLeadTagFilterSlugs", list_src)
