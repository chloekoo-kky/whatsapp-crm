"""Role visibility, bulk IDOR, assign-to-user, and hunt/create owner tests."""

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from leads.models import Lead, UserProfile
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
            category="unknown",
            assigned_to=self.sales,
        )
        self.theirs = Lead.objects.create(
            name="Idor Theirs",
            address="11 Other Rd",
            group=group,
            category="unknown",
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
        self.assertEqual(self.theirs.category, "unknown")

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
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("assign-to-user-btn", html)
        self.assertIn("bulk-assign-owner-open", html)


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
        self.assertNotIn("leads-more-open", html)
        self.assertNotIn("export-xlsx-btn", html)
        self.assertNotIn("backup-all-btn", html)
        self.assertNotIn("restore-backup-btn", html)
        self.assertIn("app-confirm-dialog", html)

    def test_sales_dashboard_hides_more_menu(self):
        html = self._dashboard_html(self.sales)
        self.assertNotIn("leads-more-open", html)
        self.assertNotIn("export-xlsx-btn", html)

    def test_superuser_dashboard_shows_more_menu(self):
        html = self._dashboard_html(self.superuser)
        self.assertIn("leads-more-open", html)
        self.assertIn("export-xlsx-btn", html)
        self.assertIn("backup-all-btn", html)
        self.assertIn("restore-backup-btn", html)
        self.assertIn("app-confirm-dialog", html)

    def test_admin_role_cannot_export_or_backup(self):
        client = Client()
        client.force_login(self.admin)
        export = client.get(reverse("clinics_export_xlsx"))
        self.assertEqual(export.status_code, 403)
        self.assertIn(b"Superuser required.", export.content)
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
