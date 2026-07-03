from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0040_leadcategorytype"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconfig",
            name="free_text_template",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Default copy for Active Chat free-form replies. Supports {{ name }} and {{ area }}.",
            ),
        ),
    ]
