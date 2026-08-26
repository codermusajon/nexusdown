from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
import uuid

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    is_premium = models.BooleanField(default=False)
    premium_expires_at = models.DateTimeField(null=True, blank=True)
    telegram_username = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_premium_active(self):
        if not self.is_premium:
            return False
        if self.premium_expires_at and timezone.now() > self.premium_expires_at:
            return False
        return True

    def __str__(self):
        status = "PREMIUM" if self.is_premium_active else "FREE"
        return f"{self.user.username} ({status})"


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()


class DailySearchTracker(models.Model):
    identifier = models.CharField(max_length=150, db_index=True)
    date = models.DateField(default=timezone.now, db_index=True)
    search_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ('identifier', 'date')

    def __str__(self):
        return f"{self.identifier} on {self.date}: {self.search_count} searches"


class EmailVerificationCode(models.Model):
    email = models.EmailField(db_index=True)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.IntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    user_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} - Code: {self.code} (Verified: {self.is_verified})"


class DownloadRecord(models.Model):
    MEDIA_TYPES = [
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('file', 'Direct File'),
        ('image_pdf', 'Image / Document'),
    ]

    STATUS_CHOICES = [
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500, default='Untitled Download')
    original_url = models.TextField(blank=True, default='')
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES, default='video')
    format_label = models.CharField(max_length=50, default='mp4')
    file_name = models.CharField(max_length=500, blank=True, default='')
    file_path = models.CharField(max_length=1000, blank=True, default='')
    file_size = models.BigIntegerField(default=0)
    duration_seconds = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='processing')
    user_id = models.CharField(max_length=100, db_index=True, blank=True, default='')
    client_ip = models.CharField(max_length=45, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def download_url(self):
        import os
        from django.conf import settings
        if self.file_path and os.path.exists(self.file_path):
            return f"/download/{self.id}/"
        if self.file_name and os.path.exists(os.path.join(settings.DOWNLOADS_DIR, self.file_name)):
            return f"/download/{self.id}/"
        if self.original_url and (self.original_url.startswith('http://') or self.original_url.startswith('https://')):
            return self.original_url
        return ''

    def __str__(self):
        return f"{self.title} ({self.format_label}) - {self.status}"


