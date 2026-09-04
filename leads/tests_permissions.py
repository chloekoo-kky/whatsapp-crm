"""Role visibility, bulk IDOR, assign-to-user, and hunt/create owner tests."""

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from leads.models import Lead, SearchQueryRecord, UserProfile
from leads.permissions import owned_lead_ids, visible_leads
from leads.pipeline import get_or_create_uncategorized_group


def _make_user(username, role, *, superuser=False, password="pass"):
    User = get_user_model()
    if superuser:
        user = User.objects.create_superuser(username, f"{username}@t.test", password)
    else:
        user = User.objects.create_user(username, f"{username}@t.test", password)
    user.profile.role = role
    user.profile.save()
    return user


def _request(user):
    req = RequestFactory().get("/")
    req.user = user
    return req


class VisibleLeadsTests(TestCase):
    def setUp(self):
        self.sales = _make_user("sales_rep", UserProfile.ROLE_SALES)
        self.other = _make_user("other_rep", UserProfile.ROLE_SALES)
        self.supervisor = _make_user("supervisor", UserProfile.ROLE_SUPERVISOR)
        self.admin = _make_user("admin_user", UserProfile.ROLE_ADMIN)
        self.superuser = _make_user("root", UserProfile.ROLE_ADMIN, superuser=True)
        group = get_or_create_uncategorized_group()
        self.mine = Lead.objects.create(
            name="Mine Clinic",
            address="1 Sales Rd",
            group=group,
            assigned_to=self.sales,
        )
        self.theirs = Lead.objects.create(
            name="Theirs Clinic",
            address="2 Other Rd",
            group=group,
            assigned_to=self.other,
        )
        self.unowned = Lead.objects.create(
            name="Unowned Clinic",
            address="3 Free Rd",
            group=group,
        )

    def test_sales_only_sees_assigned_leads(self):
        pks = set(visible_leads(_request(self.sales)).values_list("pk", flat=True))
        self.assertEqual(pks, {self.mine.pk})

    def test_supervisor_and_admin_see_all(self):
        expected = {self.mine.pk, self.theirs.pk, self.unowned.pk}
        self.assertEqual(
            set(visible_leads(_request(self.supervisor)).values_list("pk", flat=True)),
            expected,
        )
        self.assertEqual(
            set(visible_leads(_request(self.admin)).values_list("pk", flat=True)),
            expected,
        )
        self.assertEqual(
            set(visible_leads(_request(self.superuser)).values_list("pk", flat=True)),
            expected,
        )

    def test_owned_lead_ids_drops_foreign_ids(self):
        kept = owned_lead_ids(_request(self.sales), [self.mine.pk, self.theirs.pk, 99999])
        self.assertEqual(kept, [self.mine.pk])


class BulkIdorTests(TestCase):
    def setUp(self):
        self.sales = _make_user("sales_idor", UserProfile.ROLE_SALES)
        self.other = _make_user("other_idor", UserProfile.ROLE_SALES)
        group = get_or_create_uncategorized_group()
        self.mine = Lead.objects.create(
            name="Idor Mine",
            address="10 Sales Rd",
            group=group,
            assigned_to=self.sales,
        )
        self.theirs = Lead.objects.create(
            name="Idor Theirs",
            address="11 Other Rd",
            group=group,
            assigned_to=self.other,
        )
        self.client = Client()
        self.client.force_login(self.sales)

    def test_bulk_manual_ignores_foreign_lead_id(self):
        response = self.client.post(
            reverse("leads_bulk_manual"),
            data={"ids": [self.theirs.pk], "category": "unknown"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.theirs.refresh_from_db()
        self.assertEqual(list(self.theirs.tags.values_list("slug", flat=True)), [])

    def test_bulk_auto_classify_ignores_foreign_lead_id(self):
        response = self.client.post(
            reverse("leads_bulk_auto_classify"),
            data={"ids": [self.theirs.pk]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.theirs.refresh_from_db()
        self.assertEqual(list(self.theirs.tags.values_list("slug", flat=True)), [])

    def test_bulk_queue_ignores_foreign_lead_id(self):
        response = self.client.post(
            reverse("leads_bulk_whatsapp_queue"),
            data={"ids": [self.theirs.pk]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["updated"], 0)
        self.theirs.refresh_from_db()
        self.assertNotEqual(self.theirs.whatsapp_status, Lead.WhatsappStatus.PENDING)

    def test_chat_inbox_404_for_foreign_lead(self):
        response = self.client.get(reverse("chat_inbox", args=[self.theirs.pk]))
        self.assertEqual(response.status_code, 404)


class AssignOwnerAndCreateTests(TestCase):
    def setUp(self):
        self.sales = _make_user("sales_assign", UserProfile.ROLE_SALES)
        self.sales_b = _make_user("sales_b", UserProfile.ROLE_SALES)
        self.supervisor = _make_user("super_assign", UserProfile.ROLE_SUPERVISOR)
        group = get_or_create_uncategorized_group()
        self.lead = Lead.objects.create(
            name="Assign Me",
            address="20 Assign Rd",
            group=group,
            assigned_to=self.sales,
        )

    def test_sales_cannot_reassign(self):
        client = Client()
        client.force_login(self.sales)
        response = client.post(
            reverse("leads_bulk_assign_owner"),
            data={"ids": [self.lead.pk], "user_id": self.sales_b.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.assigned_to_id, self.sales.pk)

    def test_supervisor_can_reassign_to_sales(self):
        client = Client()
        client.force_login(self.supervisor)
        response = client.post(
            reverse("leads_bulk_assign_owner"),
            data={"ids": [self.lead.pk], "user_id": self.sales_b.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["updated"], 1)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.assigned_to_id, self.sales_b.pk)
        self.assertIsNotNone(self.lead.assigned_at)

    def test_supervisor_can_bulk_reassign_multiple_leads(self):
        extra = Lead.objects.create(
            name="Assign Me Too",
            address="21 Assign Rd",
            group=self.lead.group,
            assigned_to=self.sales,
        )
        client = Client()
        client.force_login(self.supervisor)
        response = client.post(
            reverse("leads_bulk_assign_owner"),
            data={"ids": [self.lead.pk, extra.pk], "user_id": self.sales_b.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated"], 2)
        self.lead.refresh_from_db()
        extra.refresh_from_db()
        self.assertEqual(self.lead.assigned_to_id, self.sales_b.pk)
        self.assertEqual(extra.assigned_to_id, self.sales_b.pk)

    def test_sales_manual_create_assigns_self(self):
        client = Client()
        client.force_login(self.sales)
        response = client.post(
            reverse("lead_manual_create"),
            data={"name": "New Sales Lead", "address": "99 New Rd"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        lead = Lead.objects.get(pk=response.json()["id"])
        self.assertEqual(lead.assigned_to_id, self.sales.pk)

    def test_supervisor_manual_create_leaves_unassigned(self):
        client = Client()
        client.force_login(self.supervisor)
        response = client.post(
            reverse("lead_manual_create"),
            data={"name": "New Super Lead", "address": "98 New Rd"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        lead = Lead.objects.get(pk=response.json()["id"])
        self.assertIsNone(lead.assigned_to_id)

    def test_sales_does_not_see_assign_control(self):
        client = Client()
        client.force_login(self.sales)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("assign-to-user-btn", html)
        self.assertNotIn("bulk-assign-owner-open", html)

    def test_supervisor_sees_assign_control(self):
        client = Client()
        client.force_login(self.supervisor)
        response = client.get(reverse("dashboard"), {"group_id": "uncategorized"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("assign-to-user-btn", html)
        self.assertIn("bulk-assign-owner-open", html)
        self.assertIn("Assign to…", html)


class SuperuserExportBackupTests(TestCase):
    def setUp(self):
        self.sales = _make_user("sales_export", UserProfile.ROLE_SALES)
        self.admin = _make_user("admin_export", UserProfile.ROLE_ADMIN)
        self.superuser = _make_user("root_export", UserProfile.ROLE_ADMIN, superuser=True)
        group = get_or_create_uncategorized_group()
        self.lead = Lead.objects.create(
            name="Export Clinic",
            address="1 Export Rd",
            group=group,
        )

    def _dashboard_html(self, user):
        client = Client()
        client.force_login(user)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_admin_role_dashboard_hides_more_menu(self):
        html = self._dashboard_html(self.admin)
        self.assertNotIn('id="leads-more-open"', html)
        self.assertNotIn('id="export-xlsx-btn"', html)
        self.assertNotIn('id="import-xlsx-btn"', html)
        self.assertNotIn('id="backup-all-btn"', html)
        self.assertNotIn('id="restore-backup-btn"', html)
        self.assertIn("app-confirm-dialog", html)

    def test_sales_dashboard_hides_more_menu(self):
        html = self._dashboard_html(self.sales)
        self.assertNotIn('id="leads-more-open"', html)
        self.assertNotIn('id="export-xlsx-btn"', html)

    def test_superuser_dashboard_shows_more_menu(self):
        html = self._dashboard_html(self.superuser)
        self.assertIn('id="leads-more-open"', html)
        self.assertIn('id="export-xlsx-btn"', html)
        self.assertIn('id="import-xlsx-btn"', html)
        self.assertIn('id="backup-all-btn"', html)
        self.assertIn('id="restore-backup-btn"', html)
        self.assertIn("app-confirm-dialog", html)

    def test_admin_role_cannot_export_or_backup(self):
        client = Client()
        client.force_login(self.admin)
        export = client.get(reverse("clinics_export_xlsx"))
        self.assertEqual(export.status_code, 403)
        self.assertIn(b"Superuser required.", export.content)
        imp = client.post(reverse("import_leads_xlsx"))
        self.assertEqual(imp.status_code, 403)
        self.assertEqual(imp.json()["detail"], "Superuser required.")
        backup = client.get(reverse("export_full_backup"))
        self.assertEqual(backup.status_code, 403)
        self.assertIn(b"Superuser required.", backup.content)
        restore = client.post(reverse("import_full_backup"))
        self.assertEqual(restore.status_code, 403)
        self.assertEqual(restore.json()["detail"], "Superuser required.")

    def test_sales_cannot_export_or_backup(self):
        client = Client()
        client.force_login(self.sales)
        self.assertEqual(client.get(reverse("clinics_export_xlsx")).status_code, 403)
        self.assertEqual(client.post(reverse("import_leads_xlsx")).status_code, 403)
        self.assertEqual(client.get(reverse("export_full_backup")).status_code, 403)
        self.assertEqual(client.post(reverse("import_full_backup")).status_code, 403)

    def test_superuser_can_export_xlsx_and_backup(self):
        client = Client()
        client.force_login(self.superuser)
        export = client.get(reverse("clinics_export_xlsx"))
        self.assertEqual(export.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            export["Content-Type"],
        )
        backup = client.get(reverse("export_full_backup"), {"ids": str(self.lead.pk)})
        self.assertEqual(backup.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            backup["Content-Type"],
        )


class SuperuserScrapingTests(TestCase):
    def setUp(self):
        self.sales = _make_user("sales_hunt", UserProfile.ROLE_SALES)
        self.admin = _make_user("admin_hunt", UserProfile.ROLE_ADMIN)
        self.superuser = _make_user("root_hunt", UserProfile.ROLE_ADMIN, superuser=True)

    def _dashboard_html(self, user):
        client = Client()
        client.force_login(user)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _hunt_post(self, user):
        client = Client()
        client.force_login(user)
        return client.post(
            reverse("hunt_trigger"),
            data={"city": "Kuala Lumpur", "state": "Selangor", "shop_keyword": "clinic"},
            content_type="application/json",
        )

    def test_admin_role_dashboard_hides_scraping_panel(self):
        html = self._dashboard_html(self.admin)
        self.assertNotIn('id="scraping-panel"', html)
        self.assertNotIn('id="hunt-form"', html)

    def test_sales_dashboard_hides_scraping_panel(self):
        html = self._dashboard_html(self.sales)
        self.assertNotIn('id="scraping-panel"', html)
        self.assertNotIn('id="hunt-form"', html)

    def test_superuser_dashboard_shows_scraping_panel(self):
        html = self._dashboard_html(self.superuser)
        self.assertIn('id="scraping-panel"', html)
        self.assertIn('id="hunt-form"', html)
        self.assertIn("hunt-form-provider-label", html)
        self.assertIn("Outscraper", html)
        self.assertLess(
            html.find("hunt-form-provider-label"),
            html.find("hunt-form-limit-label"),
        )
        self.assertLess(
            html.find("hunt-form-limit-label"),
            html.find("hunt-form-options-label"),
        )
        self.assertIn("How many listings to fetch.", html)

    def test_admin_role_cannot_hunt(self):
        response = self._hunt_post(self.admin)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Superuser required.")

    def test_sales_cannot_hunt(self):
        response = self._hunt_post(self.sales)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Superuser required.")

    def test_admin_role_cannot_hunt_via_api(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            "/api/clinics/hunt",
            data={"city": "Kuala Lumpur", "shop_keyword": "clinic"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Superuser required.")

    def test_superuser_hunt_is_not_forbidden(self):
        from unittest.mock import Mock, patch

        result = Mock(
            created=0,
            skipped_existing=0,
            skipped_duplicate_phone=0,
            skipped_no_website=0,
            skipped_excluded=0,
            places_seen=0,
            errors=[],
        )
        client = Client()
        client.force_login(self.superuser)
        with patch("leads.views.fetch_leads", return_value=result):
            response = client.post(
                reverse("hunt_trigger"),
                data={
                    "city": "Kuala Lumpur",
                    "state": "Selangor",
                    "shop_keyword": "clinic",
                },
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_hunt_records_exclude_keywords_and_leads_created(self):
        from unittest.mock import Mock, patch

        result = Mock(
            created=3,
            skipped_existing=1,
            skipped_duplicate_phone=0,
            skipped_no_website=0,
            skipped_excluded=1,
            places_seen=5,
            errors=[],
        )
        client = Client()
        client.force_login(self.superuser)
        with patch("leads.views.fetch_leads", return_value=result):
            response = client.post(
                reverse("hunt_trigger"),
                data={
                    "city": "Petaling Jaya",
                    "state": "Selangor",
                    "shop_keyword": "clinic",
                    "query": "weight loss clinic",
                    "exclude_keywords": ["hospital", "pharmacy"],
                    "provider": "outscraper",
                },
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        rec = SearchQueryRecord.objects.get()
        self.assertEqual(rec.search_state, "Selangor")
        self.assertEqual(rec.search_city, "Petaling Jaya")
        self.assertEqual(rec.keyword, "clinic")
        self.assertEqual(rec.maps_search_query, "weight loss clinic")
        self.assertEqual(rec.exclude_keywords, ["hospital", "pharmacy"])
        self.assertEqual(rec.provider, "outscraper")
        self.assertEqual(rec.leads_created, 3)

    def test_sales_cannot_open_hunt_history(self):
        client = Client()
        client.force_login(self.sales)
        response = client.get(reverse("hunt_history"))
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Superuser required.", response.content)

    def test_admin_role_cannot_open_hunt_history(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("hunt_history"))
        self.assertEqual(response.status_code, 403)

    def test_superuser_hunt_history_lists_past_hunts(self):
        SearchQueryRecord.objects.create(
            keyword="clinic",
            maps_search_query="weight loss clinic",
            search_city="Petaling Jaya",
            search_state="Selangor",
            provider="outscraper",
            exclude_keywords=["hospital", "pharmacy"],
            leads_created=7,
        )
        client = Client()
        client.force_login(self.superuser)
        response = client.get(reverse("hunt_history"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Hunt History", html)
        self.assertIn("Selangor", html)
        self.assertIn("Petaling Jaya", html)
        self.assertIn("clinic", html)
        self.assertIn("weight loss clinic", html)
        self.assertIn("hospital", html)
        self.assertIn("pharmacy", html)
        self.assertIn("Outscraper", html)
        self.assertIn(">7<", html)

    def test_sales_sidebar_hides_hunt_history(self):
        html = self._dashboard_html(self.sales)
        self.assertNotIn(reverse("hunt_history"), html)
        self.assertNotIn("Hunt History", html)

    def test_superuser_sidebar_shows_hunt_history(self):
        html = self._dashboard_html(self.superuser)
        self.assertIn(reverse("hunt_history"), html)
        self.assertIn("Hunt History", html)

    def test_sales_sidebar_hides_serper_status(self):
        client = Client()
        client.force_login(self.sales)
        response = client.get(reverse("api_status_sidebar"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn("Serper Maps", html)
        self.assertIn("YCloud WhatsApp", html)

    def test_superuser_sidebar_shows_serper_status(self):
        client = Client()
        client.force_login(self.superuser)
        response = client.get(reverse("api_status_sidebar"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Serper Maps", response.content.decode())
