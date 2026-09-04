# Add the Ready pipeline folder and pin system-view sort order.

from django.db import migrations


READY_GROUP_NAME = "ready"
SYSTEM_GROUP_SORT_ORDERS = {
    "Uncategorized": 0,
    "ready": 1,
    "queue": 2,
    "🚫 Trash": 3,
    "whatsapp": 4,
}


def create_ready_group(apps, schema_editor):
    LeadGroup = apps.get_model("leads", "LeadGroup")
    group, _ = LeadGroup.objects.get_or_create(
        name=READY_GROUP_NAME,
        defaults={"sort_order": SYSTEM_GROUP_SORT_ORDERS[READY_GROUP_NAME]},
    )
    if group.sort_order != SYSTEM_GROUP_SORT_ORDERS[READY_GROUP_NAME]:
        group.sort_order = SYSTEM_GROUP_SORT_ORDERS[READY_GROUP_NAME]
        group.save(update_fields=["sort_order"])
    for name, sort_order in SYSTEM_GROUP_SORT_ORDERS.items():
        LeadGroup.objects.filter(name=name).exclude(sort_order=sort_order).update(
            sort_order=sort_order
        )


def noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0051_convert_custom_groups_to_tags"),
    ]

    operations = [
        migrations.RunPython(create_ready_group, noop_reverse),
    ]
