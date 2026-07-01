"""Lead business category types (dropdown options) stored in the database."""

from __future__ import annotations

from django.utils.text import slugify

UNKNOWN_SLUG = "unknown"
INVALID_SLUG = "invalid"

DEFAULT_CATEGORY_TYPES: list[tuple[str, str, int, bool]] = [
    (UNKNOWN_SLUG, "Unknown", 0, True),
    (INVALID_SLUG, "Invalid / irrelevant", 1, True),
    ("gp", "GP", 10, False),
    ("aesthetic", "Aesthetic", 20, False),
    ("dental", "Dental", 30, False),
    ("fitness", "Fitness / gym / yoga", 40, False),
    ("cafe", "Café / restaurant / F&B", 50, False),
    ("retail", "Retail / shop", 60, False),
    ("service", "Services / other business", 70, False),
]


def lead_category_choices() -> list[tuple[str, str]]:
    from leads.models import LeadCategoryType

    return list(
        LeadCategoryType.objects.order_by("sort_order", "label", "slug").values_list(
            "slug", "label"
        )
    )


def category_label_for(slug: str) -> str:
    from leads.models import LeadCategoryType

    key = (slug or UNKNOWN_SLUG).strip().lower()
    row = LeadCategoryType.objects.filter(slug=key).values_list("label", flat=True).first()
    if row:
        return row
    for s, label, *_ in DEFAULT_CATEGORY_TYPES:
        if s == key:
            return label
    return key.replace("_", " ").title() or "Unknown"


def normalize_category_slug(raw: str, *, fallback_label: str = "") -> str:
    text = (raw or "").strip().lower()
    if text:
        return slugify(text).replace("-", "_")[:32]
    return slugify(fallback_label).replace("-", "_")[:32] or "category"


def is_valid_category_slug(slug: str) -> bool:
    from leads.models import LeadCategoryType

    key = (slug or "").strip().lower()
    if not key:
        return False
    return LeadCategoryType.objects.filter(slug=key).exists()


def ensure_default_category_types() -> None:
    from leads.models import LeadCategoryType

    for slug, label, sort_order, is_system in DEFAULT_CATEGORY_TYPES:
        LeadCategoryType.objects.update_or_create(
            slug=slug,
            defaults={
                "label": label,
                "sort_order": sort_order,
                "is_system": is_system,
            },
        )
