"""Lead classification helpers. Live lookups use Tag."""

from __future__ import annotations

from django.utils.text import slugify

UNKNOWN_SLUG = "unknown"
INVALID_SLUG = "invalid"

DEFAULT_CATEGORY_TYPES: list[tuple[str, str, int, bool]] = [
    (UNKNOWN_SLUG, "Unknown", 0, True),
    (INVALID_SLUG, "Invalid / irrelevant", 1, True),
    ("dental", "Dental", 10, False),
    ("aesthetic", "Aesthetic", 20, False),
    ("gp", "GP", 30, False),
    ("fitness", "Fitness / gym / yoga", 40, False),
    ("cafe", "Café / restaurant / F&B", 50, False),
    ("retail", "Retail / shop", 60, False),
    ("service", "Services / other business", 70, False),
]


def lead_category_choices() -> list[tuple[str, str]]:
    from leads.models import Tag

    return list(
        Tag.objects.order_by("sort_order", "label", "slug").values_list("slug", "label")
    )


def category_label_for(slug: str) -> str:
    from leads.models import Tag

    key = (slug or UNKNOWN_SLUG).strip().lower()
    row = Tag.objects.filter(slug=key).values_list("label", flat=True).first()
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
    from leads.models import Tag

    key = (slug or "").strip().lower()
    if not key:
        return False
    return Tag.objects.filter(slug=key).exists()
