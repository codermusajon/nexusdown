from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from downloader.models import UserProfile

class Command(BaseCommand):
    help = 'Grant or revoke premium status for a user by username or email'

    def add_arguments(self, parser):
        parser.add_argument('user_identifier', type=str, help='Username or email of the user')
        parser.add_argument('--revoke', action='store_true', help='Revoke premium status')

    def handle(self, *args, **options):
        identifier = options['user_identifier']
        revoke = options['revoke']

        user = User.objects.filter(username=identifier).first() or User.objects.filter(email=identifier).first()
        if not user:
            self.stderr.write(self.style.ERROR(f"User '{identifier}' not found."))
            return

        profile, _ = UserProfile.objects.get_or_create(user=user)
        if revoke:
            profile.is_premium = False
            profile.save()
            self.stdout.write(self.style.SUCCESS(f"Revoked Premium status for '{user.username}'."))
        else:
            profile.is_premium = True
            profile.save()
            self.stdout.write(self.style.SUCCESS(f"Granted Premium status to '{user.username}'."))
