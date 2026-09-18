from django.contrib import admin
from .models import UserProfile, DailySearchTracker, EmailVerificationCode, DownloadRecord

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_premium', 'premium_expires_at', 'telegram_username', 'created_at')
    list_filter = ('is_premium', 'created_at')
    search_fields = ('user__username', 'user__email', 'telegram_username')
    actions = ['make_premium', 'revoke_premium']

    @admin.action(description="Grant Premium status")
    def make_premium(self, request, queryset):
        queryset.update(is_premium=True)

    @admin.action(description="Revoke Premium status")
    def revoke_premium(self, request, queryset):
        queryset.update(is_premium=False)


@admin.register(DailySearchTracker)
class DailySearchTrackerAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'date', 'search_count')
    list_filter = ('date',)
    search_fields = ('identifier',)


@admin.register(EmailVerificationCode)
class EmailVerificationCodeAdmin(admin.ModelAdmin):
    list_display = ('email', 'code', 'created_at', 'expires_at', 'attempts', 'is_verified')
    list_filter = ('is_verified', 'created_at')
    search_fields = ('email', 'code')


@admin.register(DownloadRecord)
class DownloadRecordAdmin(admin.ModelAdmin):
    list_display = ('title', 'media_type', 'format_label', 'owner', 'guest_id', 'client_ip', 'status', 'created_at')
    list_filter = ('media_type', 'status', 'created_at')
    list_select_related = ('owner',)
    raw_id_fields = ('owner',)
    search_fields = ('title', 'owner__email', 'owner__username', 'guest_id', 'client_ip', 'original_url')
