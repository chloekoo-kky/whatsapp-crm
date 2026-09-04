from django.db import migrations, models
from django.db.models import Count


def backfill_leads_created(apps, schema_editor):
    SearchQueryRecord = apps.get_model("leads", "SearchQueryRecord")
    Lead = apps.get_model("leads", "Lead")
    counts = {
        row["search_query_record_id"]: row["n"]
        for row in (
            Lead.objects.filter(search_query_record_id__isnull=False)
            .values("search_query_record_id")
            .annotate(n=Count("id"))
        )
    }
    to_update = []
    for rec in SearchQueryRecord.objects.iterator():
        n = counts.get(rec.pk, 0)
        if not n:
            continue
        rec.leads_created = n
        to_update.append(rec)
        if len(to_update) >= 500:
            SearchQueryRecord.objects.bulk_update(to_update, ["leads_created"])
            to_update = []
    if to_update:
        SearchQueryRecord.objects.bulk_update(to_update, ["leads_created"])


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0054_searchqueryrecord_provider"),
    ]

    operations = [
        migrations.AddField(
            model_name="searchqueryrecord",
            name="exclude_keywords",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Exclude terms applied locally after the hunt (not sent to Maps).",
            ),
        ),
        migrations.AddField(
            model_name="searchqueryrecord",
            name="leads_created",
            field=models.PositiveIntegerField(
                default=0,
                help_text="New leads created by this hunt (snapshot at hunt time).",
            ),
        ),
        migrations.AlterField(
            model_name="searchqueryrecord",
            name="provider",
            field=models.CharField(
                choices=[("serper", "Serper"), ("outscraper", "Outscraper")],
                db_index=True,
                default="serper",
                help_text="Maps provider used for this hunt (serper or outscraper).",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_leads_created, migrations.RunPython.noop),
    ]
