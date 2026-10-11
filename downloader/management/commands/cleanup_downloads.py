from django.conf import settings
from django.core.management.base import BaseCommand

from downloader.services import cleanup_old_downloads


class Command(BaseCommand):
    help = "Delete server-side downloads/conversions older than DOWNLOAD_RETENTION_HOURS (or --hours)."

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=float, default=None, help='Override the retention period.')

    def handle(self, *args, **options):
        hours = options['hours'] if options['hours'] is not None else settings.DOWNLOAD_RETENTION_HOURS
        removed = cleanup_old_downloads(settings.DOWNLOADS_DIR, hours * 3600)
        self.stdout.write(f"Removed {removed} file(s) older than {hours:g}h from {settings.DOWNLOADS_DIR}")
