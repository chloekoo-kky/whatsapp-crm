from django.db import migrations, models


def seed_category_types(apps, schema_editor):
    LeadCategoryType = apps.get_model("leads", "LeadCategoryType")
    rows = [
        ("unknown", "Unknown", 0, True),
        ("invalid", "Invalid / irrelevant", 1, True),
        ("gp", "GP", 10, False),
        ("aesthetic", "Aesthetic", 20, False),
        ("dental", "Dental", 30, False),
        ("fitness", "Fitness / gym / yoga", 40, False),
        ("cafe", "Café / restaurant / F&B", 50, False),
        ("retail", "Retail / shop", 60, False),
        ("service", "Services / other business", 70, False),
    ]
    for slug, label, sort_order, is_system in rows:
        LeadCategoryType.objects.update_or_create(
            slug=slug,
            defaults={
                "label": label,
                "sort_order": sort_order,
                "is_system": is_system,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0039_whatsappconfig_force_send_template_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="LeadCategoryType",
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
                (
                    "slug",
                    models.SlugField(
                        help_text="Stored on Lead.category (lowercase, e.g. dental, gp).",
                        max_length=32,
                        unique=True,
                    ),
                ),
                ("label", models.CharField(max_length=80)),
                ("sort_order", models.PositiveSmallIntegerField(default=100)),
                (
                    "is_system",
                    models.BooleanField(
                        default=False,
                        help_text="System categories (Unknown, Invalid) cannot be deleted.",
                    ),
                ),
            ],
            options={
                "verbose_name": "Category type",
                "verbose_name_plural": "Category types",
                "db_table": "leads_leadcategorytype",
                "ordering": ["sort_order", "label", "slug"],
            },
        ),
        migrations.AlterField(
            model_name="lead",
            name="category",
            field=models.CharField(
                default="unknown",
                help_text="Business type / relevance — rules, AI, or manual update.",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="categoryrule",
            name="category",
            field=models.CharField(
                help_text="Lead.category slug assigned when the rule matches.",
                max_length=32,
            ),
        ),
        migrations.RunPython(seed_category_types, migrations.RunPython.noop),
    ]
