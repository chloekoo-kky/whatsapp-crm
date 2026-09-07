"""Grid card and list row share field partials and keep view-specific wrappers."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from leads.models import Lead, Tag, WhatsAppBatchSchedule
from leads.pipeline import get_or_create_ready_group, get_or_create_uncategorized_group
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
            "WhatsApp batch ·",
            "Sent ·",
            "~4 branches",
            "lead-tag-chip",
            "lead-chain-tag",
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

    def test_chain_tag_follows_business_name(self):
        card = self._card()
        name_block = card[card.find("clinic-name-cell-inner") : card.find("clinic-source-line")]
        self.assertIn("Shared Fields Clinic", name_block)
        self.assertIn("lead-chain-tag", name_block)
        self.assertGreater(name_block.find("lead-chain-tag"), name_block.find("Shared Fields Clinic"))
        self.assertIn(">C</span>", name_block)
        self.assertLess(name_block.find("</a>"), name_block.find("lead-chain-tag"))

        from leads.views import _name_cell_html

        patched = _name_cell_html(self.lead)
        self.assertIn("lead-chain-tag", patched)
        self.assertIn(">C</span>", patched)

        self.lead.is_chain = False
        self.lead.save(update_fields=["is_chain"])
        qs = _annotate_lead_dashboard_qs(Lead.objects.filter(pk=self.lead.pk))
        clinics, brands = _dashboard_prepare_clinics(qs, request=self.request)
        self.ctx["c"] = clinics[0]
        self.ctx["multi_location_brands"] = brands
        card = self._card()
        name_block = card[card.find("clinic-name-cell-inner") : card.find("clinic-source-line")]
        self.assertNotIn("lead-chain-tag", name_block)
        self.assertNotIn("lead-chain-tag", _name_cell_html(self.lead))

    def test_whatsapp_icon_opens_business_app_scheme(self):
        card = self._card()
        row = self._row()
        for html in (card, row):
            with self.subTest(view="card" if html is card else "row"):
                self.assertIn("whatsapp://send?phone=60123456789", html)
                self.assertIn('data-wa-digits="60123456789"', html)
                self.assertIn("Open in WhatsApp Business", html)
                self.assertNotIn("https://wa.me/60123456789", html)
                self.assertNotIn('title="Open in WhatsApp"', html)

    def test_batch_badge_sits_below_lead_details(self):
        card = self._card()
        row = self._row()
        for html in (card, row):
            with self.subTest(view="card" if html is card else "row"):
                self.assertGreater(
                    html.find("clinic-batch-lines"),
                    html.find("clinic-name-cell-inner"),
                )
                self.assertGreater(
                    html.find("clinic-batch-lines"),
                    html.find("clinic-created-line"),
                )
        self.assertLess(
            card.find("clinic-batch-lines"),
            card.find("lead-card-bottom-actions"),
        )
        self.assertIn("justify-end pb-2", card)
        self.assertIn("</div>", card[card.find("clinic-created-line"):card.find("clinic-batch-lines")])

    def test_dispatched_card_shows_sent_chip_beside_whatsapp(self):
        card = self._card()
        row = self._row()
        for html in (card, row):
            with self.subTest(view="card" if html is card else "row"):
                self.assertIn("clinic-sent-badge", html)
                self.assertGreater(html.find("clinic-sent-badge"), html.find("wa-me-open-btn"))
                self.assertGreater(html.find("clinic-sent-badge"), html.find("clinic-phone-wa-row"))
        self.assertNotIn("clinic-card--dispatched", card)
        self.assertNotIn("border-emerald-400", card)
        header = card[card.find("clinic-card-header-actions"):card.find("clinic-name-cell-inner")]
        self.assertNotIn("clinic-sent-badge", header)

        self.lead.whatsapp_status = "sent"
        self.lead.whatsapp_sent_at = timezone.now()
        self.lead.save(update_fields=["whatsapp_status", "whatsapp_sent_at"])
        qs = _annotate_lead_dashboard_qs(Lead.objects.filter(pk=self.lead.pk))
        clinics, brands = _dashboard_prepare_clinics(qs, request=self.request)
        self.ctx["c"] = clinics[0]
        self.ctx["multi_location_brands"] = brands
        card = self._card()
        self.assertIn("clinic-card--dispatched", card)
        self.assertIn('data-whatsapp-dispatched="1"', card)
        self.assertIn("clinic-sent-badge", card)
        self.assertIn('title="WhatsApp message sent"', card)
        self.assertGreater(card.find("clinic-sent-badge"), card.find("wa-me-open-btn"))
        self.assertNotIn("border-emerald-400", card)
        self.assertNotIn("hover:border-emerald-500", card)
        header = card[card.find("clinic-card-header-actions"):card.find("clinic-name-cell-inner")]
        self.assertNotIn("clinic-sent-badge", header)

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

    def test_card_tag_chips_sit_on_own_row_above_name(self):
        card = self._card()
        self.assertGreater(
            card.find("clinic-type-cell"),
            card.find("clinic-card-header-actions"),
        )
        self.assertGreater(
            card.find("clinic-name-cell-inner"),
            card.find("clinic-type-cell"),
        )
        self.assertGreater(
            card.find("clinic-type-cell"),
            card.find("lead-vip-star-btn"),
        )
        self.assertIn("lead-tag-chips", card[card.find("clinic-type-cell"):card.find("clinic-name-cell-inner")])

    def test_assigned_line_is_superuser_only_on_cards(self):
        sales = get_user_model().objects.create_user(
            "card_sales", "card_sales@t.test", "pass"
        )
        self.lead.assigned_to = sales
        self.lead.save()
        self.assertIsNotNone(self.lead.assigned_at)
        qs = _annotate_lead_dashboard_qs(Lead.objects.filter(pk=self.lead.pk))
        clinics, brands = _dashboard_prepare_clinics(qs, request=self.request)
        self.ctx["c"] = clinics[0]
        card = self._card()
        row = self._row()
        self.assertIn("clinic-assigned-to-line", card)
        self.assertIn("clinic-assigned-date-line", card)
        self.assertIn("Assigned to", card)
        self.assertIn("card_sales", card)
        self.assertIn("Assigned date", card)
        self.assertGreater(card.find("clinic-assigned-to-line"), card.find("clinic-name-cell-inner"))
        self.assertLess(card.find("clinic-assigned-to-line"), card.find("clinic-source-line"))
        self.assertGreater(card.find("clinic-assigned-date-line"), card.find("clinic-created-line"))
        self.assertNotIn("clinic-assigned-line", row)

        supervisor = get_user_model().objects.create_user(
            "card_super", "card_super@t.test", "pass"
        )
        from leads.models import UserProfile

        UserProfile.objects.update_or_create(
            user=supervisor, defaults={"role": UserProfile.ROLE_SUPERVISOR}
        )
        self.request.user = supervisor
        card = self._card()
        self.assertNotIn("clinic-assigned-to-line", card)
        self.assertNotIn("clinic-assigned-date-line", card)

    def test_dashboard_renders_both_views_with_shared_fields(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("dashboard"), {"group_id": "uncategorized"})
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
        self.assertIn("New", card)
        self.assertIn("New", row)
        self.assertNotIn("Uncategorized", card)
        self.assertNotIn("Uncategorized", row)

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

    def test_ready_tab_shows_whatsapp_batch_badge_on_cards(self):
        ready = get_or_create_ready_group()
        self.lead.group = ready
        self.lead.save(update_fields=["group"])
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("get_leads_table"), {"group_id": str(ready.pk)})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for html in (payload["grid_html"], payload["tbody_html"]):
            with self.subTest(view="grid" if html is payload["grid_html"] else "list"):
                self.assertIn("Shared Fields Clinic", html)
                self.assertIn("clinic-batch-lines", html)
                self.assertIn("WhatsApp batch ·", html)
                self.assertIn("Sent ·", html)
        self.assertIn("lead-dequeue-btn", payload["grid_html"])
        self.assertIn("Remove from WhatsApp batch", payload["grid_html"])
        self.assertNotIn("lead-join-queue-btn", payload["grid_html"])

    def test_tick_stays_grey_when_pending_without_batch(self):
        ready = get_or_create_ready_group()
        self.lead.group = ready
        self.lead.whatsapp_status = Lead.WhatsappStatus.PENDING
        self.lead.save(update_fields=["group", "whatsapp_status"])
        self.lead.whatsapp_batches.clear()
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("get_leads_table"), {"group_id": str(ready.pk)})
        self.assertEqual(response.status_code, 200)
        html = response.json()["grid_html"]
        self.assertIn("lead-join-queue-btn", html)
        self.assertIn("Assign to a WhatsApp batch", html)
        self.assertNotIn("lead-dequeue-btn", html)


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
        response = client.get(reverse("dashboard"), {"group_id": "uncategorized"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="lead-tag-filter"', html)
        self.assertIn('id="content-toolbar"', html)
        self.assertRegex(html, r'id="content-toolbar"[^>]*\bz-30\b')
        self.assertRegex(html, r'id="leads-scroll-container"[^>]*\bz-0\b')
        self.assertIn('z-[200]', html)
        self.assertIn("lead-tag-filter-chip", html)
        self.assertIn("lead-tag-filter-count", html)
        self.assertIn('data-tag-slug="dental"', html)
        self.assertIn('data-tag-slug="gp"', html)
        self.assertIn('data-tag-slug="aesthetic"', html)
        self.assertRegex(
            html,
            r'data-tag-slug="dental"[^>]*>[\s\S]*?lead-tag-filter-count[^>]*>1<',
        )
        self.assertRegex(
            html,
            r'data-tag-slug="gp"[^>]*>[\s\S]*?lead-tag-filter-count[^>]*>1<',
        )
        self.assertRegex(
            html,
            r'data-tag-slug="aesthetic"[^>]*>[\s\S]*?lead-tag-filter-count[^>]*>1<',
        )
        self.assertIn("Match all selected", html)
        self.assertNotIn("lead-tag-filter-cb", html)
        self.assertNotIn("lead-tag-filter-toggle", html)
        self.assertIn('id="lead-tag-filter-manage"', html)
        self.assertIn('id="manage-tags-dialog"', html)
        self.assertIn("Manage tags", html)
        self.assertNotIn('id="lead-tag-filter-add"', html)
        self.assertNotIn('id="lead-tag-filter-create"', html)

    def test_filter_control_hides_zero_count_tags(self):
        client = Client()
        client.force_login(self.user)
        html = client.get(reverse("dashboard"), {"group_id": "uncategorized"}).content.decode()
        self.assertRegex(
            html,
            r'data-tag-slug="unknown"[^>]*\bhidden\b',
        )
        self.assertNotRegex(
            html,
            r'data-tag-slug="dental"[^>]*\bhidden\b',
        )
        self.assertNotRegex(
            html,
            r'data-tag-slug="gp"[^>]*\bhidden\b',
        )
        self.assertNotRegex(
            html,
            r'data-tag-slug="aesthetic"[^>]*\bhidden\b',
        )

    def test_leads_table_returns_tag_counts_for_current_folder(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("get_leads_table"), {"group_id": "uncategorized"})
        self.assertEqual(response.status_code, 200)
        counts = response.json()["tag_counts"]
        self.assertEqual(counts.get("dental"), 1)
        self.assertEqual(counts.get("gp"), 1)
        self.assertEqual(counts.get("aesthetic"), 1)

    def test_and_semantics_from_row_data_tags_in_both_views(self):
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
            return set(selected).issubset(tags_of(name))

        self.assertTrue(matches("Both Tags Clinic", ["dental"]))
        self.assertTrue(matches("Both Tags Clinic", ["gp"]))
        self.assertTrue(matches("Both Tags Clinic", ["dental", "gp"]))
        self.assertFalse(matches("Both Tags Clinic", ["dental", "aesthetic"]))
        self.assertFalse(matches("Aesthetic Only Clinic", ["dental"]))
        self.assertFalse(matches("Aesthetic Only Clinic", ["dental", "aesthetic"]))
        self.assertTrue(matches("Aesthetic Only Clinic", ["aesthetic"]))
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
        self.assertNotIn('data-tag-slug="', aes_row)
        self.assertNotIn('data-tag-slug="', aes_card)

    def test_js_persists_selected_tags_under_dashboard_key(self):
        from pathlib import Path

        boot = Path(__file__).resolve().parent / "static" / "leads" / "js" / "dashboard-boot.js"
        listing = Path(__file__).resolve().parent / "static" / "leads" / "js" / "lead-list.js"
        boot_src = boot.read_text(encoding="utf-8")
        list_src = listing.read_text(encoding="utf-8")
        init = Path(__file__).resolve().parent / "static" / "leads" / "js" / "dashboard-init.js"
        styles = (
            Path(__file__).resolve().parent
            / "templates"
            / "leads"
            / "partials"
            / "_workspace_app_styles.html"
        )
        init_src = init.read_text(encoding="utf-8")
        styles_src = styles.read_text(encoding="utf-8")
        self.assertIn("clinic_crm_lead_tag_filter", boot_src)
        self.assertIn("clinic_crm_lead_tag_filter", list_src)
        self.assertIn("leadRowMatchesTagFilter", list_src)
        self.assertIn("getLeadTagFilterSlugs", list_src)
        self.assertIn("fadeLeadsOutOfCurrentFilters", list_src)
        self.assertIn("lead-card--filter-exit", list_src)
        self.assertIn("lead-card--filter-exit", styles_src)
        self.assertIn("fadeLeadsOutOfCurrentFilters([id])", list_src)
        self.assertIn("showLeadStatusToast", list_src)
        self.assertIn("lead-status-toast--in", list_src)
        self.assertIn("filter-chain-only", list_src)
        self.assertIn("data-is-chain", list_src)
        self.assertIn("filter-chain-only", init_src)
        self.assertIn("filter-no-chain-only", list_src)
        self.assertIn("filter-no-chain-only", init_src)
        self.assertIn("filter-unsent-message-only", list_src)
        self.assertIn("filter-unsent-message-only", init_src)
        self.assertIn("bulk-mark-sent-btn", init_src)
        self.assertIn("bulkMarkSelectedSent", init_src)
        bulk = Path(__file__).resolve().parent / "static" / "leads" / "js" / "bulk-actions.js"
        bulk_src = bulk.read_text(encoding="utf-8")
        self.assertIn("bottom_actions", bulk_src)
        self.assertIn("__swapLeadBottomActionsHtml", bulk_src)
        self.assertIn("group_id: gid", bulk_src)
        htmx_setup = (
            Path(__file__).resolve().parent
            / "templates"
            / "leads"
            / "partials"
            / "_htmx_setup.html"
        )
        htmx_src = htmx_setup.read_text(encoding="utf-8")
        self.assertIn("__ensureLeadChatAction", htmx_src)
        self.assertIn("lead-card-active-chat-btn", htmx_src)
        bulk_idx = init_src.find("dashboardJsConfig.bulkManualUrl")
        self.assertGreater(bulk_idx, -1)
        bulk_chunk = init_src[bulk_idx : bulk_idx + 1800]
        self.assertIn("fadeLeadsOutOfCurrentFilters(ids)", bulk_chunk)
        self.assertNotIn("window.location.reload()", bulk_chunk)
