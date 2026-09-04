# Convert custom LeadGroup folders into Tags and move those leads to New.

from django.db import migrations
from django.db.models import Max
from django.utils.text import slugify

SYSTEM_LEAD_GROUP_NAMES = (
    "Uncategorized",
    "queue",
    "🚫 Trash",
    "whatsapp",
)


def _unique_slug(Tag, desired: str) -> str:
    slug = desired[:32] or "group"
    base = slug
    n = 2
    while Tag.objects.filter(slug=slug).exists():
        suffix = f"_{n}"
        slug = f"{base[: 32 - len(suffix)]}{suffix}"
        n += 1
    return slug


def convert_custom_groups_to_tags(apps, schema_editor):
    LeadGroup = apps.get_model("leads", "LeadGroup")
    Lead = apps.get_model("leads", "Lead")
    Tag = apps.get_model("leads", "Tag")
    CategoryRule = apps.get_model("leads", "CategoryRule")
    Through = Lead.tags.through

    uncategorized, _ = LeadGroup.objects.get_or_create(
        name="Uncategorized",
        defaults={"sort_order": 0},
    )
    max_sort = Tag.objects.aggregate(m=Max("sort_order"))["m"] or 100

    for group in LeadGroup.objects.exclude(name__in=SYSTEM_LEAD_GROUP_NAMES).order_by(
        "sort_order", "name"
    ):
        label = (group.name or "").strip()[:80]
        if not label:
            Lead.objects.filter(group_id=group.pk).update(group_id=uncategorized.pk)
            group.delete()
            continue

        tag = Tag.objects.filter(label__iexact=label).first()
        if tag is None:
            desired = slugify(label).replace("-", "_")[:32] or f"group_{group.pk}"
            max_sort += 1
            tag = Tag.objects.create(
                slug=_unique_slug(Tag, desired),
                label=label,
                sort_order=max_sort,
                is_system=False,
            )
            if not CategoryRule.objects.filter(category=tag.slug).exists():
                CategoryRule.objects.create(
                    match_phrase=label[:200],
                    category=tag.slug,
                    priority=100,
                )

        lead_ids = list(Lead.objects.filter(group_id=group.pk).values_list("pk", flat=True))
        if lead_ids:
            already = set(
                Through.objects.filter(tag_id=tag.pk, lead_id__in=lead_ids).values_list(
                    "lead_id", flat=True
                )
            )
            Through.objects.bulk_create(
                [
                    Through(lead_id=lid, tag_id=tag.pk)
                    for lid in lead_ids
                    if lid not in already
                ]
            )
            Lead.objects.filter(group_id=group.pk).update(group_id=uncategorized.pk)
        group.delete()


def noop_reverse(apps, schema_editor):
    """Custom folders cannot be reconstructed from tags alone."""


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0050_remove_invalid_tag_and_unknown_rules"),
    ]

    operations = [
        migrations.RunPython(convert_custom_groups_to_tags, noop_reverse),
    ]
