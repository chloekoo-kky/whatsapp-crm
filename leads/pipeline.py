"""System pipeline folders, phone deduplication, and WhatsApp queue group rules."""

from __future__ import annotations

from typing import Iterable, Optional

from django.db.models import Max, Q

from leads.display import lead_has_dispatchable_phone, lead_phone_list, normalize_manual_phone
from leads.models import Lead, LeadGroup

UNCATEGORIZED_GROUP_NAME = "Uncategorized"
QUEUE_GROUP_NAME = "queue"
TRASH_GROUP_NAME = "🚫 Trash"
WHATSAPP_CHATS_GROUP_NAME = "whatsapp"
LEGACY_JUNK_GROUP_NAME = "Junk"

SYSTEM_GROUP_SORT_ORDERS = {
    UNCATEGORIZED_GROUP_NAME: 0,
    QUEUE_GROUP_NAME: 1,
    TRASH_GROUP_NAME: 2,
    WHATSAPP_CHATS_GROUP_NAME: 3,
}

WHATSAPP_PROTECTED_STATUSES = frozenset(
    {
        Lead.WhatsappStatus.PROCESSING,
    }
)

WHATSAPP_AUTOMATOR_ACTIVE_STATUSES = frozenset(
    {
        Lead.WhatsappStatus.PENDING,
        Lead.WhatsappStatus.PROCESSING,
    }
)


def phone_dedup_key(phone: str) -> str:
    """Canonical comparison key for import-time deduplication."""
    normalized = normalize_manual_phone((phone or "").strip())
    if normalized:
        return normalized
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return digits


def _digits_only(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def phone_exists_in_database(phone: str, *, exclude_pk: Optional[int] = None) -> bool:
    """
    True when ``phone`` matches any stored primary or JSON phone on another lead.
    Used during Serper import to avoid contacting the same number twice.
    """
    key = phone_dedup_key(phone)
    if not key:
        return False

    qs = Lead.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)

    if key.startswith("+"):
        if qs.filter(phone_number=key).exists():
            return True
        if qs.filter(phone_numbers__contains=[key]).exists():
            return True

    digits = _digits_only(key)
    if len(digits) < 8:
        return False

    narrow = qs.filter(
        Q(phone_number__icontains=digits[-8:])
        | Q(phone_numbers__icontains=digits[-8:])
    ).only("pk", "phone_number", "phone_numbers")

    for lead in narrow.iterator(chunk_size=200):
        for raw in lead_phone_list(lead):
            if _digits_only(phone_dedup_key(raw)) == digits:
                return True
    return False


def find_lead_by_phone(phone: str) -> Optional[Lead]:
    """Return the first lead whose stored numbers match ``phone`` (E.164-aware)."""
    key = phone_dedup_key(phone)
    if not key:
        return None

    qs = Lead.objects.select_related("group").all()

    if key.startswith("+"):
        lead = qs.filter(phone_number=key).first()
        if lead:
            return lead
        lead = qs.filter(phone_numbers__contains=[key]).first()
        if lead:
            return lead

    digits = _digits_only(key)
    if len(digits) < 8:
        return None

    narrow = qs.filter(
        Q(phone_number__icontains=digits[-8:])
        | Q(phone_numbers__icontains=digits[-8:])
    ).only("pk", "phone_number", "phone_numbers", "group_id")

    for lead in narrow.iterator(chunk_size=200):
        for raw in lead_phone_list(lead):
            if _digits_only(phone_dedup_key(raw)) == digits:
                return lead
    return None


def _pin_group_sort_order(group: LeadGroup, sort_order: int) -> LeadGroup:
    if group.sort_order != sort_order:
        group.sort_order = sort_order
        group.save(update_fields=["sort_order"])
    return group


def get_or_create_uncategorized_group() -> LeadGroup:
    group, _ = LeadGroup.objects.get_or_create(
        name=UNCATEGORIZED_GROUP_NAME,
        defaults={"sort_order": SYSTEM_GROUP_SORT_ORDERS[UNCATEGORIZED_GROUP_NAME]},
    )
    return _pin_group_sort_order(group, SYSTEM_GROUP_SORT_ORDERS[UNCATEGORIZED_GROUP_NAME])


def get_or_create_queue_group() -> LeadGroup:
    group, _ = LeadGroup.objects.get_or_create(
        name=QUEUE_GROUP_NAME,
        defaults={"sort_order": SYSTEM_GROUP_SORT_ORDERS[QUEUE_GROUP_NAME]},
    )
    return _pin_group_sort_order(group, SYSTEM_GROUP_SORT_ORDERS[QUEUE_GROUP_NAME])


def get_or_create_whatsapp_chats_group() -> LeadGroup:
    """Virtual Active Chat inbox tab (awaiting client replies across all groups)."""
    group, _ = LeadGroup.objects.get_or_create(
        name=WHATSAPP_CHATS_GROUP_NAME,
        defaults={"sort_order": SYSTEM_GROUP_SORT_ORDERS[WHATSAPP_CHATS_GROUP_NAME]},
    )
    return _pin_group_sort_order(
        group, SYSTEM_GROUP_SORT_ORDERS[WHATSAPP_CHATS_GROUP_NAME]
    )


def get_or_create_trash_group() -> LeadGroup:
    legacy = LeadGroup.objects.filter(name=LEGACY_JUNK_GROUP_NAME).first()
    if legacy:
        legacy.name = TRASH_GROUP_NAME
        legacy.save(update_fields=["name"])
        return _pin_group_sort_order(legacy, SYSTEM_GROUP_SORT_ORDERS[TRASH_GROUP_NAME])

    group, _ = LeadGroup.objects.get_or_create(
        name=TRASH_GROUP_NAME,
        defaults={"sort_order": SYSTEM_GROUP_SORT_ORDERS[TRASH_GROUP_NAME]},
    )
    return _pin_group_sort_order(group, SYSTEM_GROUP_SORT_ORDERS[TRASH_GROUP_NAME])


def ensure_pipeline_system_groups() -> dict[str, LeadGroup]:
    """Create or repair the foundational pipeline folders."""
    return {
        "uncategorized": get_or_create_uncategorized_group(),
        "queue": get_or_create_queue_group(),
        "whatsapp_chats": get_or_create_whatsapp_chats_group(),
        "trash": get_or_create_trash_group(),
    }


def uncategorized_group_filter() -> Q:
    """Match leads in the Uncategorized folder (including legacy null FK rows)."""
    uncategorized = get_or_create_uncategorized_group()
    return Q(group_id=uncategorized.pk) | Q(group__isnull=True)


def next_display_order_for_group(group_id: int) -> int:
    """Next ``display_order`` slot at the bottom of a folder tab."""
    current_max = (
        Lead.objects.filter(group_id=group_id).aggregate(m=Max("display_order"))["m"] or 0
    )
    return current_max + 1


def sink_lead_display_order(lead: Lead) -> int:
    """Return a ``display_order`` value that places the lead at the tab bottom."""
    group_id = lead.group_id
    if group_id is None:
        uncategorized = get_or_create_uncategorized_group()
        group_id = uncategorized.pk
    return next_display_order_for_group(group_id)


def enqueue_leads_for_whatsapp(lead_ids: Iterable[int]) -> int:
    """Mark eligible leads pending for WhatsApp outreach without changing their folder."""
    ids = list(lead_ids)
    if not ids:
        return 0

    updated = 0
    for lead in Lead.objects.filter(pk__in=ids).iterator():
        if lead.whatsapp_status in WHATSAPP_PROTECTED_STATUSES:
            continue
        if not lead_has_dispatchable_phone(lead):
            continue
        lead.whatsapp_status = Lead.WhatsappStatus.PENDING
        lead.whatsapp_last_error = ""
        lead.save(update_fields=["whatsapp_status", "whatsapp_last_error"])
        updated += 1
    return updated


def apply_group_assignment_side_effects(
    leads_before: list[Lead],
    target_group: Optional[LeadGroup],
) -> None:
    """
    Pending automator state is only allowed inside the queue folder.
    Moving into queue activates pending; moving out returns leads to idle.
    """
    queue_group = get_or_create_queue_group()
    uncategorized_group = get_or_create_uncategorized_group()
    queue_pk = queue_group.pk

    if target_group is None:
        target_group = uncategorized_group

    moving_to_queue = target_group.pk == queue_pk

    if moving_to_queue:
        enqueue_ids = [
            lead.pk
            for lead in leads_before
            if lead.whatsapp_status not in WHATSAPP_PROTECTED_STATUSES
            and lead_has_dispatchable_phone(lead)
        ]
        if enqueue_ids:
            Lead.objects.filter(pk__in=enqueue_ids).update(
                whatsapp_status=Lead.WhatsappStatus.PENDING,
                whatsapp_last_error="",
            )
        return

    leaving_queue_ids = [
        lead.pk
        for lead in leads_before
        if lead.group_id == queue_pk
        and lead.whatsapp_status in WHATSAPP_AUTOMATOR_ACTIVE_STATUSES
    ]
    if leaving_queue_ids:
        Lead.objects.filter(pk__in=leaving_queue_ids).update(
            whatsapp_status=Lead.WhatsappStatus.IDLE,
            whatsapp_last_error="",
        )


def queue_group_lead_queryset():
    """Pending leads eligible for the outbound daemon (any native folder)."""
    return Lead.objects.filter(
        whatsapp_status=Lead.WhatsappStatus.PENDING
    ).exclude(group__name=TRASH_GROUP_NAME)
