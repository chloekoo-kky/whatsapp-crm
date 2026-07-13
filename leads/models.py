from datetime import time

from django.db import models


class ShopType(models.Model):
    """
    User-managed hunt preset: label + keyword for Serper, optional default Maps fragment.
    Does not replace free-text ``Lead.shop_keyword`` on rows—presets only fill the hunt form.
    """

    name = models.CharField(
        max_length=120,
        unique=True,
        help_text="Label and hunt keyword stored on imported leads (e.g. Medical clinic).",
    )
    maps_query_default = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional. Pre-fills the Maps search field when you pick this type; if empty, the keyword alone is used.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Shop type"
        verbose_name_plural = "Shop types"

    def __str__(self) -> str:
        return self.name


class SearchQueryRecord(models.Model):
    """One row per Serper hunt from the dashboard (for history and filtering)."""

    keyword = models.CharField(max_length=160, help_text="Hunt keyword (e.g. Fitness Center).")
    maps_search_query = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Maps query fragment used with the city (may match keyword).",
    )
    search_city = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="City / area used for the hunt.",
    )
    search_state = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="State / region used for the hunt.",
    )
    search_country = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional country to disambiguate the Serper hunt.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Search query"
        verbose_name_plural = "Search history"

    def __str__(self) -> str:
        return f"{self.keyword} @ {self.search_city or '—'}"


class LeadGroup(models.Model):
    """User-defined folder for organizing leads (each lead has at most one group)."""

    name = models.CharField(max_length=100, unique=True)
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers appear first in the dashboard tabs (user reorderable).",
    )

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Lead group"
        verbose_name_plural = "Lead groups"

    def __str__(self) -> str:
        return self.name


class HuntRefineRecord(models.Model):
    """One persisted Gemini “refine hunt” result for a lead folder (suggest-only; audit / history)."""

    group = models.ForeignKey(
        LeadGroup,
        on_delete=models.CASCADE,
        related_name="hunt_refine_records",
    )
    secondary_group = models.ForeignKey(
        LeadGroup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Optional second folder merged into the same analysis (e.g. “very potential”).",
    )
    secondary_leads_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="How many leads from secondary_group were included.",
    )
    leads_analyzed = models.PositiveSmallIntegerField()
    suggested_shop_keyword = models.CharField(max_length=160, blank=True, default="")
    suggested_maps_query = models.CharField(max_length=255, blank=True, default="")
    patterns_summary = models.TextField(blank=True, default="")
    what_to_avoid = models.TextField(blank=True, default="")
    enrichment_tips = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "leads_huntrefinerecord"
        verbose_name = "Hunt refine record"
        verbose_name_plural = "Hunt refine records"

    def __str__(self) -> str:
        return f"{self.group.name} @ {self.created_at:%Y-%m-%d %H:%M}"


class Lead(models.Model):
    """Business lead from Serper Maps with optional Gemini enrichment."""

    class WhatsappStatus(models.TextChoices):
        IDLE = "idle", "Idle"
        PENDING = "pending", "Pending Queue"
        PROCESSING = "processing", "Processing"
        SENT = "sent", "First Message Sent"
        FAILED = "failed", "Failed"

    class Category(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        INVALID = "invalid", "Invalid / irrelevant"
        GP = "gp", "GP"
        AESTHETIC = "aesthetic", "Aesthetic"
        DENTAL = "dental", "Dental"
        FITNESS = "fitness", "Fitness / gym / yoga"
        CAFE = "cafe", "Café / restaurant / F&B"
        RETAIL = "retail", "Retail / shop"
        SERVICE = "service", "Services / other business"

    name = models.CharField(max_length=255)
    phone_number = models.CharField(
        max_length=64,
        blank=True,
        help_text="Primary phone (denormalized: first entry in phone_numbers).",
    )
    phone_numbers = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered E.164-style numbers (+60…); first is primary. Max 8.",
    )
    address = models.TextField(blank=True)
    website = models.URLField(max_length=500, blank=True)
    shop_keyword = models.CharField(
        max_length=160,
        blank=True,
        default="",
        help_text="Keyword the user entered before the hunt (e.g. fitness center, café).",
    )
    category = models.CharField(
        max_length=32,
        default=Category.UNKNOWN,
        help_text="Business type / relevance — rules, AI, or manual update.",
    )
    source_url = models.TextField(
        blank=True,
        help_text="Google Maps URL from Serper for this place.",
    )
    is_processed = models.BooleanField(
        default=False,
        help_text="True when the lead is categorized and ready (AI and/or manual), without pending review.",
    )
    is_chain = models.BooleanField(
        default=False,
        help_text="True when multiple locations are inferred (DB name match and/or AI).",
    )
    chain_detected_internal = models.BooleanField(
        default=False,
        help_text="True when another row shares the same business name with a different address.",
    )
    chain_detected_ai = models.BooleanField(
        default=False,
        help_text="True when Gemini flags multi-location / group signals from listing text.",
    )
    location_count_estimate = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Optional estimate from AI when sources mention several branches or cities.",
    )
    is_very_important = models.BooleanField(
        default=False,
        help_text="User-flagged as very important (e.g. star on dashboard card).",
    )
    whatsapp_draft = models.TextField(
        blank=True,
        help_text="Personalized opening message as a potential customer (e.g. for WhatsApp).",
    )
    whatsapp_status = models.CharField(
        max_length=16,
        choices=WhatsappStatus.choices,
        default=WhatsappStatus.IDLE,
        db_index=True,
        help_text="Outbound first-touchpoint automator queue state.",
    )
    whatsapp_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the first automated WhatsApp message was dispatched.",
    )
    whatsapp_instance_id = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Meta Graph API phone number ID used for the last outbound dispatch.",
    )
    whatsapp_last_error = models.TextField(
        blank=True,
        default="",
        help_text="Last Meta Cloud API / network error for automated WhatsApp dispatch.",
    )
    whatsapp_batches = models.ManyToManyField(
        "WhatsAppBatchSchedule",
        blank=True,
        related_name="leads",
        help_text="Scheduled batches this lead is part of (assigned from the Queue).",
    )
    search_city = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="City / area used for the Serper hunt that captured this lead.",
    )
    search_state = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="State / region from the Serper hunt that captured this lead.",
    )
    search_query = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Maps search query used for the Serper hunt.",
    )
    search_country = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Country used for the Serper hunt that captured this lead (optional).",
    )
    search_query_record = models.ForeignKey(
        SearchQueryRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leads",
        help_text="Hunt batch that created or last updated this row from the dashboard.",
    )
    group = models.ForeignKey(
        LeadGroup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="leads",
        help_text="Optional folder; ungrouped leads appear only under “All leads”.",
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Manual sort in list/grid within a folder; ties break by created_at.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "leads_lead"
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        ordering = ["display_order", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "address"],
                name="unique_lead_name_address",
            ),
        ]
        indexes = [
            models.Index(fields=["shop_keyword"], name="leads_shop_kw_idx"),
            models.Index(fields=["category"], name="leads_category_idx"),
            models.Index(fields=["search_query_record"], name="leads_search_rec_idx"),
            models.Index(fields=["group"], name="leads_leadgroup_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class WhatsAppConfig(models.Model):
    """Singleton campaign scheduler for Meta WhatsApp Cloud API outbound dispatch."""

    SINGLETON_ID = 1
    DEFAULT_ALLOWED_DAYS = [1, 2, 3, 4, 5, 6]

    allowed_days = models.JSONField(
        default=list,
        help_text="ISO weekdays when sending is allowed (Monday=1 … Sunday=7).",
    )
    window1_start = models.TimeField(default=time(8, 0))
    window1_end = models.TimeField(default=time(13, 0))
    window2_start = models.TimeField(default=time(15, 0))
    window2_end = models.TimeField(default=time(20, 0))
    is_paused = models.BooleanField(
        default=False,
        help_text="Master kill-switch for the campaign daemon.",
    )
    meta_message_templates = models.JSONField(
        default=list,
        blank=True,
        help_text="Last synced Meta message_templates catalog (approved outbound).",
    )
    meta_templates_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When meta_message_templates was last refreshed from Meta Graph API.",
    )
    outbound_template_name = models.CharField(
        max_length=64,
        default="just_to_say_hi",
        help_text="Meta-approved template name used for outbound first-touch dispatch.",
    )
    force_send_template_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Meta template used by the Send now (⚡) button on group folder cards.",
    )
    free_text_templates = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered Active Chat reply templates ({label, text}). Top 3 appear in the chat drawer.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads_whatsappconfig"
        verbose_name = "WhatsApp campaign config"
        verbose_name_plural = "WhatsApp campaign config"

    def __str__(self) -> str:
        state = "paused" if self.is_paused else "active"
        return f"WhatsAppConfig ({state})"

    def normalized_allowed_days(self) -> list[int]:
        raw = self.allowed_days if isinstance(self.allowed_days, list) else []
        days = sorted({int(d) for d in raw if str(d).isdigit() and 1 <= int(d) <= 7})
        return days or list(self.DEFAULT_ALLOWED_DAYS)

    @classmethod
    def load(cls) -> "WhatsAppConfig":
        obj, _ = cls.objects.get_or_create(
            id=cls.SINGLETON_ID,
            defaults={
                "allowed_days": list(cls.DEFAULT_ALLOWED_DAYS),
                "window1_start": time(8, 0),
                "window1_end": time(13, 0),
                "window2_start": time(15, 0),
                "window2_end": time(20, 0),
                "is_paused": False,
                "outbound_template_name": "just_to_say_hi",
            },
        )
        return obj


class WhatsAppBatchSchedule(models.Model):
    """A one-time scheduled batch that sends the Meta template to its leads.

    Executed by the ``run_whatsapp_batch`` command (Railway cron): when
    ``scheduled_at`` is due and ``status`` is ``pending``, it dispatches every
    PENDING lead assigned to it (``Lead.whatsapp_batches``), then marks itself
    completed.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Scheduled"
        PROCESSING = "processing", "Sending"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    scheduled_at = models.DateTimeField(
        db_index=True,
        help_text="When this batch should run (stored timezone-aware).",
    )
    outbound_template_name = models.CharField(
        max_length=64,
        default="just_to_say_hi",
        help_text="Meta-approved template this batch dispatches.",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    sent_count = models.PositiveIntegerField(
        default=0,
        help_text="Leads actually dispatched when the batch ran.",
    )
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "leads_whatsappbatchschedule"
        ordering = ["-scheduled_at", "-id"]
        verbose_name = "WhatsApp batch schedule"
        verbose_name_plural = "WhatsApp batch schedules"

    def __str__(self) -> str:
        return f"Batch @ {self.scheduled_at:%Y-%m-%d %H:%M} ({self.status})"


class WhatsAppScriptTemplate(models.Model):
    """Per-folder outreach copy reference; live sends use Meta-approved templates."""

    group_name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Industry folder label (e.g. Aesthetic, Clinics, General Outreach).",
    )
    template_text = models.TextField(
        blank=True,
        default="",
        help_text="Message body with {{ name }} and {{ area }} placeholders.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads_whatsappscripttemplate"
        ordering = ["group_name"]
        verbose_name = "WhatsApp script template"
        verbose_name_plural = "WhatsApp script templates"

    def __str__(self) -> str:
        return self.group_name


class ChainBrandStatus(models.Model):
    """
    Per-brand (case-insensitive name) status for chain outreach.
    Applies to every lead row sharing the same business name.
    """

    brand_key = models.CharField(
        max_length=255,
        unique=True,
        help_text="Lowercased, trimmed business name used as the chain group key.",
    )
    chain_contacted = models.BooleanField(
        default=False,
        help_text="User marked the entire chain group as contacted.",
    )
    exempt_from_spam = models.BooleanField(
        default=False,
        help_text="Exclude this chain from further outreach / spamming.",
    )
    contacted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads_chainbrandstatus"
        verbose_name = "Chain brand status"
        verbose_name_plural = "Chain brand statuses"

    def __str__(self) -> str:
        flags = []
        if self.chain_contacted:
            flags.append("contacted")
        if self.exempt_from_spam:
            flags.append("exempt")
        return f"{self.brand_key} ({', '.join(flags) or '—'})"


class ChatMessage(models.Model):
    """Meta WhatsApp thread message for the sliding chat inbox (inbound or outbound)."""

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    body = models.TextField(help_text="Rendered message text shown in the chat drawer.")
    is_outbound = models.BooleanField(
        default=False,
        help_text="True for CRM/Meta template sends; false for client replies.",
    )
    template_name = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Meta template name when this row is an outbound template send.",
    )
    meta_message_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text="WhatsApp message id from Meta webhooks (dedupe inbound).",
    )
    delivery_status = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="Outbound delivery state; 'failed' rows are hidden from the chat feed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "leads_chatmessage"
        ordering = ["created_at", "id"]
        verbose_name = "Chat message"
        verbose_name_plural = "Chat messages"

    def __str__(self) -> str:
        direction = "out" if self.is_outbound else "in"
        return f"{self.lead_id} {direction}: {self.body[:40]}"


class LeadConversationLog(models.Model):
    """Conversation history row for a lead (date + remarks)."""

    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="conversation_logs",
    )
    conversation_date = models.DateField(
        help_text="Date of the conversation or follow-up.",
    )
    remarks = models.TextField(
        help_text="What happened in the conversation.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "leads_leadconversationlog"
        verbose_name = "Lead conversation log"
        verbose_name_plural = "Lead conversation logs"
        ordering = ["-conversation_date", "-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.lead_id} @ {self.conversation_date:%Y-%m-%d}"


class LeadCategoryType(models.Model):
    """User-managed business category options (dropdown values on leads)."""

    slug = models.SlugField(
        max_length=32,
        unique=True,
        help_text="Stored on Lead.category (lowercase, e.g. dental, gp).",
    )
    label = models.CharField(max_length=80)
    sort_order = models.PositiveSmallIntegerField(default=100)
    is_system = models.BooleanField(
        default=False,
        help_text="System categories (Unknown, Invalid) cannot be deleted.",
    )

    class Meta:
        db_table = "leads_leadcategorytype"
        ordering = ["sort_order", "label", "slug"]
        verbose_name = "Category type"
        verbose_name_plural = "Category types"

    def __str__(self) -> str:
        return self.label


class CategoryRule(models.Model):
    """
    If ``match_phrase`` (case-insensitive) appears in a lead's name, ``category`` applies.
    Lower ``priority`` is checked first; first match wins. Managed in admin — no Gemini requirement.
    """

    match_phrase = models.CharField(
        max_length=200,
        help_text="Substring matched against business name (case-insensitive).",
    )
    category = models.CharField(
        max_length=32,
        help_text="Lead.category slug assigned when the rule matches.",
    )
    priority = models.PositiveSmallIntegerField(
        default=100,
        help_text="Lower number = higher priority (evaluated first).",
    )

    class Meta:
        db_table = "leads_categoryrule"
        ordering = ["priority", "id"]
        verbose_name = "Category rule"
        verbose_name_plural = "Category rules"

    def __str__(self) -> str:
        return f"{self.match_phrase!r} → {self.category}"
