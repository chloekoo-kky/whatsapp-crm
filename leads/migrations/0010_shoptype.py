# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0009_shop_keyword"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopType",
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
                ("name", models.CharField(max_length=120, unique=True)),
                (
                    "maps_query_default",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Shop type",
                "verbose_name_plural": "Shop types",
                "ordering": ["name"],
            },
        ),
    ]
