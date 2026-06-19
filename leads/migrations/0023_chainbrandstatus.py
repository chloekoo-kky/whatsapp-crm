from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0022_leadconversationlog"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChainBrandStatus",
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
                    "brand_key",
                    models.CharField(
                        help_text="Lowercased, trimmed business name used as the chain group key.",
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "chain_contacted",
                    models.BooleanField(
                        default=False,
                        help_text="User marked the entire chain group as contacted.",
                    ),
                ),
                (
                    "exempt_from_spam",
                    models.BooleanField(
                        default=False,
                        help_text="Exclude this chain from further outreach / spamming.",
                    ),
                ),
                ("contacted_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Chain brand status",
                "verbose_name_plural": "Chain brand statuses",
                "db_table": "leads_chainbrandstatus",
            },
        ),
    ]
