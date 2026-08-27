"""Additive Tag schema: seeded mirror of LeadCategoryType and backfill helpers."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch

from django.apps import apps as django_apps
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from leads.models import CategoryRule, Lead, LeadCategoryType, Tag
from leads.pipeline import get_or_create_uncategorized_group
from leads.services import classify_category_from_name, matching_category_slugs_from_name
from leads.tests import staff_client

_MIGRATION_PATH = Path(__file__).resolve().parent / "migrations" / "0046_tag_and_lead_tags.py"
_spec = importlib.util.spec_from_file_location("leads_tag_backfill_migration", _MIGRATION_PATH)
_migration = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_migration)
backfill_tags = _migration.backfill_tags
reverse_tag_backfill = _migration.reverse_tag_backfill


class _SchemaEditor:
    connection = connection


class TagBackfillTests(TestCase):
    def test_migration_mirrors_every_category_type(self):
        cat_rows = list(
            LeadCategoryType.objects.values("slug", "label", "sort_order", "is_system")
        )
        tag_rows = list(Tag.objects.values("slug", "label", "sort_order", "is_system"))
        self.assertEqual(len(tag_rows), len(cat_rows))
        self.assertCountEqual(tag_rows, cat_rows)

    def test_new_lead_is_not_dual_written(self):
        lead = Lead.objects.create(
            name="No Dual Write Clinic",
            address="1 Tag Test St",
            category="dental",
        )
        self.assertEqual(lead.tags.count(), 0)

    def test_backfill_assigns_tag_matching_category_and_is_idempotent(self):
        dental = Lead.objects.create(
            name="Dental Backfill Clinic",
            address="2 Tag Test St",
            category="dental",
        )
        unknown = Lead.objects.create(
            name="Unknown Backfill Clinic",
            address="3 Tag Test St",
            category="unknown",
        )
        LeadCategoryType.objects.create(
            slug="vet",
            label="Veterinary",
            sort_order=90,
            is_system=False,
        )
        orphan = Lead.objects.create(
            name="Vet Backfill Clinic",
            address="4 Tag Test St",
            category="vet",
        )

        backfill_tags(django_apps, _SchemaEditor())
        backfill_tags(django_apps, _SchemaEditor())

        self.assertEqual(
            Tag.objects.count(),
            LeadCategoryType.objects.count(),
        )
        self.assertEqual(
            list(dental.tags.values_list("slug", flat=True)),
            ["dental"],
        )
        self.assertEqual(
            list(unknown.tags.values_list("slug", flat=True)),
            ["unknown"],
        )
        self.assertEqual(
            list(orphan.tags.values_list("slug", flat=True)),
            ["vet"],
        )
        vet_tag = Tag.objects.get(slug="vet")
        self.assertEqual(vet_tag.label, "Veterinary")
        self.assertEqual(vet_tag.sort_order, 90)

    def test_reverse_then_forward_restores_mirror(self):
        Lead.objects.create(
            name="Reverse Clinic",
            address="5 Tag Test St",
            category="gp",
        )
        reverse_tag_backfill(django_apps, _SchemaEditor())
        self.assertEqual(Tag.objects.count(), 0)

        backfill_tags(django_apps, _SchemaEditor())
        cat_slugs = set(LeadCategoryType.objects.values_list("slug", flat=True))
        tag_slugs = set(Tag.objects.values_list("slug", flat=True))
        self.assertEqual(tag_slugs, cat_slugs)
        lead = Lead.objects.get(name="Reverse Clinic")
        self.assertEqual(list(lead.tags.values_list("slug", flat=True)), ["gp"])


def _serper_places_response(places):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json.return_value = {"places": places}
    return resp


class SerperImportTagTests(TestCase):
    def setUp(self):
        CategoryRule.objects.create(match_phrase="dental", category="dental", priority=10)
        CategoryRule.objects.create(match_phrase="skin", category="aesthetic", priority=20)
        CategoryRule.objects.create(match_phrase="clinic", category="gp", priority=50)

    def test_classify_still_returns_first_priority_match_only(self):
        self.assertEqual(
            classify_category_from_name("Q & M Dental Clinic"),
            "dental",
        )
        self.assertEqual(
            matching_category_slugs_from_name("Q & M Dental Clinic"),
            ["dental", "gp"],
        )
        self.assertEqual(classify_category_from_name("Random Bakery"), "unknown")
        self.assertEqual(matching_category_slugs_from_name("Random Bakery"), [])

    @override_settings(SERPER_API_KEY="test-key", HUNT_MAX_LIMIT=100)
    @patch("leads.services.requests.post")
    def test_new_lead_gets_all_matching_tags_and_single_category(self, mock_post):
        from leads.services import fetch_leads_from_serper

        mock_post.return_value = _serper_places_response(
            [
                {
                    "title": "Q & M Dental Clinic (Segamat)",
                    "address": "1 Tag Import St",
                    "phoneNumber": "+60121111001",
                },
            ]
        )
        result = fetch_leads_from_serper(
            "Segamat",
            "",
            num=20,
            shop_keyword="clinic",
            country="Malaysia",
        )
        self.assertEqual(result.created, 1)
        lead = Lead.objects.get(name="Q & M Dental Clinic (Segamat)")
        self.assertEqual(lead.category, "dental")
        self.assertCountEqual(
            list(lead.tags.values_list("slug", flat=True)),
            ["dental", "gp"],
        )

    @override_settings(SERPER_API_KEY="test-key", HUNT_MAX_LIMIT=100)
    @patch("leads.services.requests.post")
    def test_single_or_no_rule_match_is_one_tag_matching_category(self, mock_post):
        from leads.services import fetch_leads_from_serper

        mock_post.return_value = _serper_places_response(
            [
                {
                    "title": "Skin Lab Studio",
                    "address": "2 Tag Import St",
                    "phoneNumber": "+60121111002",
                },
                {
                    "title": "Sunrise Hardware",
                    "address": "3 Tag Import St",
                    "phoneNumber": "+60121111003",
                },
            ]
        )
        result = fetch_leads_from_serper(
            "Johor Bahru",
            "",
            num=20,
            shop_keyword="shop",
            country="Malaysia",
        )
        self.assertEqual(result.created, 2)

        single = Lead.objects.get(name="Skin Lab Studio")
        self.assertEqual(single.category, "aesthetic")
        self.assertEqual(list(single.tags.values_list("slug", flat=True)), ["aesthetic"])

        none = Lead.objects.get(name="Sunrise Hardware")
        self.assertEqual(none.category, "unknown")
        self.assertEqual(list(none.tags.values_list("slug", flat=True)), ["unknown"])

    @override_settings(SERPER_API_KEY="test-key", HUNT_MAX_LIMIT=100)
    @patch("leads.services.requests.post")
    def test_reimport_leaves_existing_tags_untouched(self, mock_post):
        from leads.services import fetch_leads_from_serper

        existing = Lead.objects.create(
            name="Q & M Dental Clinic (Segamat)",
            address="1 Tag Import St",
            category="service",
        )
        existing.tags.set(Tag.objects.filter(slug="invalid"))
        prior_tag_ids = list(existing.tags.values_list("id", flat=True))

        mock_post.return_value = _serper_places_response(
            [
                {
                    "title": "Q & M Dental Clinic (Segamat)",
                    "address": "1 Tag Import St",
                    "phoneNumber": "+60121111004",
                },
            ]
        )
        result = fetch_leads_from_serper(
            "Segamat",
            "",
            num=20,
            shop_keyword="clinic",
            country="Malaysia",
        )
        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped_existing, 1)
        existing.refresh_from_db()
        self.assertEqual(existing.category, "service")
        self.assertEqual(list(existing.tags.values_list("id", flat=True)), prior_tag_ids)
        self.assertEqual(list(existing.tags.values_list("slug", flat=True)), ["invalid"])


class TagManagementTests(TestCase):
    def test_save_creates_tag_not_category_type(self):
        client = staff_client()
        type_count = LeadCategoryType.objects.count()
        response = client.post(
            reverse("category_type_save"),
            data={"label": "Veterinary", "slug": "vet", "sort_order": "90"},
        )
        self.assertEqual(response.status_code, 302)
        tag = Tag.objects.get(slug="vet")
        self.assertEqual(tag.label, "Veterinary")
        self.assertEqual(tag.sort_order, 90)
        self.assertFalse(tag.is_system)
        self.assertFalse(LeadCategoryType.objects.filter(slug="vet").exists())
        self.assertEqual(LeadCategoryType.objects.count(), type_count)

    def test_save_updates_tag_slug_and_derived_category_refs(self):
        client = staff_client()
        client.post(
            reverse("category_type_save"),
            data={"label": "Pilates", "slug": "pilates", "sort_order": "80"},
        )
        tag = Tag.objects.get(slug="pilates")
        original_pk = tag.pk
        lead = Lead.objects.create(
            name="Pilates Rename Clinic",
            address="1 Rename St",
            category="pilates",
        )
        lead.tags.add(tag)
        CategoryRule.objects.create(
            match_phrase="pilates",
            category="pilates",
            priority=10,
        )

        response = client.post(
            reverse("category_type_save"),
            data={
                "id": str(tag.pk),
                "label": "Pilates Studio",
                "slug": "pilates_studio",
                "sort_order": "75",
            },
        )
        self.assertEqual(response.status_code, 302)
        tag.refresh_from_db()
        self.assertEqual(tag.pk, original_pk)
        self.assertEqual(tag.slug, "pilates_studio")
        self.assertEqual(tag.label, "Pilates Studio")
        self.assertEqual(tag.sort_order, 75)
        self.assertFalse(Tag.objects.filter(slug="pilates").exists())
        lead.refresh_from_db()
        self.assertEqual(lead.category, "pilates_studio")
        self.assertEqual(list(lead.tags.values_list("slug", flat=True)), ["pilates_studio"])
        self.assertEqual(
            CategoryRule.objects.get(match_phrase="pilates").category,
            "pilates_studio",
        )
        self.assertFalse(LeadCategoryType.objects.filter(slug="pilates_studio").exists())

    def test_delete_unused_tag(self):
        client = staff_client()
        client.post(
            reverse("category_type_save"),
            data={"label": "Pilates", "slug": "pilates", "sort_order": "80"},
        )
        tag = Tag.objects.get(slug="pilates")
        type_count = LeadCategoryType.objects.count()

        response = client.post(reverse("category_type_delete", kwargs={"pk": tag.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Tag.objects.filter(pk=tag.pk).exists())
        self.assertEqual(LeadCategoryType.objects.count(), type_count)

    def test_delete_blocked_when_lead_or_rule_still_uses_tag(self):
        client = staff_client()
        client.post(
            reverse("category_type_save"),
            data={"label": "Veterinary", "slug": "vet", "sort_order": "90"},
        )
        tag = Tag.objects.get(slug="vet")

        lead = Lead.objects.create(
            name="In-use Tag Clinic",
            address="10 Sync St",
            category="vet",
        )
        blocked_lead = client.post(reverse("category_type_delete", kwargs={"pk": tag.pk}))
        self.assertEqual(blocked_lead.status_code, 400)
        self.assertEqual(
            blocked_lead.content.decode(),
            "Leads still use this tag. Reassign them before deleting.",
        )
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())

        lead.category = "unknown"
        lead.save(update_fields=["category"])
        CategoryRule.objects.create(
            match_phrase="veterinary",
            category="vet",
            priority=10,
        )
        blocked_rule = client.post(reverse("category_type_delete", kwargs={"pk": tag.pk}))
        self.assertEqual(blocked_rule.status_code, 400)
        self.assertEqual(
            blocked_rule.content.decode(),
            "Import rules still reference this tag. Update or delete those rules first.",
        )
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())

        CategoryRule.objects.filter(category="vet").delete()
        lead.tags.add(tag)
        blocked_tag = client.post(reverse("category_type_delete", kwargs={"pk": tag.pk}))
        self.assertEqual(blocked_tag.status_code, 400)
        self.assertEqual(
            blocked_tag.content.decode(),
            "Leads still use this tag. Reassign them before deleting.",
        )
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())

    @override_settings(SERPER_API_KEY="test-key", HUNT_MAX_LIMIT=100)
    @patch("leads.services.requests.post")
    def test_import_assigns_tag_added_from_manage_page(self, mock_post):
        from leads.services import fetch_leads_from_serper

        client = staff_client()
        client.post(
            reverse("category_type_save"),
            data={"label": "Veterinary", "slug": "vet", "sort_order": "90"},
        )
        client.post(
            reverse("category_rule_save"),
            data={
                "match_phrase": "veterinary",
                "category": "vet",
                "priority": "10",
            },
        )
        self.assertTrue(Tag.objects.filter(slug="vet").exists())
        self.assertFalse(LeadCategoryType.objects.filter(slug="vet").exists())

        mock_post.return_value = _serper_places_response(
            [
                {
                    "title": "Sunrise Veterinary Hospital",
                    "address": "20 Sync Import St",
                    "phoneNumber": "+60121111009",
                },
            ]
        )
        result = fetch_leads_from_serper(
            "Johor Bahru",
            "",
            num=20,
            shop_keyword="clinic",
            country="Malaysia",
        )
        self.assertEqual(result.created, 1)
        lead = Lead.objects.get(name="Sunrise Veterinary Hospital")
        self.assertEqual(lead.category, "vet")
        self.assertEqual(list(lead.tags.values_list("slug", flat=True)), ["vet"])


class TagWritePathTests(TestCase):
    def setUp(self):
        self.group = get_or_create_uncategorized_group()
        self.client = staff_client()
        self.lead = Lead.objects.create(
            name="Tag Write Clinic",
            address="10 Tag Write St",
            group=self.group,
            category="unknown",
        )
        self.lead.tags.set(Tag.objects.filter(slug="unknown"))

    def test_derived_category_prefers_non_system_then_sort_order(self):
        gp = Tag.objects.get(slug="gp")
        dental = Tag.objects.get(slug="dental")
        unknown = Tag.objects.get(slug="unknown")
        invalid = Tag.objects.get(slug="invalid")
        ordered = Tag.from_slugs(["dental", "gp"])
        self.assertEqual([t.slug for t in ordered], ["gp", "dental"])
        self.assertEqual(Tag.derived_category_slug(ordered), "gp")
        self.assertEqual(
            Tag.derived_category_slug(Tag.from_slugs(["unknown", "dental"])),
            "dental",
        )
        self.assertEqual(Tag.derived_category_slug([unknown]), "unknown")
        self.assertEqual(Tag.derived_category_slug([invalid]), "invalid")
        self.assertEqual(Tag.derived_category_slug([]), "unknown")

    def test_clinic_update_sets_tags_and_derives_category(self):
        response = self.client.patch(
            reverse("clinic_update", kwargs={"pk": self.lead.pk}),
            data=json.dumps(
                {
                    "name": self.lead.name,
                    "address": self.lead.address,
                    "tags": ["dental", "gp"],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertCountEqual(payload["tags"], ["dental", "gp"])
        self.assertEqual(payload["category"], "gp")
        self.lead.refresh_from_db()
        self.assertCountEqual(
            list(self.lead.tags.values_list("slug", flat=True)),
            ["dental", "gp"],
        )
        self.assertEqual(self.lead.category, "gp")

    def test_clinic_update_empty_tags_clears_m2m_and_uses_unknown(self):
        self.lead.tags.set(Tag.objects.filter(slug__in=["dental", "gp"]))
        self.lead.category = "gp"
        self.lead.save(update_fields=["category"])
        response = self.client.patch(
            reverse("clinic_update", kwargs={"pk": self.lead.pk}),
            data=json.dumps(
                {
                    "name": self.lead.name,
                    "address": self.lead.address,
                    "tags": [],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(list(self.lead.tags.values_list("slug", flat=True)), [])
        self.assertEqual(self.lead.category, "unknown")

    def test_clinic_update_rejects_unknown_tag_slug(self):
        response = self.client.patch(
            reverse("clinic_update", kwargs={"pk": self.lead.pk}),
            data=json.dumps(
                {
                    "name": self.lead.name,
                    "address": self.lead.address,
                    "tags": ["not-a-real-tag"],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid tag.")

    def test_manual_create_assigns_selected_tags(self):
        response = self.client.post(
            reverse("lead_manual_create"),
            data=json.dumps(
                {
                    "name": "Manual Tag Lead",
                    "address": "11 Tag Write St",
                    "tags": ["aesthetic", "dental"],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        lead = Lead.objects.get(pk=response.json()["id"])
        self.assertCountEqual(
            list(lead.tags.values_list("slug", flat=True)),
            ["aesthetic", "dental"],
        )
        self.assertEqual(lead.category, "aesthetic")

    def test_bulk_manual_replaces_tags_on_owned_leads(self):
        other = Lead.objects.create(
            name="Bulk Other Clinic",
            address="12 Tag Write St",
            group=self.group,
            category="unknown",
        )
        response = self.client.post(
            reverse("leads_bulk_manual"),
            data=json.dumps(
                {
                    "ids": [self.lead.pk, other.pk],
                    "tags": ["fitness", "cafe"],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["updated"], 2)
        self.assertCountEqual(payload["tags"], ["fitness", "cafe"])
        self.assertEqual(payload["category"], "fitness")
        for lead in (self.lead, other):
            lead.refresh_from_db()
            self.assertCountEqual(
                list(lead.tags.values_list("slug", flat=True)),
                ["fitness", "cafe"],
            )
            self.assertEqual(lead.category, "fitness")
            self.assertTrue(lead.is_processed)

    def test_bulk_manual_requires_at_least_one_tag(self):
        response = self.client.post(
            reverse("leads_bulk_manual"),
            data=json.dumps({"ids": [self.lead.pk], "tags": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Select at least one tag.")

    def test_api_list_and_detail_include_tag_slugs(self):
        self.lead.tags.set(Tag.objects.filter(slug__in=["dental", "gp"]))
        detail = self.client.get(f"/api/clinics/{self.lead.pk}")
        self.assertEqual(detail.status_code, 200)
        self.assertCountEqual(detail.json()["tags"], ["dental", "gp"])

        listing = self.client.get("/api/clinics/")
        self.assertEqual(listing.status_code, 200)
        rows = listing.json()
        match = next(row for row in rows if row["id"] == self.lead.pk)
        self.assertCountEqual(match["tags"], ["dental", "gp"])

    def test_dashboard_write_dialogs_use_tag_pickers(self):
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn('id="clinic-edit-tags"', html)
        self.assertIn('id="lead-create-tags"', html)
        self.assertIn('id="bulk-manual-tags"', html)
        self.assertNotIn('id="clinic-edit-type"', html)
        self.assertNotIn('id="lead-create-type"', html)
        self.assertNotIn('id="bulk-manual-category"', html)
        self.assertIn(">Set tags<", html)
        self.assertNotIn(">Set category<", html)

    def test_edit_dialog_js_prefills_from_data_tags(self):
        js = (
            Path(__file__).resolve().parent
            / "static"
            / "leads"
            / "js"
            / "lead-dialogs.js"
        ).read_text(encoding="utf-8")
        self.assertIn("Array.isArray(data.tags)", js)
        self.assertIn("clinic-edit-tags", js)
        self.assertIn("setTagPickerSlugs", js)
        self.assertNotIn("clinic-edit-type", js)
