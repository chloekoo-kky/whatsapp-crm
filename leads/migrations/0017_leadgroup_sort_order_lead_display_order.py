from django.db import migrations, models


def backfill_leadgroup_sort_order(apps, schema_editor):
    LeadGroup = apps.get_model("leads", "LeadGroup")
    for i, g in enumerate(LeadGroup.objects.all().order_by("name", "pk")):
        g.sort_order = i
        g.save(update_fields=["sort_order"])


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0016_huntrefinerecord_secondary_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="leadgroup",
            name="sort_order",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Lower numbers appear first in the dashboard tabs (user reorderable).",
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="display_order",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Manual sort in list/grid within a folder; ties break by created_at.",
            ),
        ),
        migrations.AlterModelOptions(
            name="leadgroup",
            options={
                "ordering": ["sort_order", "name"],
                "verbose_name": "Lead group",
                "verbose_name_plural": "Lead groups",
            },
        ),
        migrations.AlterModelOptions(
            name="lead",
            options={
                "ordering": ["display_order", "-created_at"],
                "verbose_name": "Lead",
                "verbose_name_plural": "Leads",
            },
        ),
        migrations.RunPython(backfill_leadgroup_sort_order, migrations.RunPython.noop),
    ]
