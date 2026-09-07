import json
from datetime import date
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.db.models import Exists, OuterRef

from leads.models import CategoryRule, ChatMessage, Lead, LeadConversationLog, LeadGroup, SearchQueryRecord, Tag, WhatsAppConfig, WhatsAppScriptTemplate
from leads.chat_messages import record_inbound_chat_message, record_outbound_chat_message
from leads.display import (
    lead_google_maps_url,
    lead_in_active_whatsapp_batch,
    lead_phone_list,
    lead_whatsapp_active_chat,
    lead_whatsapp_dispatched,
    normalize_manual_phone,
    whatsapp_business_open_url,
    whatsapp_e164_digits,
    whatsapp_me_url,
)
from leads.views import _annotate_lead_dashboard_qs, _leads_qs_for_tab
from leads.whatsapp_service import (
    compose_free_text_template,
    compose_free_text_templates_for_lead,
    compose_outbound_message,
    free_text_templates_for_manage,
    free_text_templates_saved,
    render_script_template,
)
from leads.whatsapp_webhook import parse_meta_cloud_webhook
from leads.pipeline import (
    QUEUE_GROUP_NAME,
    QUEUE_DISPLAY_NAME,
    READY_DISPLAY_NAME,
    READY_GROUP_NAME,
    TRASH_GROUP_NAME,
    UNCATEGORIZED_DISPLAY_NAME,
    UNCATEGORIZED_GROUP_NAME,
    WHATSAPP_CHATS_GROUP_NAME,
    apply_group_assignment_side_effects,
    ensure_pipeline_system_groups,
    enqueue_leads_for_whatsapp,
    get_or_create_uncategorized_group,
    lead_group_display_name,
    move_leads_to_ready,
    phone_exists_in_database,
)


def staff_client(**kwargs):
    """Logged-in superuser client for view tests (LoginRequiredMiddleware)."""
    User = get_user_model()
    suffix = str(User.objects.count())
    user = User.objects.create_superuser(f"_s{suffix}", f"_s{suffix}@t.test", "pass")
    client = Client(**kwargs)
    client.force_login(user)
    return client


class PipelineGroupTests(TestCase):
    def test_system_groups_are_created(self):
        groups = ensure_pipeline_system_groups()
        self.assertEqual(groups["uncategorized"].name, UNCATEGORIZED_GROUP_NAME)
        self.assertEqual(groups["ready"].name, READY_GROUP_NAME)
        self.assertEqual(groups["queue"].name, QUEUE_GROUP_NAME)
        self.assertEqual(groups["whatsapp_chats"].name, WHATSAPP_CHATS_GROUP_NAME)
        self.assertEqual(groups["trash"].name, TRASH_GROUP_NAME)

    def test_uncategorized_display_name_is_new(self):
        self.assertEqual(UNCATEGORIZED_DISPLAY_NAME, "New")
        self.assertEqual(lead_group_display_name(UNCATEGORIZED_GROUP_NAME), "New")
        self.assertEqual(lead_group_display_name(None), "New")
        self.assertEqual(lead_group_display_name(READY_GROUP_NAME), READY_DISPLAY_NAME)
        self.assertEqual(lead_group_display_name(QUEUE_GROUP_NAME), QUEUE_DISPLAY_NAME)
        self.assertEqual(lead_group_display_name("Aesthetic"), "Aesthetic")

    def test_dashboard_shows_system_views_without_custom_groups(self):
        LeadGroup.objects.create(name="Johor Folder", sort_order=20)
        client = staff_client()
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-group-id="uncategorized"', html)
        self.assertIn("lead-group-tabs-system", html)
        self.assertIn("lead-group-tab--system", html)
        self.assertNotIn("lead-group-tabs-custom", html)
        self.assertNotIn("lead-group-tab--custom", html)
        self.assertRegex(html, r'data-group-id="uncategorized"[^>]*>[\s\S]*?\bNew\b')
        self.assertIn(">Ready<", html)
        ready = ensure_pipeline_system_groups()["ready"]
        self.assertRegex(
            html,
            r'data-group-id="' + str(ready.pk) + r'"[^>]*aria-selected="true"',
        )
        self.assertRegex(
            html,
            r'data-group-id="uncategorized"[^>]*aria-selected="false"',
        )
        self.assertNotIn("Uncategorized", html)
        self.assertNotIn("Johor Folder", html)
        self.assertNotIn("+ New group", html)
        self.assertNotIn("Move to group", html)
        self.assertIn("Views", html)
        self.assertIn("Set tags", html)
        self.assertIn("Mark sent", html)
        self.assertIn("Assign to…", html)
        manual_idx = html.find('id="bulk-manual-open"')
        mark_sent_idx = html.find('id="bulk-mark-sent-btn"')
        assign_idx = html.find('id="bulk-assign-owner-open"')
        ready_idx = html.find('id="bulk-move-ready-btn"')
        dock_idx = html.find('id="bulk-action-dock"')
        self.assertNotEqual(manual_idx, -1)
        self.assertNotEqual(mark_sent_idx, -1)
        self.assertNotEqual(assign_idx, -1)
        self.assertNotEqual(ready_idx, -1)
        self.assertLess(manual_idx, mark_sent_idx)
        self.assertLess(mark_sent_idx, assign_idx)
        self.assertLess(assign_idx, ready_idx)
        self.assertLess(ready_idx, dock_idx)
        self.assertIn("Choose batch", html)
        self.assertNotIn('aria-label="Queue"', html)
        self.assertNotIn('data-group-id="' + str(ensure_pipeline_system_groups()["queue"].pk) + '"', html)
        search_idx = html.find('id="table-search"')
        queued_idx = html.find('id="filter-queued-only"')
        vip_idx = html.find('id="filter-very-important-only"')
        chain_idx = html.find('id="filter-chain-only"')
        no_chain_idx = html.find('id="filter-no-chain-only"')
        sent_idx = html.find('id="filter-sent-message-only"')
        unsent_idx = html.find('id="filter-unsent-message-only"')
        self.assertNotEqual(search_idx, -1)
        self.assertNotEqual(queued_idx, -1)
        self.assertNotEqual(vip_idx, -1)
        self.assertNotEqual(chain_idx, -1)
        tag_idx = html.find('id="lead-tag-filter"')
        self.assertNotEqual(tag_idx, -1)
        self.assertLess(tag_idx, search_idx)
        self.assertLess(search_idx, queued_idx)
        self.assertLess(queued_idx, vip_idx)
        self.assertLess(vip_idx, chain_idx)
        self.assertLess(chain_idx, no_chain_idx)
        self.assertLess(no_chain_idx, sent_idx)
        self.assertLess(sent_idx, unsent_idx)
        self.assertIn('aria-label="Not sent"', html)
        self.assertIn('aria-label="Not chain"', html)
        self.assertIn('id="lead-tag-filter-manage"', html)
        self.assertIn('aria-label="Manage tags"', html)
        self.assertIn('id="table-search-clear"', html)
        self.assertIn('id="clinic-save-status"', html)
        self.assertIn("lead-status-toast", html)
        self.assertIn('id="lead-status-toast-stack"', html)
        self.assertIn('aria-label="Clear search and filters"', html)
        self.assertIn('id="lead-filter-tag-save"', html)
        self.assertIn('id="lead-filter-tags-list"', html)
        self.assertIn('aria-label="Save current search as tag"', html)
        self.assertIn("leads/js/mobile-pull-refresh.js", html)
        self.assertIn('id="select-all-clinics"', html)
        self.assertIn('data-lead-selection-count', html)
        self.assertNotIn('return to New', html)

    def test_dashboard_defaults_to_ready_tab(self):
        groups = ensure_pipeline_system_groups()
        Lead.objects.create(
            name="Only In New Clinic",
            address="1 New St",
            group=groups["uncategorized"],
        )
        Lead.objects.create(
            name="Only In Ready Clinic",
            address="2 Ready St",
            group=groups["ready"],
        )
        client = staff_client()
        html = client.get(reverse("dashboard")).content.decode()
        self.assertIn("Only In Ready Clinic", html)
        self.assertNotIn("Only In New Clinic", html)
        new_html = client.get(
            reverse("dashboard"), {"group_id": "uncategorized"}
        ).content.decode()
        self.assertIn("Only In New Clinic", new_html)
        self.assertNotIn("Only In Ready Clinic", new_html)

    def test_create_lead_group_api_is_gone(self):
        client = staff_client()
        url = reverse("create_lead_group")
        response = client.post(
            url,
            data=json.dumps({"name": "Johor"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 410)
        self.assertIn("tags", response.json()["detail"].lower())

    def test_custom_group_converts_to_tag_and_moves_leads_to_new(self):
        import importlib.util
        from pathlib import Path

        from django.apps import apps

        path = Path(__file__).resolve().parent / "migrations" / "0051_convert_custom_groups_to_tags.py"
        spec = importlib.util.spec_from_file_location("convert_custom_groups_to_tags", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        uncategorized = get_or_create_uncategorized_group()
        folder = LeadGroup.objects.create(name="Johor", sort_order=20)
        lead = Lead.objects.create(
            name="JB Clinic",
            address="1 Jalan Test",
            group=folder,
        )
        mod.convert_custom_groups_to_tags(apps, None)
        lead.refresh_from_db()
        self.assertEqual(lead.group_id, uncategorized.pk)
        self.assertTrue(lead.tags.filter(label="Johor").exists())
        self.assertFalse(LeadGroup.objects.filter(name="Johor").exists())

    def test_unknown_group_id_falls_back_to_new(self):
        from django.test import RequestFactory

        from leads.views import _leads_qs_for_tab

        uncategorized = get_or_create_uncategorized_group()
        lead = Lead.objects.create(
            name="Visible In New",
            address="9 Fall St",
            group=uncategorized,
        )
        user = get_user_model().objects.create_superuser(
            "fallbackadmin", "fallback@t.test", "pass"
        )
        request = RequestFactory().get("/")
        request.user = user
        qs = _leads_qs_for_tab(request, "999999", None)
        self.assertEqual(list(qs.values_list("name", flat=True)), ["Visible In New"])
        self.assertEqual(lead.pk, qs.get().pk)

    def test_new_tab_includes_pending_uncategorized(self):
        from django.test import RequestFactory

        from leads.views import _leads_qs_for_tab, apply_queued_outreach_filter

        groups = ensure_pipeline_system_groups()
        visible = Lead.objects.create(
            name="Idle In New",
            address="1 New St",
            group=groups["uncategorized"],
        )
        queued = Lead.objects.create(
            name="Queued Pending",
            address="2 New St",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        )
        ready = Lead.objects.create(
            name="Picked Ready",
            address="3 Ready St",
            group=groups["ready"],
        )
        ready_queued = Lead.objects.create(
            name="Ready Pending",
            address="5 Ready St",
            group=groups["ready"],
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        )
        trashed = Lead.objects.create(
            name="Hidden In Trash",
            address="4 Trash St",
            group=groups["trash"],
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        )
        user = get_user_model().objects.create_superuser(
            "newtabadmin", "newtab@t.test", "pass"
        )
        request = RequestFactory().get("/")
        request.user = user
        qs = _leads_qs_for_tab(request, "uncategorized", None)
        names = set(qs.values_list("name", flat=True))
        self.assertEqual(names, {"Idle In New", "Queued Pending"})
        self.assertNotIn(trashed.pk, qs.values_list("pk", flat=True))
        self.assertNotIn(ready.pk, qs.values_list("pk", flat=True))
        self.assertIn(visible.pk, qs.values_list("pk", flat=True))
        self.assertIn(queued.pk, qs.values_list("pk", flat=True))

        ready_qs = _leads_qs_for_tab(request, str(groups["ready"].pk), None)
        self.assertEqual(
            set(ready_qs.values_list("name", flat=True)),
            {"Picked Ready", "Ready Pending"},
        )

        queued_new = _leads_qs_for_tab(
            request, "uncategorized", None, queued_only=True
        )
        self.assertEqual(set(queued_new.values_list("name", flat=True)), {"Queued Pending"})
        queued_ready = _leads_qs_for_tab(
            request, str(groups["ready"].pk), None, queued_only=True
        )
        self.assertEqual(set(queued_ready.values_list("name", flat=True)), {"Ready Pending"})

        # Same condition the Queue tab used: exclude trash, pending/processing only.
        base = _leads_qs_for_tab(request, "uncategorized", None, queued_only=False)
        self.assertEqual(
            set(apply_queued_outreach_filter(base).values_list("name", flat=True)),
            {"Queued Pending"},
        )
        self.assertFalse(
            apply_queued_outreach_filter(
                _leads_qs_for_tab(request, str(groups["trash"].pk), None, queued_only=False)
            ).exists()
        )
        self.assertNotIn(ready_queued.pk, queued_new.values_list("pk", flat=True))

        queued_req = RequestFactory().get("/?queued=1")
        queued_req.user = user
        self.assertEqual(
            set(
                _leads_qs_for_tab(queued_req, "uncategorized", None).values_list(
                    "name", flat=True
                )
            ),
            {"Queued Pending"},
        )

    def test_new_lead_defaults_to_idle_not_pending(self):
        lead = Lead.objects.create(
            name="Gamma Clinic",
            address="3 Main St",
            group=get_or_create_uncategorized_group(),
        )
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.IDLE)

    def test_enqueue_sets_pending_without_moving_group(self):
        groups = ensure_pipeline_system_groups()
        uncategorized = groups["uncategorized"]
        lead = Lead.objects.create(
            name="Alpha Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=uncategorized,
            whatsapp_status=Lead.WhatsappStatus.IDLE,
            display_order=1,
        )
        updated = enqueue_leads_for_whatsapp([lead.pk])
        lead.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(lead.group_id, uncategorized.pk)
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.PENDING)
        self.assertEqual(lead.display_order, 1)

    def test_move_to_ready_picks_from_new(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Pick Me",
            address="5 Ready Rd",
            group=groups["uncategorized"],
        )
        updated = move_leads_to_ready([lead.pk])
        lead.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(lead.group_id, groups["ready"].pk)
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.IDLE)

    def test_bulk_move_ready_api_picks_from_new(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Bulk Pick",
            address="6 Ready Rd",
            group=groups["uncategorized"],
        )
        client = staff_client()
        response = client.post(
            reverse("leads_bulk_move_ready"),
            data=json.dumps({"ids": [lead.pk]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["updated"], 1)
        lead.refresh_from_db()
        self.assertEqual(lead.group_id, groups["ready"].pk)

    def test_bulk_mark_sent_api_sets_first_message_sent(self):
        from django.utils import timezone

        from leads.whatsapp_service import MANUAL_MARK_SENT_REMARK

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Manual Sent Clinic",
            address="7 Ready Rd",
            phone_number="+60119876543",
            phone_numbers=["+60119876543"],
            group=groups["ready"],
            whatsapp_status=Lead.WhatsappStatus.IDLE,
        )
        already = Lead.objects.create(
            name="Already Sent Clinic",
            address="8 Ready Rd",
            phone_number="+60119876544",
            phone_numbers=["+60119876544"],
            group=groups["ready"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=timezone.now(),
        )
        client = staff_client()
        response = client.post(
            reverse("leads_bulk_mark_sent"),
            data=json.dumps({"ids": [lead.pk, already.pk]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["updated"], 1)
        self.assertEqual(payload["ids"], [lead.pk])
        bottom_html = payload["bottom_actions"][str(lead.pk)]
        self.assertIn("lead-card-active-chat-btn", bottom_html)
        self.assertIn("chat/inbox", bottom_html)
        self.assertNotIn('title="Move to trash"', bottom_html)
        self.assertNotIn(str(already.pk), payload["bottom_actions"])
        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.SENT)
        self.assertIsNotNone(lead.whatsapp_sent_at)
        self.assertTrue(
            LeadConversationLog.objects.filter(
                lead=lead, remarks=MANUAL_MARK_SENT_REMARK
            ).exists()
        )
        already.refresh_from_db()
        self.assertEqual(already.whatsapp_status, Lead.WhatsappStatus.SENT)

    def test_bulk_mark_sent_new_folder_keeps_permanent_delete(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="New Folder Manual Sent",
            address="9 New Rd",
            phone_number="+60119876545",
            phone_numbers=["+60119876545"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.IDLE,
        )
        client = staff_client()
        response = client.post(
            reverse("leads_bulk_mark_sent"),
            data=json.dumps({"ids": [lead.pk], "group_id": "uncategorized"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        html = response.json()["bottom_actions"][str(lead.pk)]
        self.assertIn("lead-card-active-chat-btn", html)
        self.assertNotIn('title="Move to trash"', html)
        self.assertIn("Permanently delete", html)

    def test_dequeue_reverts_pending_lead_to_idle(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Delta Clinic",
            address="4 Main St",
            phone_number="+60111222333",
            phone_numbers=["+60111222333"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        )
        client = staff_client(enforce_csrf_checks=True)
        client.get("/")
        response = client.post(
            f"/leads/ajax/lead/{lead.pk}/dequeue/",
            HTTP_HX_REQUEST="true",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.IDLE)
        self.assertIn("lead-join-queue-btn", response.content.decode())
        self.assertIn("Assign to a WhatsApp batch", response.content.decode())
        self.assertNotIn(f"/leads/ajax/lead/{lead.pk}/enqueue/", response.content.decode())

    def test_ready_join_queue_button_targets_choose_batch_modal(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Ready Batch Clinic",
            address="8 Batch Rd",
            phone_number="+60118889900",
            phone_numbers=["+60118889900"],
            group=groups["ready"],
            whatsapp_status=Lead.WhatsappStatus.IDLE,
        )
        client = staff_client()
        response = client.get(
            reverse("get_leads_table"), {"group_id": str(groups["ready"].pk)}
        )
        self.assertEqual(response.status_code, 200)
        html = response.json()["grid_html"]
        self.assertIn("lead-join-queue-btn", html)
        self.assertIn(f'data-lead-id="{lead.pk}"', html)
        self.assertIn("Assign to a WhatsApp batch", html)
        self.assertNotIn(f"/leads/ajax/lead/{lead.pk}/enqueue/", html)
        self.assertIn('id="choose-batch-dialog"', client.get(reverse("dashboard")).content.decode())

    def test_leaving_queue_folder_returns_lead_to_idle(self):
        groups = ensure_pipeline_system_groups()
        queue = groups["queue"]
        uncategorized = groups["uncategorized"]
        lead = Lead.objects.create(
            name="Beta Clinic",
            address="2 Main St",
            group=queue,
            phone_number="+60198765432",
            phone_numbers=["+60198765432"],
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        )
        apply_group_assignment_side_effects([lead], uncategorized)
        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.IDLE)

    def test_enqueue_after_sent_allows_re_promotion(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Sent Clinic",
            address="5 Main St",
            phone_number="+60122334455",
            phone_numbers=["+60122334455"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        updated = enqueue_leads_for_whatsapp([lead.pk])
        lead.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.PENDING)


class LeadDisplayPipelineTests(TestCase):
    def test_dispatched_when_sent_without_client_reply(self):
        lead = Lead.objects.create(
            name="Outbound Only",
            address="1 Road",
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        self.assertTrue(lead_whatsapp_dispatched(lead))
        self.assertFalse(lead_whatsapp_active_chat(lead))

    def test_active_batch_ignores_pending_status_without_assignment(self):
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        pending_only = Lead.objects.create(
            name="Pending No Batch",
            address="2 Road",
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        )
        self.assertFalse(lead_in_active_whatsapp_batch(pending_only))

        batched = Lead.objects.create(
            name="Idle In Batch",
            address="3 Road",
            whatsapp_status=Lead.WhatsappStatus.IDLE,
        )
        batch = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        batched.whatsapp_batches.add(batch)
        self.assertTrue(lead_in_active_whatsapp_batch(batched))

    def test_dispatched_persists_when_re_enqueued(self):
        from django.utils import timezone

        lead = Lead.objects.create(
            name="Re-promo Clinic",
            address="4 Road",
            whatsapp_status=Lead.WhatsappStatus.PENDING,
            whatsapp_sent_at=timezone.now(),
        )
        self.assertTrue(lead_whatsapp_dispatched(lead))
        self.assertFalse(lead_whatsapp_active_chat(lead))

    def test_active_chat_requires_latest_inbound_message(self):
        from django.utils import timezone

        lead = Lead.objects.create(
            name="Replied Clinic",
            address="2 Road",
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=timezone.now(),
        )
        record_outbound_chat_message(lead, body="Hello from CRM")
        record_inbound_chat_message(lead, body="Yes please")
        annotated = _annotate_lead_dashboard_qs(Lead.objects.all()).get(pk=lead.pk)
        self.assertTrue(lead_whatsapp_active_chat(annotated))

    def test_active_chat_cleared_after_staff_reply(self):
        from django.utils import timezone

        lead = Lead.objects.create(
            name="Handled Clinic",
            address="6 Road",
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=timezone.now(),
        )
        record_outbound_chat_message(lead, body="Hello from CRM")
        record_inbound_chat_message(lead, body="Interested")
        record_outbound_chat_message(lead, body="Great, let's talk")
        annotated = _annotate_lead_dashboard_qs(Lead.objects.all()).get(pk=lead.pk)
        self.assertFalse(lead_whatsapp_active_chat(annotated))

    def test_outbound_only_thread_has_no_active_chat_pulse(self):
        from django.utils import timezone

        lead = Lead.objects.create(
            name="Outbound Thread",
            address="7 Road",
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=timezone.now(),
        )
        record_outbound_chat_message(lead, body="Hello from CRM")
        annotated = _annotate_lead_dashboard_qs(Lead.objects.all()).get(pk=lead.pk)
        self.assertFalse(lead_whatsapp_active_chat(annotated))

    def test_whatsapp_open_urls_prefer_business_app_scheme(self):
        self.assertEqual(whatsapp_e164_digits("012-345 6789"), "60123456789")
        self.assertEqual(whatsapp_e164_digits("+60123456789"), "60123456789")
        self.assertEqual(whatsapp_me_url("0123456789"), "https://wa.me/60123456789")
        self.assertEqual(
            whatsapp_business_open_url("0123456789"),
            "whatsapp://send?phone=60123456789",
        )
        self.assertEqual(whatsapp_business_open_url(""), "")

    def test_human_log_without_client_reply_is_not_active_chat(self):
        lead = Lead.objects.create(
            name="Staff Note",
            address="3 Road",
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        LeadConversationLog.objects.create(
            lead=lead,
            conversation_date=date.today(),
            remarks="[WhatsApp · staff] Follow up tomorrow",
        )
        annotated = Lead.objects.annotate(
            has_client_conversation_log=Exists(
                LeadConversationLog.objects.filter(
                    lead_id=OuterRef("pk"),
                    remarks__icontains="[WhatsApp · client]",
                )
            ),
            has_inbound_chat_message=Exists(
                ChatMessage.objects.filter(lead_id=OuterRef("pk"), is_outbound=False)
            ),
            has_human_conversation_log=Exists(
                LeadConversationLog.objects.filter(lead_id=OuterRef("pk")).exclude(
                    remarks__icontains="Touchpoint Automator"
                )
            ),
        ).get(pk=lead.pk)
        self.assertFalse(lead_whatsapp_active_chat(annotated))

    @override_settings(WHATSAPP_CAMPAIGN_TIMEZONE="Asia/Kuala_Lumpur")
    def test_campaign_datetime_filter_uses_local_timezone(self):
        from datetime import datetime, timezone as dt_timezone

        from leads.templatetags.clinic_display import campaign_datetime

        utc = datetime(2026, 7, 1, 2, 41, tzinfo=dt_timezone.utc)
        self.assertEqual(campaign_datetime(utc), "Jul 1, 2026 · 10:41 AM")

    def test_google_maps_url_uses_name_instead_of_coordinate_source(self):
        lead = Lead.objects.create(
            name="U.n.i Klinik Iskandar Puteri",
            address="97 Jalan Suria 2, Iskandar Puteri, Johor",
            source_url="https://www.google.com/maps/search/?api=1&query=1.453703,103.599190",
        )
        url = lead_google_maps_url(lead)
        self.assertIn("query=", url)
        self.assertNotIn("1.453703", url)
        self.assertIn("U.n.i", url)
        self.assertIn("Iskandar", url)

    def test_normalize_manual_phone_malaysian_landlines(self):
        self.assertEqual(normalize_manual_phone("07-585 4964"), "+6075854964")
        self.assertEqual(normalize_manual_phone("03-1234 5678"), "+60312345678")
        self.assertEqual(normalize_manual_phone("6075854964"), "+6075854964")
        self.assertEqual(normalize_manual_phone("+6075854964"), "+6075854964")

    def test_normalize_manual_phone_repairs_double_country_prefix(self):
        self.assertEqual(normalize_manual_phone("+606075854964"), "+6075854964")
        self.assertEqual(normalize_manual_phone("606075854964"), "+6075854964")

    def test_lead_phone_list_repairs_stored_double_prefix(self):
        lead = Lead.objects.create(
            name="Johor Clinic",
            address="1 Road",
            phone_number="+606075854964",
            phone_numbers=["+606075854964"],
        )
        self.assertEqual(lead_phone_list(lead), ["+6075854964"])


class ActiveChatTabTests(TestCase):
    def test_active_chat_tab_lists_awaiting_leads_without_moving_group(self):
        from django.utils import timezone

        groups = ensure_pipeline_system_groups()
        quality = LeadGroup.objects.create(name="Quality Leads", sort_order=20)
        lead = Lead.objects.create(
            name="Tab Clinic",
            address="8 Road",
            phone_number="+60199887766",
            phone_numbers=["+60199887766"],
            group=quality,
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=timezone.now(),
        )
        record_outbound_chat_message(lead, body="Hello")
        record_inbound_chat_message(lead, body="Please call me")

        from django.test import RequestFactory

        user = get_user_model().objects.create_superuser("tabuser", "tab@t.test", "x")
        req = RequestFactory().get("/")
        req.user = user
        active_chat_qs = _leads_qs_for_tab(req, str(groups["whatsapp_chats"].pk), None)
        self.assertEqual(list(active_chat_qs.values_list("pk", flat=True)), [lead.pk])
        lead.refresh_from_db()
        self.assertEqual(lead.group_id, quality.pk)


class WhatsAppScriptTemplateTests(TestCase):
    def test_render_script_template_substitutes_placeholders(self):
        lead = Lead.objects.create(
            name="Glow Clinic",
            address="12 Jalan Ampang",
            search_city="Kuala Lumpur",
        )
        text = render_script_template(
            "Hello {{ name }} from {{ area }}!",
            lead,
        )
        self.assertEqual(text, "Hello Glow Clinic from Kuala Lumpur!")

    def test_compose_outbound_message_uses_group_template(self):
        aesthetic = LeadGroup.objects.create(name="Aesthetic", sort_order=10)
        WhatsAppScriptTemplate.objects.create(
            group_name="Aesthetic",
            template_text="Hi {{ name }}, welcome to {{ area }}.",
        )
        lead = Lead.objects.create(
            name="Skin Lab",
            address="1 Main St",
            search_city="Petaling Jaya",
            group=aesthetic,
        )
        body = compose_outbound_message(lead)
        self.assertEqual(body, "Hi Skin Lab, welcome to Petaling Jaya.")

    def test_compose_outbound_message_falls_back_to_default(self):
        lead = Lead.objects.create(
            name="Unknown Shop",
            address="9 Road",
            search_city="Johor Bahru",
            group=ensure_pipeline_system_groups()["uncategorized"],
        )
        body = compose_outbound_message(lead)
        self.assertIn("Unknown Shop", body)
        self.assertIn("Johor Bahru", body)


class FreeTextTemplateTests(TestCase):
    def test_compose_free_text_templates_substitutes_placeholders(self):
        config = WhatsAppConfig.load()
        config.free_text_templates = [
            {"label": "Thanks", "text": "Hi {{ name }}, thanks from {{ area }}!"},
            {"label": "Follow up", "text": "Checking in, {{ name }}."},
        ]
        config.save(update_fields=["free_text_templates"])
        lead = Lead.objects.create(
            name="Avea Clinic",
            address="1 Main St",
            search_city="Petaling Jaya",
        )
        templates = compose_free_text_templates_for_lead(lead)
        self.assertEqual(len(templates), 2)
        self.assertEqual(templates[0]["label"], "Thanks")
        self.assertEqual(templates[0]["text"], "Hi Avea Clinic, thanks from Petaling Jaya!")
        self.assertEqual(templates[1]["text"], "Checking in, Avea Clinic.")

    def test_active_chat_shows_only_top_three_templates(self):
        config = WhatsAppConfig.load()
        config.free_text_templates = [
            {"label": "One", "text": "First {{ name }}"},
            {"label": "Two", "text": "Second {{ name }}"},
            {"label": "Three", "text": "Third {{ name }}"},
            {"label": "Four", "text": "Fourth {{ name }}"},
            {"label": "Five", "text": "Fifth {{ name }}"},
        ]
        config.save(update_fields=["free_text_templates"])
        lead = Lead.objects.create(name="Clinic", address="1 St", search_city="KL")
        templates = compose_free_text_templates_for_lead(lead)
        self.assertEqual(len(templates), 3)
        self.assertEqual(templates[0]["label"], "One")
        self.assertEqual(templates[2]["label"], "Three")
        self.assertEqual(templates[2]["text"], "Third Clinic")

    def test_compose_free_text_template_uses_first_slot(self):
        lead = Lead.objects.create(name="Clinic", address="1 St", search_city="KL")
        templates = compose_free_text_templates_for_lead(lead)
        self.assertEqual(compose_free_text_template(lead), templates[0]["text"])

    def test_free_text_template_page_loads(self):
        client = staff_client()
        response = client.get(reverse("free_text_template"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Free text templates", response.content)
        self.assertIn(b"Add template", response.content)
        self.assertIn(b"thank you for your reply", response.content)

    def test_save_free_text_template_persists_order(self):
        client = staff_client()
        response = client.post(
            reverse("save_free_text_template"),
            data={
                "template_label": ["Quick thanks", "Follow up", "Archive"],
                "template_text": [
                    "Custom reply for {{ name }}.",
                    "Hi {{ name }}, following up.",
                    "Stored but not in top 3 for {{ name }}.",
                ],
            },
        )
        self.assertEqual(response.status_code, 302)
        config = WhatsAppConfig.load()
        self.assertEqual(len(config.free_text_templates), 3)
        self.assertEqual(config.free_text_templates[0]["label"], "Quick thanks")
        self.assertEqual(config.free_text_templates[2]["label"], "Archive")

    def test_chat_inbox_shows_top_three_template_buttons_only(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Chat Template Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            search_city="Shah Alam",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        config = WhatsAppConfig.load()
        config.free_text_templates = [
            {"label": "Hello", "text": "Hello {{ name }} in {{ area }}"},
            {"label": "Thanks", "text": "Thanks {{ name }}"},
            {"label": "Follow up", "text": "Follow up with {{ name }}"},
            {"label": "Hidden", "text": "Should not appear {{ name }}"},
        ]
        config.save(update_fields=["free_text_templates"])
        client = staff_client()
        response = client.get(reverse("chat_inbox", kwargs={"pk": lead.pk}))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('data-template-index="'), 3)
        self.assertIn("Hello Chat Template Clinic in Shah Alam", html)
        self.assertIn("Thanks Chat Template Clinic", html)
        self.assertIn("Follow up with Chat Template Clinic", html)
        self.assertNotIn("Should not appear Chat Template Clinic", html)
        self.assertNotIn("manage in sidebar link", html)


class WhatsAppWebhookTests(TestCase):
    def _meta_inbound_payload(self, **message_overrides):
        message = {
            "from": "60123456789",
            "id": "wamid.MSG123",
            "timestamp": "1709550600",
            "type": "text",
            "text": {"body": "Yes, interested"},
        }
        message.update(message_overrides)
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "messages": [message],
                            },
                        }
                    ],
                }
            ],
        }

    def test_parse_meta_cloud_webhook_extracts_client_text(self):
        parsed = parse_meta_cloud_webhook(self._meta_inbound_payload())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].remote_phone, "+60123456789")
        self.assertEqual(parsed[0].text_body, "Yes, interested")
        self.assertFalse(parsed[0].from_me)

    def _meta_echo_payload(self, **echo_overrides):
        echo = {
            "from": "60126336429",
            "to": "60123456789",
            "id": "wamid.ECHO123",
            "timestamp": "1709550700",
            "type": "text",
            "text": {"body": "Thanks, we can help with that."},
        }
        echo.update(echo_overrides)
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID",
                    "changes": [
                        {
                            "field": "smb_message_echoes",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "60126336429",
                                    "phone_number_id": "999888777",
                                },
                                "message_echoes": [echo],
                            },
                        }
                    ],
                }
            ],
        }

    def test_parse_meta_cloud_webhook_extracts_smb_message_echoes(self):
        parsed = parse_meta_cloud_webhook(self._meta_echo_payload())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].remote_phone, "+60123456789")
        self.assertEqual(parsed[0].text_body, "Thanks, we can help with that.")
        self.assertTrue(parsed[0].from_me)

    def test_webhook_syncs_smb_message_echo_to_outbound_chat(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Echo Clinic",
            address="3 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        client = Client()
        response = client.post(
            "/webhook/whatsapp/",
            data=json.dumps(self._meta_echo_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], 1)

        chat = ChatMessage.objects.get(lead=lead, is_outbound=True)
        self.assertEqual(chat.body, "Thanks, we can help with that.")
        self.assertEqual(chat.meta_message_id, "wamid.ECHO123")
        log = LeadConversationLog.objects.get(lead=lead)
        self.assertIn("[WhatsApp · agent]", log.remarks)

    def test_webhook_syncs_log_and_keeps_lead_in_origin_group(self):
        groups = ensure_pipeline_system_groups()
        quality = LeadGroup.objects.create(name="Quality Leads", sort_order=20)
        lead = Lead.objects.create(
            name="Webhook Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=quality,
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        client = Client()
        response = client.post(
            "/webhook/whatsapp/",
            data=json.dumps(self._meta_inbound_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(response.json()["synced"], 1)

        lead.refresh_from_db()
        self.assertEqual(lead.group_id, quality.pk)
        log = LeadConversationLog.objects.get(lead=lead)
        self.assertIn("[WhatsApp · client]", log.remarks)
        self.assertIn("Yes, interested", log.remarks)
        chat = ChatMessage.objects.get(lead=lead, is_outbound=False)
        self.assertEqual(chat.body, "Yes, interested")
        self.assertEqual(chat.meta_message_id, "wamid.MSG123")

    def test_webhook_verify_get_returns_challenge(self):
        client = Client()
        with override_settings(WHATSAPP_WEBHOOK_VERIFY_TOKEN="verify-me"):
            response = client.get(
                "/webhook/whatsapp/",
                {
                    "hub.mode": "subscribe",
                    "hub.verify_token": "verify-me",
                    "hub.challenge": "1234567890",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "1234567890")

    @override_settings(WHATSAPP_WEBHOOK_VERIFY_TOKEN="CLINIC_CRM_WEBHOOK_73R469Mf")
    def test_webhook_receiver_verify_get_returns_challenge(self):
        client = Client()
        response = client.get(
            "/whatsapp/webhook/",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "CLINIC_CRM_WEBHOOK_73R469Mf",
                "hub.challenge": "99887766",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "99887766")

    @override_settings(WHATSAPP_APP_SECRET="meta-app-secret")
    def test_webhook_rejects_unsigned_from_public_ip(self):
        client = Client()
        response = client.post(
            "/webhook/whatsapp/",
            data=json.dumps(self._meta_inbound_payload()),
            content_type="application/json",
            REMOTE_ADDR="8.8.8.8",
        )
        self.assertEqual(response.status_code, 403)

    def test_webhook_accepts_meta_forwarded_ip_when_peer_is_local(self):
        """ngrok forwards Meta's public IP in X-Forwarded-For; auth uses REMOTE_ADDR only."""
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Tunnel Clinic",
            address="2 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        client = Client()
        response = client.post(
            "/whatsapp/webhook/",
            data=json.dumps(self._meta_inbound_payload()),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="157.240.0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], 1)
        self.assertTrue(
            ChatMessage.objects.filter(lead=lead, is_outbound=False).exists()
        )


class YCloudWebhookTests(TestCase):
    def _ycloud_inbound_payload(self, **overrides):
        inbound = {
            "id": "inb_123",
            "wamid": "wamid.YCLOUD_INBOUND",
            "from": "+60123456789",
            "to": "+60126336529",
            "type": "text",
            "text": {"body": "Hello from YCloud"},
            "sendTime": "2026-06-14T10:00:00.000Z",
        }
        inbound.update(overrides)
        return {
            "id": "evt_inbound_1",
            "type": "whatsapp.inbound_message.received",
            "apiVersion": "v2",
            "createTime": "2026-06-14T10:00:01.000Z",
            "whatsappInboundMessage": inbound,
        }

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336529")
    def test_parse_ycloud_inbound_message(self):
        from leads.whatsapp_webhook import parse_ycloud_webhook

        parsed, failures = parse_ycloud_webhook(self._ycloud_inbound_payload())
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(failures), 0)
        self.assertEqual(parsed[0].remote_phone, "+60123456789")
        self.assertEqual(parsed[0].text_body, "Hello from YCloud")
        self.assertFalse(parsed[0].from_me)

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_parse_ycloud_mobile_echo(self):
        from leads.whatsapp_webhook import parse_ycloud_webhook

        payload = {
            "id": "evt_out_1",
            "type": "whatsapp.message.updated",
            "apiVersion": "v2",
            "createTime": "2026-06-14T10:01:00.000Z",
            "whatsappMessage": {
                "id": "msg_1",
                "wamid": "wamid.YCLOUD_ECHO",
                "from": "+60126336429",
                "to": "+60123456789",
                "type": "text",
                "status": "sent",
                "text": {"body": "Reply from mobile app"},
                "sendTime": "2026-06-14T10:01:00.000Z",
            },
        }
        parsed, failures = parse_ycloud_webhook(payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(failures), 0)
        self.assertTrue(parsed[0].from_me)
        self.assertEqual(parsed[0].text_body, "Reply from mobile app")

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_parse_ycloud_smb_message_echoes(self):
        from leads.whatsapp_webhook import parse_ycloud_webhook

        payload = {
            "id": "evt_smb_echo_1",
            "type": "whatsapp.smb.message.echoes",
            "apiVersion": "v2",
            "createTime": "2026-06-14T10:02:00.000Z",
            "whatsappMessage": {
                "id": "msg_smb_1",
                "wamid": "wamid.YCLOUD_SMB_ECHO",
                "from": "+60126336429",
                "to": "+60123456789",
                "type": "text",
                "status": "sent",
                "text": {"body": "Reply from Coex phone app"},
                "sendTime": "2026-06-14T10:02:00.000Z",
            },
        }
        parsed, failures = parse_ycloud_webhook(payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(failures), 0)
        self.assertTrue(parsed[0].from_me)
        self.assertEqual(parsed[0].remote_phone, "+60123456789")
        self.assertEqual(parsed[0].text_body, "Reply from Coex phone app")

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_ycloud_template_webhook_upserts_outbound_chat(self):
        from django.utils import timezone

        from leads.chat_messages import upsert_outbound_chat_message
        from leads.whatsapp_webhook import parse_ycloud_webhook

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Template Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        WhatsAppConfig = __import__("leads.models", fromlist=["WhatsAppConfig"]).WhatsAppConfig
        config = WhatsAppConfig.load()
        config.meta_message_templates = [
            {
                "name": "say_hi",
                "status": "APPROVED",
                "language": "en_US",
                "body": "Hi- are you open today?",
            },
        ]
        config.save(update_fields=["meta_message_templates"])

        send_time = timezone.now() - timezone.timedelta(minutes=2)
        upsert_outbound_chat_message(
            lead,
            template_name="say_hi",
            body="wrong draft copy",
            meta_message_id="wamid.TEMPLATE123",
            created_at=send_time,
        )

        payload = {
            "id": "evt_tpl_1",
            "type": "whatsapp.message.updated",
            "apiVersion": "v2",
            "createTime": "2026-06-30T11:31:00.000Z",
            "whatsappMessage": {
                "id": "msg_tpl_1",
                "wamid": "wamid.TEMPLATE123",
                "from": "+60126336429",
                "to": "+60123456789",
                "type": "template",
                "status": "sent",
                "template": {"name": "say_hi", "language": {"code": "en_US"}},
                "text": {"body": "Hi- are you open today? May I know your business hours?"},
                "sendTime": "2026-06-30T11:31:00.000Z",
            },
        }
        parsed, failures = parse_ycloud_webhook(payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(failures), 0)
        self.assertEqual(parsed[0].template_name, "say_hi")
        self.assertIn("business hours", parsed[0].text_body)

        client = Client()
        response = client.post(
            "/whatsapp/webhook/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        chat = ChatMessage.objects.get(lead=lead, is_outbound=True)
        self.assertEqual(chat.template_name, "say_hi")
        self.assertIn("business hours", chat.body)
        self.assertNotEqual(chat.body, "wrong draft copy")
        self.assertEqual(chat.meta_message_id, "wamid.TEMPLATE123")

    def test_lead_already_received_template(self):
        from leads.chat_messages import lead_already_received_template

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Dup Template Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            group=groups["uncategorized"],
        )
        self.assertFalse(lead_already_received_template(lead, "say_hi"))
        ChatMessage.objects.create(
            lead=lead,
            body="Hi~",
            is_outbound=True,
            template_name="say_hi",
        )
        self.assertTrue(lead_already_received_template(lead, "say_hi"))
        self.assertFalse(lead_already_received_template(lead, "say_hi_en"))

    def test_mark_sent_sinks_display_order_on_first_send(self):
        from leads.whatsapp_service import mark_sent

        groups = ensure_pipeline_system_groups()
        group = LeadGroup.objects.create(name="Sink Folder", sort_order=60)
        top = Lead.objects.create(
            name="Top Lead",
            address="1 Main St",
            phone_number="+60111111111",
            group=group,
            display_order=1,
        )
        lead = Lead.objects.create(
            name="Sink Lead",
            address="2 Main St",
            phone_number="+60222222222",
            group=group,
            display_order=2,
        )
        mark_sent(lead, "+60126336429", template_name="say_hi")
        lead.refresh_from_db()
        top.refresh_from_db()
        self.assertGreater(lead.display_order, top.display_order)

    def test_mark_first_outbound_sent_sets_status_without_template_row(self):
        from django.utils import timezone

        from leads.whatsapp_service import OFFICIAL_API_MARKER, mark_first_outbound_sent

        groups = ensure_pipeline_system_groups()
        group = LeadGroup.objects.create(name="App Send Folder", sort_order=61)
        top = Lead.objects.create(
            name="Top App Lead",
            address="1 Main St",
            phone_number="+60111111112",
            group=group,
            display_order=1,
        )
        lead = Lead.objects.create(
            name="App Send Lead",
            address="2 Main St",
            phone_number="+60222222223",
            group=group,
            display_order=2,
            whatsapp_status=Lead.WhatsappStatus.PENDING,
            whatsapp_last_error="queued",
        )
        sent_at = timezone.now()
        self.assertTrue(
            mark_first_outbound_sent(lead, "+60126336429", sent_at=sent_at)
        )
        lead.refresh_from_db()
        top.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.SENT)
        self.assertEqual(lead.whatsapp_sent_at, sent_at)
        self.assertEqual(lead.whatsapp_instance_id, "+60126336429")
        self.assertEqual(lead.whatsapp_last_error, "")
        self.assertGreater(lead.display_order, top.display_order)
        self.assertFalse(ChatMessage.objects.filter(lead=lead).exists())
        self.assertFalse(
            LeadConversationLog.objects.filter(
                lead=lead, remarks__icontains=OFFICIAL_API_MARKER
            ).exists()
        )
        self.assertFalse(
            mark_first_outbound_sent(lead, "+60126336429", sent_at=timezone.now())
        )
        unchanged = lead.whatsapp_sent_at
        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_sent_at, unchanged)

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_parse_ycloud_delivery_failure(self):
        from leads.whatsapp_webhook import DELIVERY_FAILED_MARKER, parse_ycloud_webhook

        payload = {
            "id": "evt_fail_1",
            "type": "whatsapp.message.updated",
            "whatsappMessage": {
                "id": "msg_fail_1",
                "wamid": "wamid.FAILED123",
                "from": "+60126336429",
                "to": "+60198765030",
                "type": "template",
                "status": "failed",
                "errorCode": "131026",
                "errorMessage": "Message undeliverable",
                "template": {"name": "say_hi", "language": {"code": "en_US"}},
            },
        }
        parsed, failures = parse_ycloud_webhook(payload)
        self.assertEqual(parsed, [])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error_message, "Message undeliverable")

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Fail Clinic",
            address="1 Main St",
            phone_number="+60198765030",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        client = Client()
        response = client.post(
            "/whatsapp/webhook/",
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["delivery_failures"], 1)
        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.FAILED)
        self.assertTrue(
            LeadConversationLog.objects.filter(
                lead=lead,
                remarks__contains=DELIVERY_FAILED_MARKER,
            ).exists()
        )

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_upsert_merges_api_send_and_webhook_ids_for_same_template(self):
        from django.utils import timezone

        from leads.chat_messages import chat_messages_for_lead, upsert_outbound_chat_message
        from leads.models import WhatsAppConfig

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Merge Template Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        preview = "Hi~ are you open today? may I know your business hours?"
        config = WhatsAppConfig.load()
        config.outbound_template_name = "say_hi"
        config.meta_message_templates = [
            {
                "name": "say_hi",
                "status": "APPROVED",
                "language": "en_US",
                "body": preview,
            },
        ]
        config.save(update_fields=["outbound_template_name", "meta_message_templates"])
        send_time = timezone.now() - timezone.timedelta(minutes=7)
        upsert_outbound_chat_message(
            lead,
            template_name="say_hi",
            body=preview,
            meta_message_id="ycloud_msg_1",
            created_at=send_time,
        )
        upsert_outbound_chat_message(
            lead,
            template_name="say_hi",
            body=preview,
            meta_message_id="wamid.TEMPLATE123",
            created_at=timezone.now(),
        )

        messages = chat_messages_for_lead(lead)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].template_name, "say_hi")
        self.assertEqual(messages[0].meta_message_id, "wamid.TEMPLATE123")
        self.assertEqual(messages[0].body, preview)

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_upsert_merges_free_text_api_and_webhook_ids(self):
        from django.utils import timezone

        from leads.chat_messages import chat_messages_for_lead, upsert_outbound_chat_message

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Merge Free Text Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        body = "We open at 9am tomorrow."
        send_time = timezone.now() - timezone.timedelta(minutes=3)
        upsert_outbound_chat_message(
            lead,
            body=body,
            meta_message_id="ycloud_text_1",
            template_name="",
            created_at=send_time,
        )
        upsert_outbound_chat_message(
            lead,
            body=body,
            meta_message_id="wamid.FREE_TEXT_ECHO",
            template_name="",
            created_at=timezone.now(),
        )

        messages = chat_messages_for_lead(lead)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].body, body)
        self.assertEqual(messages[0].template_name, "")
        self.assertEqual(messages[0].meta_message_id, "wamid.FREE_TEXT_ECHO")

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_ycloud_smb_echo_webhook_post_syncs_outbound(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Coex Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        payload = {
            "id": "evt_smb_echo_2",
            "type": "whatsapp.smb.message.echoes",
            "apiVersion": "v2",
            "createTime": "2026-06-14T10:02:00.000Z",
            "whatsappMessage": {
                "id": "msg_smb_2",
                "wamid": "wamid.YCLOUD_SMB_ECHO_POST",
                "from": "+60126336429",
                "to": "+60123456789",
                "type": "text",
                "text": {"body": "Coex phone reply logged"},
                "sendTime": "2026-06-14T10:02:00.000Z",
            },
        }
        client = Client()
        response = client.post(
            "/whatsapp/webhook/",
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], 1)
        chat = ChatMessage.objects.get(lead=lead, is_outbound=True)
        self.assertEqual(chat.body, "Coex phone reply logged")
        self.assertEqual(chat.template_name, "")

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_ycloud_smb_echo_marks_first_message_sent(self):
        from leads.whatsapp_service import OFFICIAL_API_MARKER

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="App First Send Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.IDLE,
        )
        payload = {
            "id": "evt_smb_echo_first",
            "type": "whatsapp.smb.message.echoes",
            "apiVersion": "v2",
            "createTime": "2026-06-14T10:02:00.000Z",
            "whatsappMessage": {
                "id": "msg_smb_first",
                "wamid": "wamid.YCLOUD_SMB_FIRST",
                "from": "+60126336429",
                "to": "+60123456789",
                "type": "text",
                "text": {"body": "Hi, are you open today?"},
                "sendTime": "2026-06-14T10:02:00.000Z",
            },
        }
        client = Client()
        response = client.post(
            "/whatsapp/webhook/",
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], 1)

        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.SENT)
        self.assertIsNotNone(lead.whatsapp_sent_at)
        self.assertEqual(lead.whatsapp_instance_id, "+60126336429")
        chat = ChatMessage.objects.get(lead=lead, is_outbound=True)
        self.assertEqual(chat.body, "Hi, are you open today?")
        self.assertEqual(chat.template_name, "")
        self.assertFalse(
            LeadConversationLog.objects.filter(
                lead=lead, remarks__icontains=OFFICIAL_API_MARKER
            ).exists()
        )
        agent_log = LeadConversationLog.objects.get(lead=lead)
        self.assertIn("[WhatsApp · agent]", agent_log.remarks)

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_ycloud_smb_echo_does_not_reset_existing_first_send(self):
        from django.utils import timezone

        groups = ensure_pipeline_system_groups()
        first_send = timezone.now()
        lead = Lead.objects.create(
            name="Already Sent Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=first_send,
            whatsapp_instance_id="prior-id",
        )
        payload = {
            "id": "evt_smb_echo_followup",
            "type": "whatsapp.smb.message.echoes",
            "apiVersion": "v2",
            "createTime": "2026-06-14T11:02:00.000Z",
            "whatsappMessage": {
                "id": "msg_smb_followup",
                "wamid": "wamid.YCLOUD_SMB_FOLLOWUP",
                "from": "+60126336429",
                "to": "+60123456789",
                "type": "text",
                "text": {"body": "Just checking in"},
                "sendTime": "2026-06-14T11:02:00.000Z",
            },
        }
        client = Client()
        response = client.post(
            "/whatsapp/webhook/",
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.SENT)
        self.assertEqual(lead.whatsapp_sent_at, first_send)
        self.assertEqual(lead.whatsapp_instance_id, "prior-id")

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336529")
    def test_ycloud_inbound_marks_first_message_sent(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Inbound Idle Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.IDLE,
        )
        client = Client()
        response = client.post(
            "/whatsapp/webhook/",
            data=json.dumps(self._ycloud_inbound_payload()),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], 1)
        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.SENT)
        self.assertIsNotNone(lead.whatsapp_sent_at)

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_business_app_free_text_not_labeled_as_template(self):
        from leads.chat_messages import chat_messages_for_lead, upsert_outbound_chat_message

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Free Text Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        upsert_outbound_chat_message(
            lead,
            body="Thanks, we open at 9am tomorrow.",
            meta_message_id="wamid.FREE_TEXT_ECHO",
            template_name="",
        )
        messages = chat_messages_for_lead(lead)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].body, "Thanks, we open at 9am tomorrow.")
        self.assertEqual(messages[0].template_name, "")

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_sync_logs_do_not_retag_free_text_as_template(self):
        from django.utils import timezone

        from leads.chat_messages import chat_messages_for_lead, record_outbound_chat_message
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import OFFICIAL_API_MARKER

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Retag Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        config = WhatsAppConfig.load()
        config.outbound_template_name = "say_hi"
        config.meta_message_templates = [
            {
                "name": "say_hi",
                "status": "APPROVED",
                "language": "en_US",
                "body": "Hi~ are you open today? may I know your business hours?",
            },
        ]
        config.save(update_fields=["outbound_template_name", "meta_message_templates"])

        record_outbound_chat_message(
            lead,
            template_name="say_hi",
            body="Hi~ are you open today? may I know your business hours?",
        )
        record_outbound_chat_message(
            lead,
            template_name="",
            body="We open at 9am — reply from Business app",
        )
        LeadConversationLog.objects.create(
            lead=lead,
            conversation_date=timezone.now().date(),
            remarks=f"{OFFICIAL_API_MARKER} Template queued by YCloud for 6012XXXX789",
        )

        messages = chat_messages_for_lead(lead)
        free_text = [m for m in messages if "9am" in m.body]
        self.assertEqual(len(free_text), 1)
        self.assertEqual(free_text[0].template_name, "")

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_chat_messages_for_lead_imports_agent_log_and_relabels_you(self):
        from django.utils import timezone

        from leads.chat_messages import (
            chat_messages_for_lead,
            outbound_message_is_template,
        )
        from leads.models import WhatsAppConfig

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Sync Button Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        config = WhatsAppConfig.load()
        config.outbound_template_name = "say_hi"
        config.meta_message_templates = [
            {
                "name": "say_hi",
                "status": "APPROVED",
                "language": "en_US",
                "body": "Hi~ are you open today? may I know your business hours?",
            },
        ]
        config.save(update_fields=["outbound_template_name", "meta_message_templates"])

        LeadConversationLog.objects.create(
            lead=lead,
            conversation_date=timezone.now().date(),
            remarks="[WhatsApp · agent] We open at 9am — reply from Business app",
        )

        messages = chat_messages_for_lead(lead)
        self.assertEqual(len(messages), 1)

        msg = messages[0]
        self.assertEqual(msg.body, "We open at 9am — reply from Business app")
        self.assertEqual(msg.template_name, "")
        self.assertFalse(outbound_message_is_template(msg))

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336529")
    def test_ycloud_webhook_post_syncs_inbound(self):
        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="YCloud Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        client = Client()
        response = client.post(
            "/whatsapp/webhook/",
            data=json.dumps(self._ycloud_inbound_payload()),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], 1)
        chat = ChatMessage.objects.get(lead=lead, is_outbound=False)
        self.assertEqual(chat.body, "Hello from YCloud")


class PhoneDeduplicationTests(TestCase):
    def test_phone_exists_matches_primary_and_json_numbers(self):
        Lead.objects.create(
            name="Existing",
            address="9 Road",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
        )
        self.assertTrue(phone_exists_in_database("0123456789"))
        self.assertTrue(phone_exists_in_database("+60123456789"))
        self.assertFalse(phone_exists_in_database("+60999998888"))


class ChatFreeTextSendTests(TestCase):
    def setUp(self):
        groups = ensure_pipeline_system_groups()
        self.lead = Lead.objects.create(
            name="Chat Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )

    @patch("leads.views.send_free_text_to_lead")
    def test_send_free_text_returns_outbound_bubble(self, mock_send):
        from leads.models import ChatMessage

        msg = ChatMessage.objects.create(
            lead=self.lead,
            body="Thanks for your reply!",
            is_outbound=True,
            template_name="",
        )
        mock_send.return_value = (True, "", msg)

        client = staff_client()
        response = client.post(
            reverse("send_free_text", kwargs={"pk": self.lead.pk}),
            {"message": "Thanks for your reply!"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Thanks for your reply!", response.content.decode())
        mock_send.assert_called_once_with(self.lead, "Thanks for your reply!")

    def test_send_free_text_rejects_empty_body(self):
        client = staff_client()
        response = client.post(
            reverse("send_free_text", kwargs={"pk": self.lead.pk}),
            {"message": "   "},
        )
        self.assertEqual(response.status_code, 400)


class WhatsAppBatchScheduleTests(TestCase):
    def _make_pending_lead(self, name: str, phone: str = "+60123456789") -> Lead:
        return Lead.objects.create(
            name=name,
            address=f"{name} St",
            group=get_or_create_uncategorized_group(),
            phone_number=phone,
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        )

    def test_dispatch_pending_batch_sends_oldest_first_up_to_limit(self):
        from leads.whatsapp_service import dispatch_pending_batch

        first = self._make_pending_lead("Alpha")
        second = self._make_pending_lead("Beta")
        self._make_pending_lead("Gamma")

        sent_order = []

        def fake_send(lead, *, priority=False, template_name=None):
            sent_order.append(lead.pk)
            lead.whatsapp_status = Lead.WhatsappStatus.SENT
            lead.save(update_fields=["whatsapp_status"])
            return True, ""

        with patch("leads.whatsapp_service.send_text_to_lead", side_effect=fake_send):
            sent = dispatch_pending_batch(2)

        self.assertEqual(sent, 2)
        self.assertEqual(sent_order, [first.pk, second.pk])
        self.assertEqual(
            Lead.objects.filter(whatsapp_status=Lead.WhatsappStatus.PENDING).count(),
            1,
        )

    def test_run_due_scheduled_batches_executes_only_due(self):
        from django.utils import timezone
        from datetime import timedelta

        from leads.models import WhatsAppBatchSchedule
        from leads.whatsapp_service import run_due_scheduled_batches

        due = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() - timedelta(minutes=1),
        )
        future = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        # Two leads assigned to the due batch, one assigned to the future batch.
        for i in range(2):
            lead = self._make_pending_lead(f"Due{i}")
            lead.whatsapp_batches.add(due)
        later = self._make_pending_lead("Later")
        later.whatsapp_batches.add(future)

        def fake_send(lead, *, priority=False, template_name=None):
            lead.whatsapp_status = Lead.WhatsappStatus.SENT
            lead.save(update_fields=["whatsapp_status"])
            return True, ""

        with patch("leads.whatsapp_service.send_text_to_lead", side_effect=fake_send):
            summary = run_due_scheduled_batches()

        due.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual(summary["batches_run"], 1)
        self.assertEqual(summary["leads_sent"], 2)
        self.assertEqual(due.status, WhatsAppBatchSchedule.Status.COMPLETED)
        self.assertEqual(due.sent_count, 2)
        self.assertEqual(future.status, WhatsAppBatchSchedule.Status.PENDING)
        self.assertEqual(
            Lead.objects.filter(whatsapp_status=Lead.WhatsappStatus.PENDING).count(),
            1,
        )

    def test_schedule_batch_view_creates_future_batch(self):
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        target = (timezone.localtime() + timedelta(days=1)).replace(
            second=0, microsecond=0
        )
        client = staff_client()
        response = client.post(
            reverse("whatsapp_schedule_batch"),
            {
                "scheduled_date": target.strftime("%Y-%m-%d"),
                "scheduled_time": target.strftime("%H:%M"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WhatsAppBatchSchedule.objects.count(), 1)
        batch = WhatsAppBatchSchedule.objects.first()
        self.assertEqual(batch.status, WhatsAppBatchSchedule.Status.PENDING)

    def test_schedule_batch_view_rejects_past_datetime(self):
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        target = timezone.localtime() - timedelta(days=1)
        client = staff_client()
        response = client.post(
            reverse("whatsapp_schedule_batch"),
            {
                "scheduled_date": target.strftime("%Y-%m-%d"),
                "scheduled_time": target.strftime("%H:%M"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WhatsAppBatchSchedule.objects.count(), 0)

    def test_cancel_batch_view_cancels_pending(self):
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        batch = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=2),
        )
        client = staff_client()
        response = client.post(reverse("whatsapp_cancel_batch", kwargs={"pk": batch.pk}))
        self.assertEqual(response.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.status, WhatsAppBatchSchedule.Status.CANCELLED)

    def test_bulk_assign_batch_assigns_to_existing_batch(self):
        import json as _json
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        batch = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=3),
        )
        a = self._make_pending_lead("Aa")
        b = self._make_pending_lead("Bb")
        client = staff_client()
        response = client.post(
            reverse("leads_bulk_assign_batch"),
            data=_json.dumps({"ids": [a.pk, b.pk], "batch_id": batch.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["updated"], 2)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertTrue(a.whatsapp_batches.filter(pk=batch.pk).exists())
        self.assertTrue(b.whatsapp_batches.filter(pk=batch.pk).exists())

    def test_bulk_assign_batch_creates_new_batch(self):
        import json as _json
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        target = (timezone.localtime() + timedelta(days=1)).replace(
            second=0, microsecond=0
        )
        a = self._make_pending_lead("Cc")
        client = staff_client()
        response = client.post(
            reverse("leads_bulk_assign_batch"),
            data=_json.dumps(
                {
                    "ids": [a.pk],
                    "batch_id": "new",
                    "new_batch": {
                        "scheduled_date": target.strftime("%Y-%m-%d"),
                        "scheduled_time": target.strftime("%H:%M"),
                        "outbound_template_name": "just_to_say_hi",
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WhatsAppBatchSchedule.objects.count(), 1)
        a.refresh_from_db()
        self.assertTrue(a.whatsapp_batches.exists())

    def test_dequeue_clears_pending_batch_assignment(self):
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        batch = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=2),
        )
        lead = self._make_pending_lead("Dequeued")
        lead.whatsapp_batches.add(batch)

        client = staff_client()
        response = client.post(reverse("dequeue_lead", kwargs={"pk": lead.pk}))
        self.assertEqual(response.status_code, 200)

        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.IDLE)
        self.assertFalse(lead.whatsapp_batches.filter(pk=batch.pk).exists())

    def test_dequeue_unassigns_idle_lead_from_pending_batch(self):
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        batch = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=2),
        )
        lead = Lead.objects.create(
            name="Idle Batched",
            address="1 Batch St",
            group=get_or_create_uncategorized_group(),
            phone_number="+60123456780",
            whatsapp_status=Lead.WhatsappStatus.IDLE,
        )
        lead.whatsapp_batches.add(batch)

        client = staff_client()
        response = client.post(reverse("dequeue_lead", kwargs={"pk": lead.pk}))
        self.assertEqual(response.status_code, 200)

        lead.refresh_from_db()
        self.assertEqual(lead.whatsapp_status, Lead.WhatsappStatus.IDLE)
        self.assertFalse(lead.whatsapp_batches.filter(pk=batch.pk).exists())
        self.assertIn("lead-join-queue-btn", response.content.decode())
        self.assertNotIn("lead-dequeue-btn", response.content.decode())

    def test_dequeue_keeps_completed_batch_history(self):
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        done = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() - timedelta(hours=2),
            status=WhatsAppBatchSchedule.Status.COMPLETED,
        )
        lead = self._make_pending_lead("KeepHistory")
        lead.whatsapp_batches.add(done)

        client = staff_client()
        response = client.post(reverse("dequeue_lead", kwargs={"pk": lead.pk}))
        self.assertEqual(response.status_code, 200)

        lead.refresh_from_db()
        self.assertTrue(lead.whatsapp_batches.filter(pk=done.pk).exists())

    def test_bulk_dequeue_removes_pending_leads_from_queue(self):
        import json as _json
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        batch = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=2),
        )
        pending_a = self._make_pending_lead("BulkA")
        pending_b = self._make_pending_lead("BulkB")
        processing = self._make_pending_lead("Processing")
        processing.whatsapp_status = Lead.WhatsappStatus.PROCESSING
        processing.save(update_fields=["whatsapp_status"])
        pending_a.whatsapp_batches.add(batch)
        pending_b.whatsapp_batches.add(batch)

        client = staff_client()
        response = client.post(
            reverse("leads_bulk_dequeue"),
            data=_json.dumps({"ids": [pending_a.pk, pending_b.pk, processing.pk]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated"], 2)
        self.assertEqual(data["skipped"], 1)

        pending_a.refresh_from_db()
        pending_b.refresh_from_db()
        processing.refresh_from_db()
        self.assertEqual(pending_a.whatsapp_status, Lead.WhatsappStatus.IDLE)
        self.assertEqual(pending_b.whatsapp_status, Lead.WhatsappStatus.IDLE)
        self.assertEqual(processing.whatsapp_status, Lead.WhatsappStatus.PROCESSING)
        self.assertFalse(pending_a.whatsapp_batches.filter(pk=batch.pk).exists())
        self.assertFalse(pending_b.whatsapp_batches.filter(pk=batch.pk).exists())

    def test_bulk_assign_batch_skips_leads_already_in_pending_batch(self):
        import json as _json
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        existing = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=1),
        )
        target = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=2),
        )
        already = self._make_pending_lead("Already")
        already.whatsapp_batches.add(existing)
        fresh = self._make_pending_lead("Fresh")

        client = staff_client()
        response = client.post(
            reverse("leads_bulk_assign_batch"),
            data=_json.dumps({"ids": [already.pk, fresh.pk], "batch_id": target.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["updated"], 1)
        self.assertEqual(payload["skipped"], 1)
        # The already-queued lead stays out of the target batch.
        self.assertFalse(already.whatsapp_batches.filter(pk=target.pk).exists())
        self.assertTrue(fresh.whatsapp_batches.filter(pk=target.pk).exists())

    def test_bulk_assign_batch_enqueues_idle_ready_leads(self):
        import json as _json
        from datetime import timedelta

        from django.utils import timezone

        from leads.models import WhatsAppBatchSchedule

        groups = ensure_pipeline_system_groups()
        batch = WhatsAppBatchSchedule.objects.create(
            scheduled_at=timezone.now() + timedelta(hours=3),
        )
        ready = Lead.objects.create(
            name="ReadyIdle",
            address="1 Ready St",
            group=groups["ready"],
            phone_number="+60129876543",
            whatsapp_status=Lead.WhatsappStatus.IDLE,
        )
        client = staff_client()
        response = client.post(
            reverse("leads_bulk_assign_batch"),
            data=_json.dumps({"ids": [ready.pk], "batch_id": batch.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["updated"], 1)
        ready.refresh_from_db()
        self.assertEqual(ready.whatsapp_status, Lead.WhatsappStatus.PENDING)
        self.assertTrue(ready.whatsapp_batches.filter(pk=batch.pk).exists())
        self.assertEqual(ready.group_id, groups["ready"].pk)


class WhatsAppMetaTemplateSyncTests(TestCase):
    def test_meta_template_choices_uses_synced_catalog(self):
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import meta_template_choices_for_ui

        config = WhatsAppConfig.load()
        config.meta_message_templates = [
            {"name": "custom_greeting", "status": "APPROVED", "language": "en", "body": "Hi"},
            {"name": "just_to_say_hi", "status": "APPROVED", "language": "en", "body": "Hello"},
        ]
        config.save(update_fields=["meta_message_templates"])

        choices = dict(meta_template_choices_for_ui())
        self.assertIn("custom_greeting", choices)
        self.assertIn("just_to_say_hi", choices)
        self.assertIn("(Default", choices["just_to_say_hi"])

    @patch("leads.whatsapp_service.fetch_meta_message_templates_from_api")
    def test_sync_meta_message_templates_persists_catalog(self, mock_fetch):
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import sync_meta_message_templates_to_config

        mock_fetch.return_value = [
            {"name": "just_to_say_hi", "status": "APPROVED", "language": "en", "body": "Hello"},
            {"name": "promo_v2", "status": "APPROVED", "language": "en", "body": "Promo"},
        ]
        count, error = sync_meta_message_templates_to_config()
        self.assertIsNone(error)
        self.assertEqual(count, 2)

        config = WhatsAppConfig.load()
        self.assertEqual(len(config.meta_message_templates), 2)
        self.assertIsNotNone(config.meta_templates_synced_at)

    def test_meta_template_language_preserves_en_us(self):
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import build_meta_template_payload, meta_template_language_for_name

        config = WhatsAppConfig.load()
        config.meta_message_templates = [
            {
                "name": "say_hi",
                "status": "APPROVED",
                "language": "en_US",
                "body": "Hi- are you open today?",
            },
        ]
        config.outbound_template_name = "say_hi"
        config.save(update_fields=["meta_message_templates", "outbound_template_name"])

        self.assertEqual(meta_template_language_for_name("say_hi"), "en_US")
        payload = build_meta_template_payload(
            Lead.objects.create(name="Test Clinic", phone_number="+60123456789"),
            template_name="say_hi",
        )
        self.assertEqual(payload["template"]["language"]["code"], "en_US")

    def test_get_force_send_template_name_falls_back_to_outbound(self):
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import get_force_send_template_name

        config = WhatsAppConfig.load()
        config.meta_message_templates = [
            {"name": "say_hi", "status": "APPROVED", "language": "en_US", "body": "Hi"},
            {"name": "say_hi_en", "status": "APPROVED", "language": "en", "body": "Hello"},
        ]
        config.outbound_template_name = "say_hi"
        config.force_send_template_name = ""
        config.save(
            update_fields=[
                "meta_message_templates",
                "outbound_template_name",
                "force_send_template_name",
            ]
        )
        self.assertEqual(get_force_send_template_name(), "say_hi")

        config.force_send_template_name = "say_hi_en"
        config.save(update_fields=["force_send_template_name"])
        self.assertEqual(get_force_send_template_name(), "say_hi_en")

    def test_known_meta_template_names_requires_synced_catalog(self):
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import known_meta_template_names

        config = WhatsAppConfig.load()
        config.meta_message_templates = []
        config.save(update_fields=["meta_message_templates"])
        self.assertEqual(known_meta_template_names(), frozenset())

    def test_validate_outbound_template_name_accepts_synced_name(self):
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import validate_outbound_template_name

        config = WhatsAppConfig.load()
        config.meta_message_templates = [
            {"name": "hello_clinic", "status": "APPROVED", "language": "en", "body": "Hi"},
        ]
        config.save(update_fields=["meta_message_templates"])

        ok, err = validate_outbound_template_name("hello_clinic")
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_validate_outbound_template_name_rejects_unknown_name(self):
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import validate_outbound_template_name

        config = WhatsAppConfig.load()
        config.meta_message_templates = [
            {"name": "hello_clinic", "status": "APPROVED", "language": "en", "body": "Hi"},
        ]
        config.save(update_fields=["meta_message_templates"])

        ok, err = validate_outbound_template_name("just_to_say_hi")
        self.assertFalse(ok)
        self.assertIn("not approved on YCloud", err)

    @patch("leads.whatsapp_service.fetch_meta_message_templates_from_api")
    def test_normalize_outbound_template_name_uses_catalog_default(self, mock_fetch):
        from leads.models import WhatsAppConfig
        from leads.whatsapp_service import normalize_outbound_template_name, sync_meta_message_templates_to_config

        mock_fetch.return_value = [
            {"name": "hello_clinic", "status": "APPROVED", "language": "en", "body": "Hi", "wabaId": "123"},
        ]
        sync_meta_message_templates_to_config()
        config = WhatsAppConfig.load()
        config.outbound_template_name = "just_to_say_hi"
        config.save(update_fields=["outbound_template_name"])

        self.assertEqual(normalize_outbound_template_name("just_to_say_hi"), "hello_clinic")

    @patch("leads.views.sync_meta_message_templates_to_config")
    def test_refresh_meta_templates_view_returns_toast_and_oob_field(self, mock_sync):
        mock_sync.return_value = (3, None)

        client = staff_client()
        response = client.post(reverse("whatsapp_refresh_meta_templates"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Synced 3 approved template(s) from YCloud", body)
        self.assertIn('id="outbound-template-field"', body)
        self.assertIn("hx-swap-oob", body)
        mock_sync.assert_called_once()

    @patch("leads.views.sync_meta_message_templates_to_config")
    def test_refresh_meta_templates_view_shows_error_toast(self, mock_sync):
        mock_sync.return_value = (0, "Token expired")

        client = staff_client()
        response = client.post(reverse("whatsapp_refresh_meta_templates"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Template sync failed: Token expired", response.content.decode())


class YCloudWabaResolveTests(TestCase):
    @patch("leads.ycloud_service.httpx.Client")
    def test_resolve_sending_waba_id_from_phone_numbers_api(self, mock_client_cls):
        from leads.ycloud_service import resolve_sending_waba_id

        mock_response = mock_client_cls.return_value.__enter__.return_value.get
        mock_response.return_value.status_code = 200
        mock_response.return_value.json.return_value = {
            "items": [
                {
                    "phoneNumber": "+60126336429",
                    "wabaId": "1478974178167699",
                }
            ],
            "page": {"length": 1, "limit": 100},
        }

        with self.settings(WHATSAPP_FROM_NUMBER="+60126336429", YCLOUD_WABA_ID="1470974178167699"):
            waba = resolve_sending_waba_id(refresh=True)
        self.assertEqual(waba, "1478974178167699")


class ClinicUpdatePhoneTests(TestCase):
    def setUp(self):
        groups = ensure_pipeline_system_groups()
        self.group = LeadGroup.objects.create(name="Test Folder", sort_order=50)
        self.user = get_user_model().objects.create_user(
            username="phone-editor", password="pass"
        )
        self.user.is_superuser = True
        self.user.save()
        self.lead = Lead.objects.create(
            name="Phone Change Clinic",
            address="1 Main St",
            phone_number="+60123456789",
            phone_numbers=["+60123456789"],
            group=self.group,
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        ChatMessage.objects.create(
            lead=self.lead,
            body="Hi",
            is_outbound=True,
            template_name="say_hi",
        )
        ChatMessage.objects.create(
            lead=self.lead,
            body="Yes, we are open",
            is_outbound=False,
        )

    def test_clinic_update_phone_resets_whatsapp_dispatch_state(self):
        client = staff_client()
        client.force_login(self.user)
        response = client.patch(
            reverse("clinic_update", kwargs={"pk": self.lead.pk}),
            data=json.dumps(
                {
                    "name": self.lead.name,
                    "phone_numbers": ["+60198765432"],
                    "address": self.lead.address,
                    "category": "unknown",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["phone_numbers"], ["+60198765432"])
        self.assertEqual(data["whatsapp_status"], Lead.WhatsappStatus.IDLE)
        self.assertIn("lead-force-send-btn", data["grid_bottom_actions_html"])

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.phone_number, "+60198765432")
        self.assertEqual(self.lead.whatsapp_status, Lead.WhatsappStatus.IDLE)
        self.assertIsNone(self.lead.whatsapp_sent_at)
        self.assertFalse(
            ChatMessage.objects.filter(lead=self.lead, is_outbound=True).exists()
        )
        inbound = ChatMessage.objects.filter(lead=self.lead, is_outbound=False)
        self.assertEqual(inbound.count(), 1)
        self.assertEqual(inbound.first().body, "Yes, we are open")

    def test_primary_phone_uses_phone_numbers_over_stale_phone_number(self):
        from leads.whatsapp_service import build_meta_template_payload, primary_phone

        self.lead.phone_number = "+60111111111"
        self.lead.phone_numbers = ["+60222222222"]
        self.assertEqual(primary_phone(self.lead), "+60222222222")

        payload = build_meta_template_payload(self.lead, template_name="say_hi")
        self.assertEqual(payload["to"], "+60222222222")

    def test_force_send_button_shown_when_status_sent(self):
        from django.test import RequestFactory

        from leads.views import _force_send_grid_response

        self.lead.whatsapp_status = Lead.WhatsappStatus.SENT
        request = RequestFactory().post(
            "/",
            data={"group_id": str(self.group.pk)},
        )
        response = _force_send_grid_response(
            request,
            self.lead,
            ok=True,
        )
        self.assertIn("lead-force-send-btn", response.content.decode())

    @patch("leads.views.send_text_to_lead")
    def test_force_send_duplicate_prompts_resend(self, mock_send):
        from leads.models import WhatsAppConfig

        config = WhatsAppConfig.load()
        config.force_send_template_name = "say_hi"
        config.save(update_fields=["force_send_template_name"])
        ChatMessage.objects.create(
            lead=self.lead,
            body="Hi~ are you open today?",
            is_outbound=True,
            template_name="say_hi",
        )
        client = staff_client()
        client.force_login(self.user)
        with self.settings(WHATSAPP_FROM_NUMBER="+60126336429", YCLOUD_API_KEY="test"):
            response = client.post(
                reverse("whatsapp_force_send", kwargs={"pk": self.lead.pk}),
                data={"group_id": str(self.group.pk)},
            )
        self.assertEqual(response.status_code, 200)
        mock_send.assert_not_called()
        trigger = json.loads(response["HX-Trigger"])
        self.assertIn("forceSendDuplicatePrompt", trigger)
        self.assertEqual(trigger["forceSendDuplicatePrompt"]["leadId"], self.lead.pk)
        self.assertNotIn("leadCardSink", trigger)

    @patch("leads.views.send_text_to_lead")
    def test_force_send_confirm_duplicate_resends(self, mock_send):
        from leads.models import WhatsAppConfig

        mock_send.return_value = (True, "accepted")
        config = WhatsAppConfig.load()
        config.force_send_template_name = "say_hi"
        config.save(update_fields=["force_send_template_name"])
        ChatMessage.objects.create(
            lead=self.lead,
            body="Hi~ are you open today?",
            is_outbound=True,
            template_name="say_hi",
        )
        client = staff_client()
        client.force_login(self.user)
        with self.settings(WHATSAPP_FROM_NUMBER="+60126336429", YCLOUD_API_KEY="test"):
            response = client.post(
                reverse("whatsapp_force_send", kwargs={"pk": self.lead.pk}),
                data={
                    "group_id": str(self.group.pk),
                    "confirm_duplicate": "1",
                },
            )
        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()

    def test_force_send_success_triggers_dispatched_and_sink(self):
        from django.test import RequestFactory
        from django.utils import timezone

        from leads.views import _force_send_grid_response

        self.lead.whatsapp_sent_at = timezone.now()
        self.lead.whatsapp_status = Lead.WhatsappStatus.SENT
        self.lead.save(update_fields=["whatsapp_sent_at", "whatsapp_status"])
        request = RequestFactory().post(
            "/",
            data={"group_id": str(self.group.pk)},
        )
        response = _force_send_grid_response(
            request,
            self.lead,
            ok=True,
            sink_card=True,
        )
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["leadCardDispatched"], self.lead.pk)
        self.assertEqual(trigger["leadCardSink"], self.lead.pk)
        body = response.content.decode()
        self.assertIn("lead-force-send-btn", body)
        self.assertNotIn("hx-swap-oob", body)


class DailyReportTests(TestCase):
    def setUp(self):
        from datetime import datetime, time

        from django.utils import timezone

        from leads.whatsapp_service import campaign_timezone

        self.tz = campaign_timezone()
        self.today = timezone.now().astimezone(self.tz).date()
        self.user = get_user_model().objects.create_superuser(
            "reportadmin", "report@t.test", "pass"
        )
        self.client = Client()
        self.client.force_login(self.user)
        start = timezone.make_aware(datetime.combine(self.today, time.min), self.tz)
        self.lead_sent = Lead.objects.create(
            name="Alpha Clinic",
            address="1 Main St",
            group=get_or_create_uncategorized_group(),
            phone_number="+60111111111",
            search_state="Selangor",
            search_city="Petaling Jaya",
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=start,
        )
        ChatMessage.objects.create(
            lead=self.lead_sent,
            body="Hi",
            is_outbound=True,
            template_name="say_hi",
            created_at=start,
        )
        self.lead_reply = Lead.objects.create(
            name="Beta Clinic",
            address="2 Main St",
            group=get_or_create_uncategorized_group(),
            phone_number="+60222222222",
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        ChatMessage.objects.create(
            lead=self.lead_reply,
            body="Hello back",
            is_outbound=False,
            created_at=start,
        )

    def _req(self):
        from django.test import RequestFactory

        req = RequestFactory().get("/")
        req.user = self.user
        return req

    def test_reports_excludes_leads_without_outbound_that_day(self):
        from django.utils import timezone

        from leads.views import _daily_report_leads

        start = timezone.make_aware(
            __import__("datetime").datetime.combine(self.today, __import__("datetime").time.min),
            self.tz,
        )
        log_only = Lead.objects.create(
            name="Log Only Clinic",
            address="9 Main St",
            group=get_or_create_uncategorized_group(),
            phone_number="+60999999999",
        )
        LeadConversationLog.objects.create(
            lead=log_only,
            conversation_date=self.today,
            remarks="Phone number updated.",
        )
        leads = _daily_report_leads(self._req(), self.today)
        names = {lead.name for lead in leads}
        self.assertIn("Alpha Clinic", names)
        self.assertNotIn("Log Only Clinic", names)

    def test_reports_shows_active_when_inbound_and_failed(self):
        from django.utils import timezone

        from leads.views import _daily_report_leads

        start = timezone.make_aware(
            __import__("datetime").datetime.combine(self.today, __import__("datetime").time.min),
            self.tz,
        )
        failed_active = Lead.objects.create(
            name="Failed But Active",
            address="8 Main St",
            group=get_or_create_uncategorized_group(),
            phone_number="+60888888888",
            whatsapp_status=Lead.WhatsappStatus.FAILED,
        )
        ChatMessage.objects.create(
            lead=failed_active,
            body="Hi",
            is_outbound=True,
            template_name="say_hi",
            created_at=start,
        )
        ChatMessage.objects.create(
            lead=failed_active,
            body="Thanks",
            is_outbound=False,
            created_at=start,
        )
        leads = {lead.name: lead for lead in _daily_report_leads(self._req(), self.today)}
        self.assertEqual(leads["Failed But Active"].report_status_display, "Active")

    def test_reports_first_send_without_reply_shows_first_message_sent(self):
        from leads.views import _daily_report_leads

        leads = {lead.name: lead for lead in _daily_report_leads(self._req(), self.today)}
        self.assertEqual(leads["Alpha Clinic"].report_status_display, "First Message Sent")

    def test_reports_same_day_reply_shows_active(self):
        from datetime import datetime, time, timedelta

        from django.utils import timezone

        from leads.views import _daily_report_leads

        start = timezone.make_aware(datetime.combine(self.today, time.min), self.tz)
        same_day = Lead.objects.create(
            name="Same Day Reply",
            address="3 Main St",
            group=get_or_create_uncategorized_group(),
            phone_number="+60333333333",
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=start,
        )
        ChatMessage.objects.create(
            lead=same_day,
            body="Hi",
            is_outbound=True,
            template_name="say_hi",
            created_at=start,
        )
        ChatMessage.objects.create(
            lead=same_day,
            body="Auto reply",
            is_outbound=False,
            created_at=start + timedelta(hours=1),
        )
        leads = {lead.name: lead for lead in _daily_report_leads(self._req(), self.today)}
        self.assertEqual(leads["Same Day Reply"].report_status_display, "Active")

    def test_reports_follow_up_outbound_without_inbound_shows_active(self):
        from datetime import datetime, time, timedelta

        from django.utils import timezone

        from leads.views import _daily_report_leads

        yesterday = self.today - timedelta(days=1)
        first_send = timezone.make_aware(
            datetime.combine(yesterday, time.min), self.tz
        )
        follow_up = Lead.objects.create(
            name="Follow Up Only",
            address="4 Main St",
            group=get_or_create_uncategorized_group(),
            phone_number="+60444444444",
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=first_send,
        )
        ChatMessage.objects.create(
            lead=follow_up,
            body="Hi",
            is_outbound=True,
            template_name="say_hi",
            created_at=first_send,
        )
        today_start = timezone.make_aware(
            datetime.combine(self.today, time.min), self.tz
        )
        ChatMessage.objects.create(
            lead=follow_up,
            body="Checking in",
            is_outbound=True,
            template_name="say_hi",
            created_at=today_start,
        )
        leads = {lead.name: lead for lead in _daily_report_leads(self._req(), self.today)}
        self.assertEqual(leads["Follow Up Only"].report_status_display, "Active")

    def test_reports_delayed_inbound_shows_high_potential(self):
        from datetime import datetime, time, timedelta

        from django.utils import timezone

        from leads.views import _daily_report_leads

        yesterday = self.today - timedelta(days=1)
        first_send = timezone.make_aware(
            datetime.combine(yesterday, time.min), self.tz
        )
        delayed = Lead.objects.create(
            name="Delayed Reply",
            address="5 Main St",
            group=get_or_create_uncategorized_group(),
            phone_number="+60555555555",
            whatsapp_status=Lead.WhatsappStatus.SENT,
            whatsapp_sent_at=first_send,
        )
        ChatMessage.objects.create(
            lead=delayed,
            body="Hi",
            is_outbound=True,
            template_name="say_hi",
            created_at=first_send,
        )
        today_start = timezone.make_aware(
            datetime.combine(self.today, time.min), self.tz
        )
        ChatMessage.objects.create(
            lead=delayed,
            body="Yes, interested",
            is_outbound=False,
            created_at=today_start,
        )
        leads = {lead.name: lead for lead in _daily_report_leads(self._req(), self.today)}
        self.assertEqual(leads["Delayed Reply"].report_status_display, "High Potential")

    def test_reports_page_shows_daily_dashboard(self):
        response = self.client.get(
            reverse("reports"),
            {"date": self.today.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Daily reports", html)
        self.assertIn("Alpha Clinic", html)
        self.assertNotIn("Beta Clinic", html)
        self.assertIn("First sends", html)
        self.assertIn("Selangor / Petaling Jaya", html)
        self.assertIn("Click for state breakdown", html)

    def test_reports_page_shows_state_breakdown_for_metric(self):
        response = self.client.get(
            reverse("reports"),
            {"date": self.today.isoformat(), "metric": "first_sends"},
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="report-breakdown-drawer"', html)
        self.assertIn('id="report-breakdown-data"', html)
        self.assertIn('"first_sends"', html)
        self.assertIn("Selangor", html)

    def test_daily_report_location_and_state_breakdown_helpers(self):
        from leads.views import (
            _daily_report_leads,
            _daily_report_location_display,
            _daily_report_state_breakdown,
        )

        leads = {lead.name: lead for lead in _daily_report_leads(self._req(), self.today)}
        self.assertEqual(
            _daily_report_location_display(leads["Alpha Clinic"]),
            "Selangor / Petaling Jaya",
        )
        self.assertEqual(
            leads["Alpha Clinic"].report_location_display,
            "Selangor / Petaling Jaya",
        )
        breakdown = _daily_report_state_breakdown(self._req(), self.today, "first_sends")
        self.assertEqual(breakdown, [{"state": "Selangor", "count": 1}])

    def test_daily_report_export_xlsx(self):
        response = self.client.get(
            reverse("daily_report_export_xlsx"),
            {"date": self.today.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            response["Content-Type"],
        )
        from io import BytesIO

        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(response.content))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        header_idx = next(i for i, row in enumerate(rows) if row[0] == "Name")
        self.assertEqual(
            rows[header_idx],
            (
                "Name",
                "State / area",
                "Contact number",
                "First send today",
                "Outbound",
                "Inbound",
                "Status",
            ),
        )
        names = {row[0] for row in rows[header_idx + 1 :]}
        self.assertIn("Alpha Clinic", names)
        self.assertNotIn("Beta Clinic", names)
        alpha_row = next(row for row in rows[header_idx + 1 :] if row[0] == "Alpha Clinic")
        self.assertEqual(alpha_row[1], "Selangor / Petaling Jaya")

        ws_states = wb["By state"]
        state_rows = list(ws_states.iter_rows(values_only=True))
        self.assertEqual(state_rows[0], ("Metric", "State", "Count"))
        self.assertIn(("First sends", "Selangor", 1), state_rows)

    def test_monthly_report_export_xlsx(self):
        month = self.today.strftime("%Y-%m")
        response = self.client.get(
            reverse("monthly_report_export_xlsx"),
            {"month": month},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            response["Content-Type"],
        )
        from io import BytesIO

        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(response.content))
        self.assertEqual(wb.active.title, "Monthly summary")
        summary_rows = list(wb.active.iter_rows(values_only=True))
        self.assertEqual(summary_rows[0][:2], ("Month", month))
        summary_pairs = [(row[0], row[1]) for row in summary_rows if row[0]]
        self.assertIn(("First messages sent", 1), summary_pairs)
        self.assertIn("By day", wb.sheetnames)
        self.assertIn("By state", wb.sheetnames)
        day_rows = list(wb["By day"].iter_rows(values_only=True))
        self.assertEqual(day_rows[0][0], "Date")
        self.assertTrue(any(row[0] == self.today.isoformat() for row in day_rows[1:]))


class CategoryRuleManagementTests(TestCase):
    def test_category_rules_page_lists_rules(self):
        CategoryRule.objects.create(
            match_phrase="dental",
            category="dental",
            priority=10,
        )
        client = staff_client()
        response = client.get(reverse("category_rules"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"dental", response.content)
        html = response.content.decode()
        self.assertIn("Manage Tags", html)
        self.assertIn("leads/js/mobile-pull-refresh.js", html)
        self.assertIn("Add tag", html)
        self.assertIn("Save changes", html)
        self.assertIn('id="tags-table-save"', html)
        self.assertNotIn(">Save</button>", html)
        self.assertIn("Manage tags and import rules", html)
        self.assertIn('name="match_phrase"', html)
        self.assertNotIn("Add rule", html)
        self.assertNotIn("Import rules", html)
        self.assertNotIn("Category types", html)

    def test_category_types_fragment_returns_manage_html(self):
        client = staff_client()
        response = client.get(reverse("category_types_fragment"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("data-tag-form", html)
        self.assertIn("Unknown", html)

    def test_category_type_save_via_fragment_header(self):
        client = staff_client()
        response = client.post(
            reverse("category_type_save"),
            data={
                "label": "Veterinary",
                "slug": "vet",
                "sort_order": "50",
            },
            HTTP_X_TAGS_FRAGMENT="1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Veterinary", response.content)
        self.assertTrue(Tag.objects.filter(slug="vet").exists())

    def test_category_type_save_and_delete(self):
        client = staff_client()
        create = client.post(
            reverse("category_type_save"),
            data={
                "label": "Pilates",
                "slug": "pilates",
                "sort_order": "80",
            },
        )
        self.assertEqual(create.status_code, 302)
        tag = Tag.objects.get(slug="pilates")
        self.assertEqual(tag.label, "Pilates")

        update = client.post(
            reverse("category_type_save"),
            data={
                "id": str(tag.pk),
                "label": "Pilates Studio",
                "slug": "pilates",
                "sort_order": "75",
            },
        )
        self.assertEqual(update.status_code, 302)
        tag.refresh_from_db()
        self.assertEqual(tag.label, "Pilates Studio")

        delete = client.post(reverse("category_type_delete", kwargs={"pk": tag.pk}))
        self.assertEqual(delete.status_code, 302)
        self.assertFalse(Tag.objects.filter(pk=tag.pk).exists())

    def test_category_rule_save_and_delete(self):
        client = staff_client()
        create = client.post(
            reverse("category_rule_save"),
            data={
                "match_phrase": "gym",
                "category": "fitness",
                "priority": "50",
            },
        )
        self.assertEqual(create.status_code, 302)
        rule = CategoryRule.objects.get(match_phrase="gym")
        self.assertEqual(rule.category, "fitness")

        update = client.post(
            reverse("category_rule_save"),
            data={
                "id": str(rule.pk),
                "match_phrase": "fitness",
                "category": "fitness",
                "priority": "20",
            },
        )
        self.assertEqual(update.status_code, 302)
        rule.refresh_from_db()
        self.assertEqual(rule.match_phrase, "fitness")
        self.assertEqual(rule.priority, 20)

        delete = client.post(reverse("category_rule_delete", kwargs={"pk": rule.pk}))
        self.assertEqual(delete.status_code, 302)
        self.assertFalse(CategoryRule.objects.filter(pk=rule.pk).exists())


class SerperHuntPaginationTests(TestCase):
    @override_settings(SERPER_API_KEY="test-key", HUNT_MAX_LIMIT=100)
    @patch("leads.services.requests.post")
    def test_fetch_paginates_when_limit_above_page_size(self, mock_post):
        from leads.services import fetch_leads_from_serper

        page1 = [
            {
                "title": f"Biz {i}",
                "address": f"St {i}",
                "phoneNumber": f"+6012{i:07d}",
                "latitude": 1.49 + i * 0.001,
                "longitude": 103.74 + i * 0.001,
            }
            for i in range(20)
        ]
        page2 = [
            {
                "title": f"Biz {i}",
                "address": f"St {i}",
                "phoneNumber": f"+6013{i:07d}",
                "latitude": 1.50 + i * 0.001,
                "longitude": 103.75 + i * 0.001,
            }
            for i in range(20, 35)
        ]

        def _resp(places):
            resp = Mock()
            resp.raise_for_status = Mock()
            resp.json.return_value = {
                "places": places,
                "searchParameters": {"ll": "@1.4927,103.7414,13z"},
            }
            return resp

        mock_post.side_effect = [_resp(page1), _resp(page2)]

        result = fetch_leads_from_serper(
            "Kuala Lumpur",
            "",
            num=40,
            shop_keyword="dental clinic",
            state="Selangor",
            country="Malaysia",
        )

        self.assertEqual(mock_post.call_count, 2)
        second_payload = mock_post.call_args_list[1][1]["json"]
        self.assertEqual(second_payload["page"], 2)
        self.assertEqual(second_payload["ll"], "@1.4927,103.7414,13z")
        self.assertEqual(result.places_seen, 35)
        self.assertEqual(result.created, 35)
        self.assertEqual(Lead.objects.count(), 35)

    @override_settings(SERPER_API_KEY="test-key", HUNT_MAX_LIMIT=100)
    @patch("leads.services.requests.post")
    def test_page_two_uses_geocoded_ll_when_page_one_has_no_coordinates(self, mock_post):
        from leads.services import fetch_leads_from_serper

        page1 = [
            {"title": f"Biz {i}", "address": f"St {i}", "phoneNumber": f"+6012{i:07d}"}
            for i in range(20)
        ]
        page2 = [
            {"title": f"Biz {i}", "address": f"St {i}", "phoneNumber": f"+6013{i:07d}"}
            for i in range(20, 25)
        ]

        def _resp(places, ll=None):
            resp = Mock()
            resp.raise_for_status = Mock()
            body: dict = {"places": places}
            if ll:
                body["searchParameters"] = {"ll": ll}
            resp.json.return_value = body
            return resp

        mock_post.side_effect = [
            _resp(page1),
            _resp([], ll="@1.4927,103.7414,13z"),
            _resp(page2, ll="@1.4927,103.7414,13z"),
        ]

        result = fetch_leads_from_serper(
            "Johor Bahru",
            "",
            num=40,
            shop_keyword="klinik",
            state="Johor",
            country="Malaysia",
        )

        self.assertEqual(mock_post.call_count, 3)
        second_payload = mock_post.call_args_list[2][1]["json"]
        self.assertEqual(second_payload["page"], 2)
        self.assertEqual(second_payload["ll"], "@1.4927,103.7414,13z")
        self.assertEqual(result.places_seen, 25)
        self.assertEqual(result.created, 25)

    @override_settings(SERPER_API_KEY="test-key", HUNT_MAX_LIMIT=100)
    @patch("leads.services.requests.post")
    def test_single_page_when_limit_is_20(self, mock_post):
        from leads.services import fetch_leads_from_serper

        places = [
            {"title": f"Solo {i}", "address": f"Road {i}", "phoneNumber": f"+6014{i:07d}"}
            for i in range(15)
        ]
        resp = Mock()
        resp.raise_for_status = Mock()
        resp.json.return_value = {"places": places}
        mock_post.return_value = resp

        result = fetch_leads_from_serper(
            "Penang",
            "",
            num=20,
            shop_keyword="gym",
            state="Penang",
            country="Malaysia",
        )

        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(result.places_seen, 15)
        self.assertEqual(result.created, 15)


class SerperExcludeKeywordTests(TestCase):
    def test_build_search_q_does_not_append_exclude_suffix(self):
        from leads.services import _build_search_q

        q = _build_search_q(
            "Iskandar Puteri",
            "",
            shop_keyword="klinik",
            state="Johor",
            country="Malaysia",
            exclude_keywords=["dental", "24 jam"],
        )
        self.assertEqual(q, "klinik Iskandar Puteri Johor Malaysia")
        self.assertNotIn("-dental", q)

    def test_strip_serper_query_operators(self):
        from leads.services import _strip_serper_query_operators

        raw = 'klinik Johor Bahru Johor Malaysia -dental -"24 jam"'
        self.assertEqual(
            _strip_serper_query_operators(raw),
            "klinik Johor Bahru Johor Malaysia",
        )

    @override_settings(SERPER_API_KEY="test-key", HUNT_MAX_LIMIT=100)
    @patch("leads.services.requests.post")
    def test_fetch_skips_excluded_places(self, mock_post):
        from leads.services import fetch_leads_from_serper

        places = [
            {"title": "Alpha Klinik", "address": "St 1", "phoneNumber": "+60121111111"},
            {"title": "Beta Dental Clinic", "address": "St 2", "phoneNumber": "+60122222222"},
        ]
        resp = Mock()
        resp.raise_for_status = Mock()
        resp.json.return_value = {"places": places}
        mock_post.return_value = resp

        result = fetch_leads_from_serper(
            "Johor Bahru",
            "",
            num=20,
            shop_keyword="klinik",
            state="Johor",
            country="Malaysia",
            exclude_keywords=["dental"],
        )

        payload = mock_post.call_args[1]["json"]
        self.assertNotIn("-dental", payload["q"])
        self.assertEqual(result.skipped_excluded, 1)
        self.assertEqual(result.places_seen, 1)
        self.assertEqual(result.created, 1)
        self.assertEqual(Lead.objects.get().name, "Alpha Klinik")


class BackupExportTests(TestCase):
    def test_build_backup_workbook_filters_selected_leads(self):
        from io import BytesIO

        from openpyxl import load_workbook

        from leads.backup import build_backup_workbook

        group = LeadGroup.objects.create(name="Quality", sort_order=10)
        keep = Lead.objects.create(name="Keep Me", address="1 Road", group=group)
        Lead.objects.create(name="Drop Me", address="2 Road", group=group)
        ChatMessage.objects.create(lead=keep, body="Hi", is_outbound=True)
        ChatMessage.objects.create(
            lead=Lead.objects.get(name="Drop Me"),
            body="Bye",
            is_outbound=False,
        )

        wb = build_backup_workbook(lead_ids=[keep.pk])
        buf = BytesIO()
        wb.save(buf)
        loaded = load_workbook(BytesIO(buf.getvalue()), read_only=True, data_only=True)

        lead_rows = list(loaded["Leads"].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(lead_rows), 1)
        self.assertEqual(lead_rows[0][1], "Keep Me")

        chat_rows = list(loaded["ChatMessages"].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(chat_rows), 1)
        self.assertEqual(chat_rows[0][0], keep.pk)

        group_rows = list(loaded["Groups"].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(group_rows), 1)
        self.assertEqual(group_rows[0][0], "Quality")

    def test_export_full_backup_view_accepts_ids_query(self):
        keep = Lead.objects.create(name="Export Me", address="9 Road")
        Lead.objects.create(name="Other", address="8 Road")
        client = staff_client()
        response = client.get(reverse("export_full_backup"), {"ids": str(keep.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", response["Content-Type"])
        self.assertIn(f"clinic_crm_backup_1_leads_", response["Content-Disposition"])


class ExcelLeadsImportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_superuser(
            "xlsxadmin", "xlsx@t.test", "pass"
        )
        self.client.force_login(self.user)
        self.group = get_or_create_uncategorized_group()
        self.tag, _ = Tag.objects.get_or_create(
            slug="dental", defaults={"label": "Dental", "sort_order": 1}
        )

    def _xlsx_upload(self, content, name="business_leads.xlsx"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(
            name,
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_export_import_round_trip(self):
        lead = Lead.objects.create(
            name="Excel Clinic",
            address="10 Import Rd",
            phone_number="+60121111000",
            phone_numbers=["+60121111000", "+60121111001"],
            website="https://excel.example/",
            shop_keyword="clinic",
            search_city="Petaling Jaya",
            search_country="Malaysia",
            search_query="weight loss clinic",
            source_url="https://maps.example/place",
            is_very_important=True,
            is_processed=True,
            group=self.group,
        )
        lead.tags.set([self.tag])
        export = self.client.get(reverse("clinics_export_xlsx"))
        self.assertEqual(export.status_code, 200)
        payload = export.content
        lead.delete()

        response = self.client.post(
            reverse("import_leads_xlsx"),
            {"xlsx": self._xlsx_upload(payload), "group_id": "uncategorized"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["leads_created"], 1)
        imported = Lead.objects.get(name="Excel Clinic")
        self.assertEqual(imported.address, "10 Import Rd")
        self.assertEqual(imported.phone_number, "+60121111000")
        self.assertEqual(imported.phone_numbers, ["+60121111000", "+60121111001"])
        self.assertEqual(imported.shop_keyword, "clinic")
        self.assertEqual(imported.search_city, "Petaling Jaya")
        self.assertEqual(imported.search_query, "weight loss clinic")
        self.assertTrue(imported.is_very_important)
        self.assertCountEqual(list(imported.tags.values_list("slug", flat=True)), ["dental"])
        self.assertEqual(imported.group_id, self.group.pk)

    def test_import_skips_existing_name_and_address(self):
        Lead.objects.create(
            name="Excel Clinic",
            address="10 Import Rd",
            group=self.group,
        )
        export = self.client.get(reverse("clinics_export_xlsx"))
        response = self.client.post(
            reverse("import_leads_xlsx"),
            {"xlsx": self._xlsx_upload(export.content), "group_id": "uncategorized"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["leads_created"], 0)
        self.assertEqual(data["leads_skipped"], 1)
        self.assertEqual(Lead.objects.filter(name="Excel Clinic").count(), 1)

    def test_rejects_full_backup_workbook(self):
        from io import BytesIO

        from leads.backup import build_backup_workbook

        Lead.objects.create(name="Keep Me", address="1 Road", group=self.group)
        wb = build_backup_workbook()
        buf = BytesIO()
        wb.save(buf)
        response = self.client.post(
            reverse("import_leads_xlsx"),
            {"xlsx": self._xlsx_upload(buf.getvalue(), name="clinic_crm_backup.xlsx")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Restore", response.json()["detail"])


class GlobalLeadSearchTests(TestCase):
    def setUp(self):
        from leads.models import LeadGroup

        self.client = Client()
        self.user = get_user_model().objects.create_superuser(
            "searchadmin", "search@t.test", "pass"
        )
        self.client.force_login(self.user)
        self.uncategorized = get_or_create_uncategorized_group()
        self.custom_group = LeadGroup.objects.create(name="Selangor Prospects", sort_order=10)
        self.hidden_in_uncategorized = Lead.objects.create(
            name="Alpha Dental",
            address="1 Jalan Alpha",
            group=self.uncategorized,
            phone_number="+60111111111",
            search_city="Petaling Jaya",
        )
        self.hidden_in_custom = Lead.objects.create(
            name="Beta Physio",
            address="2 Jalan Beta",
            group=self.custom_group,
            phone_number="+60222222222",
            search_city="Shah Alam",
        )

    def test_global_search_finds_leads_across_folders(self):
        from django.test import RequestFactory

        from leads.views import _leads_queryset_for_table

        request = RequestFactory().get("/", {"q": "Beta"})
        request.user = self.user
        qs, is_global = _leads_queryset_for_table(request)
        self.assertTrue(is_global)
        names = list(qs.values_list("name", flat=True))
        self.assertEqual(names, ["Beta Physio"])

    def test_global_search_ajax_includes_folder_badges(self):
        response = self.client.get(
            reverse("get_leads_table"),
            {"q": "Alpha"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["global_search"])
        self.assertEqual(payload["global_search_query"], "Alpha")
        self.assertEqual(payload["global_search_count"], 1)
        self.assertIsNone(payload["funnel_metrics"])
        self.assertIn("lead-folder-badge", payload["tbody_html"])
        self.assertIn("New", payload["tbody_html"])
        self.assertNotIn("Uncategorized", payload["tbody_html"])
        self.assertIn("data-folder-tab-id=\"uncategorized\"", payload["tbody_html"])

    def test_global_search_custom_group_shows_folder_actions(self):
        response = self.client.get(
            reverse("get_leads_table"),
            {"q": "Beta"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Selangor Prospects", payload["grid_html"])
        self.assertIn("lead-force-send-btn", payload["grid_html"])
        self.assertNotIn("delete_lead_permanently", payload["grid_html"])

    def test_global_search_excludes_trash(self):
        from leads.pipeline import get_or_create_trash_group

        trash = get_or_create_trash_group()
        Lead.objects.create(
            name="Trash Alpha",
            address="99 Dump Rd",
            group=trash,
        )
        response = self.client.get(reverse("get_leads_table"), {"q": "Trash Alpha"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["global_search_count"], 0)
        self.assertNotIn("Trash Alpha", payload["tbody_html"])

    def test_tab_query_ignores_short_q_param(self):
        from django.test import RequestFactory

        from leads.views import _leads_queryset_for_table

        request = RequestFactory().get("/", {"q": "A", "group_id": str(self.custom_group.pk)})
        request.user = self.user
        qs, is_global = _leads_queryset_for_table(request)
        self.assertFalse(is_global)
        self.assertEqual(list(qs.values_list("name", flat=True)), ["Beta Physio"])


class ApiStatusSidebarTests(TestCase):
    @override_settings(SERPER_API_KEY="test-serper")
    def test_sidebar_partial_shows_provider_status_and_usage(self):
        from unittest.mock import patch

        SearchQueryRecord.objects.create(
            keyword="Clinic",
            maps_search_query="clinic",
            search_city="KL",
            search_state="Selangor",
        )
        Lead.objects.create(
            name="Sent Lead",
            address="1 St",
            phone_number="+60123456789",
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        Lead.objects.create(
            name="Pending Lead",
            address="2 St",
            phone_number="+60198765432",
            whatsapp_status=Lead.WhatsappStatus.PENDING,
        )

        with patch(
            "leads.api_status_service.fetch_gateway_status",
            return_value={"connected": False, "state": "unconfigured", "error": "Missing: YCLOUD_API_KEY"},
        ):
            response = staff_client().get(reverse("api_status_sidebar"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("YCloud WhatsApp", html)
        self.assertIn("Not configured", html)
        self.assertIn("Serper Maps", html)
        self.assertIn("Outscraper", html)
        self.assertIn("Ready", html)
        self.assertIn("hunts", html)
        self.assertIn("sent", html)
        self.assertIn("pending", html)

    @override_settings(SERPER_API_KEY="")
    def test_sidebar_partial_ycloud_connected(self):
        from unittest.mock import patch

        with patch(
            "leads.api_status_service.fetch_gateway_status",
            return_value={"connected": True, "state": "open", "error": None},
        ):
            response = staff_client().get(reverse("api_status_sidebar"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Connected", html)
        self.assertIn("Not configured", html)  # Serper still unconfigured


class OutboundFreeTextFailureTests(TestCase):
    @override_settings(YCLOUD_API_KEY="ycloud-key", WHATSAPP_FROM_NUMBER="+60126336429")
    def test_free_text_blocked_outside_24h_window(self):
        from unittest.mock import patch

        from leads.chat_messages import chat_messages_for_lead
        from leads.models import ChatMessage
        from leads.whatsapp_service import send_free_text_to_lead

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Window Clinic",
            address="1 Main St",
            phone_number="+60198765030",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )

        with patch("leads.whatsapp_service.send_message_directly") as mock_send:
            ok, detail, msg = send_free_text_to_lead(lead, "Hello, still interested?")

        self.assertFalse(ok)
        self.assertIn("24-hour", detail)
        self.assertIsNone(msg)
        mock_send.assert_not_called()
        # No misleading outbound bubble was created.
        self.assertEqual(
            ChatMessage.objects.filter(lead=lead, is_outbound=True).count(), 0
        )
        self.assertEqual(chat_messages_for_lead(lead), [])

    @override_settings(YCLOUD_API_KEY="ycloud-key", WHATSAPP_FROM_NUMBER="+60126336429")
    def test_free_text_sends_inside_24h_window(self):
        from unittest.mock import patch

        from leads.chat_messages import record_inbound_chat_message
        from leads.models import ChatMessage
        from leads.whatsapp_service import send_free_text_to_lead

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Open Window Clinic",
            address="1 Main St",
            phone_number="+60198765031",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        record_inbound_chat_message(lead, body="Hi, yes please", meta_message_id="wamid.IN1")

        with patch(
            "leads.whatsapp_service.send_message_directly",
            return_value=(True, "", {"id": "ycloud_ok_1", "status": "accepted"}),
        ) as mock_send:
            ok, detail, msg = send_free_text_to_lead(lead, "Great, here are the details.")

        self.assertTrue(ok)
        self.assertEqual(detail, "")
        self.assertIsNotNone(msg)
        mock_send.assert_called_once()
        self.assertEqual(
            ChatMessage.objects.filter(lead=lead, is_outbound=True).count(), 1
        )

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_delivery_failure_hides_outbound_bubble(self):
        from leads.chat_messages import (
            FAILED_DELIVERY_STATUS,
            chat_messages_for_lead,
            record_outbound_chat_message,
        )
        from leads.models import ChatMessage
        from leads.whatsapp_webhook import (
            ParsedWebhookDeliveryFailure,
            sync_webhook_delivery_failure,
        )

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Failed Send Clinic",
            address="1 Main St",
            phone_number="+60198765032",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.SENT,
        )
        bubble = record_outbound_chat_message(
            lead,
            template_name="",
            body="Are you free this week?",
            meta_message_id="wamid.FAILEDFREE1",
        )

        failure = ParsedWebhookDeliveryFailure(
            remote_phone="+60198765032",
            error_message="Message undeliverable",
            message_id="wamid.FAILEDFREE1",
        )
        self.assertTrue(sync_webhook_delivery_failure(failure))

        bubble.refresh_from_db()
        self.assertEqual(bubble.delivery_status, FAILED_DELIVERY_STATUS)
        feed = chat_messages_for_lead(lead)
        self.assertNotIn(bubble.pk, [m.pk for m in feed])

    @override_settings(WHATSAPP_FROM_NUMBER="+60126336429")
    def test_failed_bubble_not_resurrected_from_agent_log(self):
        from django.utils import timezone

        from leads.chat_messages import (
            chat_messages_for_lead,
            record_outbound_chat_message,
        )

        groups = ensure_pipeline_system_groups()
        lead = Lead.objects.create(
            name="Resurrect Clinic",
            address="1 Main St",
            phone_number="+60198765033",
            group=groups["uncategorized"],
            whatsapp_status=Lead.WhatsappStatus.FAILED,
        )
        body = "Following up on your enquiry."
        record_outbound_chat_message(
            lead,
            template_name="",
            body=body,
            meta_message_id="wamid.RESURRECT1",
        )
        # Agent send log (would normally recreate the bubble on sync)...
        LeadConversationLog.objects.create(
            lead=lead,
            conversation_date=timezone.now().date(),
            remarks=f"wa-id:wamid.RESURRECT1\n[WhatsApp · agent] {body}",
        )
        # ...and the matching delivery-failure log.
        LeadConversationLog.objects.create(
            lead=lead,
            conversation_date=timezone.now().date(),
            remarks="[WhatsApp delivery failed] to +60198765033: Undeliverable · wamid.RESURRECT1",
        )

        feed = chat_messages_for_lead(lead)
        self.assertEqual(feed, [])
        # Re-open should stay clean (no resurrection).
        feed_again = chat_messages_for_lead(lead)
        self.assertEqual(feed_again, [])
