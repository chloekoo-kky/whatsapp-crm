# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0008_clinic_shop_type"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="clinic", name="leads_shop_ty_idx"),
        migrations.RenameField(
            model_name="clinic",
            old_name="shop_type",
            new_name="shop_keyword",
        ),
        migrations.AlterField(
            model_name="clinic",
            name="shop_keyword",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Keyword the user entered before the hunt (e.g. medical clinic, café, boutique).",
                max_length=160,
            ),
        ),
        migrations.AddIndex(
            model_name="clinic",
            index=models.Index(fields=["shop_keyword"], name="leads_shop_kw_idx"),
        ),
    ]
