from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0043_alter_whatsappconfig_free_text_templates'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='delivery_status',
            field=models.CharField(blank=True, default='', help_text="Outbound delivery state; 'failed' rows are hidden from the chat feed.", max_length=16),
        ),
    ]
