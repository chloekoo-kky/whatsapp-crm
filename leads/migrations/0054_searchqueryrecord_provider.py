from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0053_lead_assigned_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="searchqueryrecord",
            name="provider",
            field=models.CharField(
                db_index=True,
                default="serper",
                help_text="Maps provider used for this hunt (serper or outscraper).",
                max_length=20,
            ),
        ),
    ]
