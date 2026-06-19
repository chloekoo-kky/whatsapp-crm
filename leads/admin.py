from django.contrib import admin

from leads.models import (
    CategoryRule,
    ChainBrandStatus,
    Lead,
    LeadConversationLog,
    LeadGroup,
    SearchQueryRecord,
    WhatsAppBatchSchedule,
    WhatsAppConfig,
)


@admin.register(ChainBrandStatus)
class ChainBrandStatusAdmin(admin.ModelAdmin):
    list_display = ("brand_key", "chain_contacted", "exempt_from_spam", "contacted_at", "updated_at")
    list_filter = ("chain_contacted", "exempt_from_spam")
    search_fields = ("brand_key",)
    ordering = ("brand_key",)


@admin.register(LeadGroup)
class LeadGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order")
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(SearchQueryRecord)
class SearchQueryRecordAdmin(admin.ModelAdmin):
    list_display = ("keyword", "maps_search_query", "search_city", "search_country", "created_at")
    list_filter = ("created_at",)
    search_fields = ("keyword", "maps_search_query", "search_city", "search_country")
    ordering = ("-created_at",)


@admin.register(CategoryRule)
class CategoryRuleAdmin(admin.ModelAdmin):
    list_display = ("priority", "match_phrase", "category")
    list_filter = ("category",)
    search_fields = ("match_phrase",)
    ordering = ("priority", "id")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "shop_keyword",
        "category",
        "is_chain",
        "is_very_important",
        "is_processed",
        "phone_number",
        "website",
        "created_at",
    )
    list_filter = (
        "category",
        "group",
        "is_processed",
        "is_chain",
        "is_very_important",
    )
    search_fields = (
        "name",
        "address",
        "website",
        "phone_number",
        "search_city",
        "search_country",
        "search_query",
        "shop_keyword",
    )


@admin.register(LeadConversationLog)
class LeadConversationLogAdmin(admin.ModelAdmin):
    list_display = ("lead", "conversation_date", "created_at")
    list_filter = ("conversation_date", "created_at")
    search_fields = ("lead__name", "remarks")
    ordering = ("-conversation_date", "-created_at")


@admin.register(WhatsAppConfig)
class WhatsAppConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "outbound_template_name",
        "is_paused",
        "allowed_days",
        "window1_start",
        "window1_end",
        "updated_at",
    )
    readonly_fields = ("updated_at",)


@admin.register(WhatsAppBatchSchedule)
class WhatsAppBatchScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "scheduled_at",
        "outbound_template_name",
        "status",
        "sent_count",
        "created_at",
        "completed_at",
    )
    list_filter = ("status",)
    ordering = ("-scheduled_at", "-id")
    readonly_fields = ("created_at", "started_at", "completed_at", "sent_count")
