# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0007_whatsapp_draft"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="clinic",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Lead",
                "verbose_name_plural": "Leads",
            },
        ),
        migrations.AddField(
            model_name="clinic",
            name="shop_type",
            field=models.CharField(
                choices=[
                    ("clinic", "Medical clinic"),
                    ("restaurant", "Restaurant / café"),
                    ("retail", "Retail store"),
                    ("beauty", "Beauty / salon"),
                    ("fitness", "Gym / fitness"),
                    ("other", "Other"),
                ],
                default="clinic",
                help_text="Business vertical chosen before the Serper hunt that created or last updated this row.",
                max_length=32,
            ),
        ),
        migrations.AddIndex(
            model_name="clinic",
            index=models.Index(fields=["shop_type"], name="leads_shop_ty_idx"),
        ),
    ]
