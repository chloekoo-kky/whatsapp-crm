# Generated manually

from django.db import migrations, models


def backfill_shop_keyword_from_search_query(apps, schema_editor):
    Clinic = apps.get_model("leads", "Clinic")
    for row in (
        Clinic.objects.exclude(search_query__isnull=True)
        .exclude(search_query="")
        .iterator(chunk_size=500)
    ):
        if (row.shop_keyword or "").strip():
            continue
        row.shop_keyword = (row.search_query or "")[:160]
        row.save(update_fields=["shop_keyword"])


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0010_shoptype"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClinicTypeRule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("match_phrase", models.CharField(max_length=200)),
                (
                    "clinic_type",
                    models.CharField(
                        choices=[
                            ("gp", "GP"),
                            ("aesthetic", "Aesthetic"),
                            ("dental", "Dental"),
                            ("unknown", "Unknown"),
                        ],
                        max_length=32,
                    ),
                ),
                ("priority", models.PositiveSmallIntegerField(default=100)),
            ],
            options={
                "verbose_name": "Clinic type rule",
                "verbose_name_plural": "Clinic type rules",
                "ordering": ["priority", "id"],
            },
        ),
        migrations.RunPython(
            backfill_shop_keyword_from_search_query,
            migrations.RunPython.noop,
        ),
    ]
