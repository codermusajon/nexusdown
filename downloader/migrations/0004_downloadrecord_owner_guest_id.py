from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def forwards(apps, schema_editor):
    """Map legacy free-text user_id values onto owner (registered) or guest_id (anonymous)."""
    DownloadRecord = apps.get_model('downloader', 'DownloadRecord')
    User = apps.get_model('auth', 'User')

    by_email = {}
    by_username = {}
    for uid, email, username in User.objects.values_list('id', 'email', 'username'):
        if email:
            by_email.setdefault(email.lower(), uid)
        by_username.setdefault(username, uid)

    for record in DownloadRecord.objects.exclude(user_id='').iterator():
        legacy = record.user_id.strip()
        owner_id = by_email.get(legacy.lower()) or by_username.get(legacy)
        if owner_id:
            record.owner_id = owner_id
        else:
            record.guest_id = legacy[:100]
        record.save(update_fields=['owner', 'guest_id'])


def backwards(apps, schema_editor):
    DownloadRecord = apps.get_model('downloader', 'DownloadRecord')
    for record in DownloadRecord.objects.iterator():
        if record.owner_id:
            record.user_id = record.owner.email or record.owner.username
        else:
            record.user_id = record.guest_id
        record.save(update_fields=['user_id'])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('downloader', '0003_emailverificationcode_dailysearchtracker_userprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='downloadrecord',
            name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='download_records', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='downloadrecord',
            name='guest_id',
            field=models.CharField(blank=True, db_index=True, default='', max_length=100),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='downloadrecord',
            name='user_id',
        ),
    ]
