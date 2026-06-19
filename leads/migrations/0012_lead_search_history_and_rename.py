# Generated manually — renames Clinic → Lead, ClinicTypeRule → CategoryRule,
# adds SearchQueryRecord, is_processed, search_query_record.

import django.db.models.deletion
from django.db import migrations, models


def backfill_is_processed_from_ai(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    Lead.objects.filter(is_ai_processed=True).update(is_processed=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0011_clinictype_rule_and_backfill_keyword"),
    ]

    operations = [
        migrations.CreateModel(
            name="SearchQueryRecord",
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
                ("keyword", models.CharField(help_text='Hunt keyword (e.g. Fitness Center).', max_length=160)),
                (
                    "maps_search_query",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Maps query fragment used with the city (may match keyword).",
                        max_length=255,
                    ),
                ),
                (
                    "search_city",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="City / area used for the hunt.",
                        max_length=255,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Search query",
                "verbose_name_plural": "Search history",
                "ordering": ["-created_at"],
            },
        ),
        migrations.RenameModel(old_name="Clinic", new_name="Lead"),
        migrations.RenameField(
            model_name="lead",
            old_name="clinic_type",
            new_name="category",
        ),
        migrations.RenameModel(old_name="ClinicTypeRule", new_name="CategoryRule"),
        migrations.RenameField(
            model_name="categoryrule",
            old_name="clinic_type",
            new_name="category",
        ),
        migrations.RemoveConstraint(
            model_name="lead",
            name="unique_clinic_name_address",
        ),
        migrations.RenameIndex(
            model_name="lead",
            new_name="leads_category_idx",
            old_name="leads_cl_ty_idx",
        ),
        migrations.AddField(
            model_name="lead",
            name="is_processed",
            field=models.BooleanField(
                default=False,
                help_text="True when the lead is categorized and ready (AI and/or manual), without pending review.",
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="search_query_record",
            field=models.ForeignKey(
                blank=True,
                help_text="Hunt batch that created or last updated this row from the dashboard.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="leads",
                to="leads.searchqueryrecord",
            ),
        ),
        migrations.AddConstraint(
            model_name="lead",
            constraint=models.UniqueConstraint(fields=("name", "address"), name="unique_lead_name_address"),
        ),
        migrations.AddIndex(
            model_name="lead",
            index=models.Index(fields=["search_query_record"], name="leads_search_rec_idx"),
        ),
        migrations.AlterField(
            model_name="lead",
            name="category",
            field=models.CharField(
                choices=[
                    ("unknown", "Unknown"),
                    ("invalid", "Invalid / irrelevant"),
                    ("gp", "GP"),
                    ("aesthetic", "Aesthetic"),
                    ("dental", "Dental"),
                    ("fitness", "Fitness / gym / yoga"),
                    ("cafe", "Café / restaurant / F&B"),
                    ("retail", "Retail / shop"),
                    ("service", "Services / other business"),
                ],
                default="unknown",
                help_text="Business type / relevance — rules, AI, or manual update.",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="categoryrule",
            name="category",
            field=models.CharField(
                choices=[
                    ("unknown", "Unknown"),
                    ("invalid", "Invalid / irrelevant"),
                    ("gp", "GP"),
                    ("aesthetic", "Aesthetic"),
                    ("dental", "Dental"),
                    ("fitness", "Fitness / gym / yoga"),
                    ("cafe", "Café / restaurant / F&B"),
                    ("retail", "Retail / shop"),
                    ("service", "Services / other business"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterModelOptions(
            name="categoryrule",
            options={
                "ordering": ["priority", "id"],
                "verbose_name": "Category rule",
                "verbose_name_plural": "Category rules",
            },
        ),
        migrations.AlterModelOptions(
            name="lead",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Lead",
                "verbose_name_plural": "Leads",
            },
        ),
        migrations.RunPython(backfill_is_processed_from_ai, noop_reverse),
    ]
