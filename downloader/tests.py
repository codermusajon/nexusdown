from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from .services import YtDlpService
from .models import DownloadRecord, DailySearchTracker
from . import views as downloader_views


class InstagramFallbackParsingTests(SimpleTestCase):
    def test_extracts_video_from_json_payload(self):
        html = '''
        <script type="application/json">
          {"shortcode_media":{"video_url":"https://cdn.example.com/video.mp4","display_url":"https://cdn.example.com/thumb.jpg"}}
        </script>
        '''

        result = YtDlpService._parse_instagram_fallback(
            url="https://www.instagram.com/reel/abc123/",
            page_html=html,
        )

        self.assertEqual(result["video_formats"][0]["download_url"], "https://cdn.example.com/video.mp4")
        self.assertEqual(result["video_formats"][0]["ext"], "mp4")

    def test_extracts_photo_from_open_graph_markup(self):
        html = '''
        <meta property="og:image" content="https://cdn.example.com/photo.jpg" />
        '''

        result = YtDlpService._parse_instagram_fallback(
            url="https://www.instagram.com/p/abc123/",
            page_html=html,
        )

        self.assertEqual(result["video_formats"][0]["download_url"], "https://cdn.example.com/photo.jpg")
        self.assertEqual(result["video_formats"][0]["ext"], "jpg")


class FormatInspectionTests(SimpleTestCase):
    @patch('yt_dlp.YoutubeDL')
    def test_inspect_url_populates_video_formats(self, mock_yt_dlp):
        mock_instance = mock_yt_dlp.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {
            'title': 'Test Video',
            'uploader': 'Test User',
            'duration': 120,
            'thumbnail': 'https://example.com/thumb.jpg',
            'url': 'https://example.com/fallback.mp4',
            'formats': [
                {
                    'format_id': '137',
                    'ext': 'mp4',
                    'vcodec': 'avc1',
                    'acodec': 'none',
                    'height': 1080,
                    'filesize': 10485760,
                    'url': 'https://example.com/1080p.mp4'
                },
                {
                    'format_id': '136',
                    'ext': 'mp4',
                    'vcodec': 'avc1',
                    'acodec': 'none',
                    'height': 720,
                    'filesize': 5242880,
                    'url': 'https://example.com/720p.mp4'
                },
                {
                    'format_id': '140',
                    'ext': 'm4a',
                    'vcodec': 'none',
                    'acodec': 'mp4a.40.2',
                    'url': 'https://example.com/audio.m4a'
                }
            ]
        }

        res = YtDlpService.inspect_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ')

        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['title'], 'Test Video')
        self.assertEqual(res['audio_url'], 'https://example.com/audio.m4a')
        self.assertEqual(len(res['video_formats']), 2)
        self.assertEqual(res['video_formats'][0]['resolution'], '1080p')
        self.assertEqual(res['video_formats'][1]['resolution'], '720p')


class DownloaderViewTests(TestCase):
    def test_index_view_renders_successfully(self):
        response = self.client.get(reverse('downloader:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'NexusDown')

    def test_api_history_returns_empty_list_initially(self):
        response = self.client.get(reverse('downloader:api_history'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {'history': []})


class GoogleAuthApiTests(TestCase):
    def test_auth_me_unauthenticated(self):
        response = self.client.get(reverse('downloader:api_auth_me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()['is_authenticated'])

    def test_google_auth_missing_token(self):
        response = self.client.post(reverse('downloader:api_google_auth'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('downloader.views.verify_google_id_token')
    def test_google_auth_success(self, mock_verify):
        mock_verify.return_value = {
            'email': 'testuser@gmail.com',
            'given_name': 'Test',
            'family_name': 'User',
            'picture': 'https://lh3.googleusercontent.com/a/testavatar'
        }

        response = self.client.post(
            reverse('downloader:api_google_auth'),
            {'id_token': 'fake_token_string'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res_data = response.json()
        self.assertEqual(res_data['status'], 'success')
        self.assertEqual(res_data['user']['email'], 'testuser@gmail.com')
        self.assertEqual(res_data['user']['name'], 'Test User')

        # Check me endpoint after login
        me_res = self.client.get(reverse('downloader:api_auth_me'))
        self.assertTrue(me_res.json()['is_authenticated'])

        # Check logout endpoint
        logout_res = self.client.post(reverse('downloader:api_auth_logout'))
        self.assertEqual(logout_res.status_code, status.HTTP_200_OK)

        # Check me endpoint after logout
        me_res_after = self.client.get(reverse('downloader:api_auth_me'))
        self.assertFalse(me_res_after.json()['is_authenticated'])

    @patch('downloader.views.verify_google_access_token')
    def test_google_auth_access_token_success(self, mock_verify):
        mock_verify.return_value = {
            'email': 'accesstokenuser@gmail.com',
            'given_name': 'Access',
            'family_name': 'TokenUser',
            'picture': 'https://lh3.googleusercontent.com/a/avatar'
        }

        response = self.client.post(
            reverse('downloader:api_google_auth'),
            {'access_token': 'fake_access_token_string'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res_data = response.json()
        self.assertEqual(res_data['status'], 'success')
        self.assertEqual(res_data['user']['email'], 'accesstokenuser@gmail.com')



from django.contrib.auth.models import User

class AuthViewsTests(TestCase):
    def test_login_page_renders_successfully(self):
        response = self.client.get(reverse('downloader:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'NexusDown Hisobi')
        self.assertContains(response, 'Kirish')

    def test_signup_page_renders_successfully(self):
        response = self.client.get(reverse('downloader:signup'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ro\'yxatdan o\'tish')

    def test_api_register_success(self):
        response = self.client.post(
            reverse('downloader:api_auth_register'),
            {
                'username': 'newuser',
                'email': 'newuser@example.com',
                'password': 'password123',
                'first_name': 'New',
                'last_name': 'User'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res_data = response.json()
        self.assertEqual(res_data['status'], 'success')
        self.assertIn('Tasdiqlash kodi', res_data['message'])

        # Step 2: Verify code
        code_obj = EmailVerificationCode.objects.get(email='newuser@example.com')
        verify_res = self.client.post(
            reverse('downloader:api_auth_verify_code'),
            {
                'email': 'newuser@example.com',
                'code': code_obj.code
            },
            format='json'
        )
        self.assertEqual(verify_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(verify_res.json()['user']['username'], 'newuser')

        # Check me endpoint after registration
        me_res = self.client.get(reverse('downloader:api_auth_me'))
        self.assertTrue(me_res.json()['is_authenticated'])


    def test_api_register_duplicate_username(self):
        User.objects.create_user(username='existinguser', email='existing@example.com', password='password123')

        response = self.client.post(
            reverse('downloader:api_auth_register'),
            {
                'username': 'existinguser',
                'email': 'different@example.com',
                'password': 'password123'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('band qilingan', response.json()['error'])

    def test_api_login_success_with_username(self):
        User.objects.create_user(username='john', email='john@example.com', password='secretpassword')

        response = self.client.post(
            reverse('downloader:api_auth_login'),
            {
                'login_id': 'john',
                'password': 'secretpassword'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'success')

    def test_api_login_success_with_email(self):
        User.objects.create_user(username='jane', email='jane@example.com', password='secretpassword')

        response = self.client.post(
            reverse('downloader:api_auth_login'),
            {
                'login_id': 'jane@example.com',
                'password': 'secretpassword'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'success')

    def test_api_login_invalid_password(self):
        User.objects.create_user(username='alex', email='alex@example.com', password='secretpassword')

        response = self.client.post(
            reverse('downloader:api_auth_login'),
            {
                'login_id': 'alex',
                'password': 'wrongpassword'
            },
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('noto\'g\'ri', response.json()['error'])


import os
import tempfile
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from downloader.services import ImageConverterService

class ImageConverterServiceTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.img1_path = os.path.join(self.temp_dir, 'img1.png')
        self.img2_path = os.path.join(self.temp_dir, 'img2.jpg')

        img1 = Image.new('RGB', (200, 300), color='red')
        img1.save(self.img1_path)

        img2 = Image.new('RGB', (400, 200), color='blue')
        img2.save(self.img2_path)

    def test_convert_images_to_pdf_custom_options(self):
        out_pdf = os.path.join(self.temp_dir, 'output.pdf')
        res_path = ImageConverterService.convert_images_to_pdf(
            image_paths=[self.img1_path, self.img2_path],
            output_path=out_pdf,
            rotations=[90, 0],
            page_size='a4',
            orientation='portrait',
            margin_mm=5,
            quality=85,
            page_numbers=True
        )

        self.assertTrue(os.path.exists(res_path))
        self.assertGreater(os.path.getsize(res_path), 0)

    def test_convert_image_format(self):
        out_jpg = os.path.join(self.temp_dir, 'output.jpg')
        res_path = ImageConverterService.convert_image_format(
            input_path=self.img1_path,
            target_format='jpeg',
            output_path=out_jpg,
            rotation=90,
            quality=90
        )

        self.assertTrue(os.path.exists(res_path))
        self.assertGreater(os.path.getsize(res_path), 0)

    def test_create_converted_zip(self):
        out_zip = os.path.join(self.temp_dir, 'output.zip')
        res_path = ImageConverterService.create_converted_zip(
            image_paths=[self.img1_path, self.img2_path],
            output_path=out_zip,
            rotations=[0, 180],
            target_format='pdf',
            page_size='a4'
        )

        self.assertTrue(os.path.exists(res_path))
        self.assertGreater(os.path.getsize(res_path), 0)

    def test_api_convert_images_endpoint(self):
        with open(self.img1_path, 'rb') as f1, open(self.img2_path, 'rb') as f2:
            upload1 = SimpleUploadedFile('test1.png', f1.read(), content_type='image/png')
            upload2 = SimpleUploadedFile('test2.jpg', f2.read(), content_type='image/jpeg')

            response = self.client.post(
                reverse('downloader:api_convert_images'),
                {
                    'images': [upload1, upload2],
                    'target_format': 'pdf',
                    'page_size': 'a4',
                    'orientation': 'auto',
                    'margin': '10',
                    'quality': '80',
                    'page_numbers': 'true',
                    'rotations': '[90, 0]'
                }
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        res_data = response.json()
        self.assertEqual(res_data['status'], 'success')
        self.assertIn('download_url', res_data)


from django.contrib.auth.models import User
from downloader.models import EmailVerificationCode, UserProfile, DailySearchTracker

class TieredQuotasAndVerificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='Password123!'
        )

    def test_send_verification_code_creates_record(self):
        response = self.client.post(reverse('downloader:api_auth_send_code'), {
            'username': 'newuser',
            'email': 'newuser@gmail.com',
            'password': 'Password123!',
            'first_name': 'New',
            'last_name': 'User'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(EmailVerificationCode.objects.filter(email='newuser@gmail.com').count(), 1)
        code_obj = EmailVerificationCode.objects.get(email='newuser@gmail.com')
        self.assertEqual(len(code_obj.code), 6)

    def test_verify_code_creates_user_account(self):
        self.client.post(reverse('downloader:api_auth_send_code'), {
            'username': 'verifieduser',
            'email': 'verified@gmail.com',
            'password': 'Password123!',
        })
        code_obj = EmailVerificationCode.objects.get(email='verified@gmail.com')

        # Test wrong code attempt
        res_fail = self.client.post(reverse('downloader:api_auth_verify_code'), {
            'email': 'verified@gmail.com',
            'code': '000000'
        })
        self.assertEqual(res_fail.status_code, status.HTTP_400_BAD_REQUEST)

        # Test correct code
        res_success = self.client.post(reverse('downloader:api_auth_verify_code'), {
            'email': 'verified@gmail.com',
            'code': code_obj.code
        })
        self.assertEqual(res_success.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username='verifieduser').exists())

    def test_admin_toggle_premium(self):
        admin = User.objects.create_superuser(username='admin', email='admin@test.com', password='AdminPassword123!')
        self.client.force_login(admin)

        response = self.client.post(reverse('downloader:api_admin_toggle_premium'), {
            'user_id': self.user.id,
            'is_premium': True,
            'days': 30
        }, content_type='application/json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.is_premium_active)

    def test_download_file_view(self):
        record = DownloadRecord.objects.create(
            title='Test File',
            file_name='test.txt',
            file_path='',
            original_url='https://example.com/test.mp4',
            status='completed',
            guest_id='usr_guest_abc123',
        )
        url = reverse('downloader:download_file', kwargs={'record_id': str(record.id)})
        # A different browser (no matching guest id) cannot fetch someone else's record.
        self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.get(url, HTTP_X_USER_ID='usr_guest_abc123')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.com/test.mp4')


class InspectQuotaAndLockTests(TestCase):
    def setUp(self):
        safe_patch = patch('downloader.views.is_safe_public_url', return_value=True)
        safe_patch.start()
        self.addCleanup(safe_patch.stop)
        self.inspect_url = reverse('downloader:api_inspect')
        self.payload = {'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'}
        self.inspect_ok = {
            'status': 'success',
            'title': 'Sample',
            'uploader': 'Channel',
            'duration': 30,
            'thumbnail': 'https://example.com/thumb.jpg',
            'audio_url': 'https://example.com/audio.m4a',
            'video_formats': [
                {
                    'format_id': '137',
                    'ext': 'mp4',
                    'resolution': '1080p',
                    'height': 1080,
                    'download_url': 'https://example.com/1080p.mp4',
                    'label': '1080p',
                },
                {
                    'format_id': '313',
                    'ext': 'mp4',
                    'resolution': '2160p',
                    'height': 2160,
                    'download_url': 'https://example.com/2160p.mp4',
                    'label': '2160p',
                },
            ],
        }

    def test_inspect_requires_url(self):
        response = self.client.post(self.inspect_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('URL', response.json()['error'])

    @patch('downloader.views.YtDlpService.inspect_url')
    def test_guest_inspect_succeeds_and_locks_4k(self, mock_inspect):
        mock_inspect.return_value = self.inspect_ok
        response = self.client.post(self.inspect_url, self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        unlocked = next(fmt for fmt in data['video_formats'] if fmt['height'] == 1080)
        locked = next(fmt for fmt in data['video_formats'] if fmt['height'] == 2160)
        self.assertFalse(unlocked.get('is_locked'))
        self.assertTrue(locked['is_locked'])
        self.assertEqual(locked['download_url'], '#premium_required')
        # The real format id must not leak, or the lock is bypassable via /api/download-media/
        self.assertEqual(locked['format_id'], 'premium_required')
        self.assertEqual(data['quota_info']['user_type'], 'unregistered')
        self.assertEqual(data['quota_info']['searches_today'], 1)

    @patch('downloader.views.YtDlpService.inspect_url')
    def test_guest_hits_daily_limit_of_two(self, mock_inspect):
        mock_inspect.return_value = self.inspect_ok
        self.assertEqual(self.client.post(self.inspect_url, self.payload, format='json').status_code, 200)
        self.assertEqual(self.client.post(self.inspect_url, self.payload, format='json').status_code, 200)
        blocked = self.client.post(self.inspect_url, self.payload, format='json')
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(blocked.json()['error_code'], 'UNREGISTERED_LIMIT_REACHED')
        self.assertEqual(mock_inspect.call_count, 2)

    @patch('downloader.views.YtDlpService.inspect_url')
    def test_registered_user_hits_daily_limit_of_ten(self, mock_inspect):
        user = User.objects.create_user(username='quota_user', email='quota@example.com', password='Password123!')
        self.client.force_login(user)
        DailySearchTracker.objects.create(
            identifier=f'user_{user.id}',
            date=timezone.now().date(),
            search_count=10,
        )
        blocked = self.client.post(self.inspect_url, self.payload, format='json')
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(blocked.json()['error_code'], 'REGISTERED_LIMIT_REACHED')
        mock_inspect.assert_not_called()

    @patch('downloader.views.YtDlpService.inspect_url')
    def test_premium_user_keeps_4k_and_skips_quota(self, mock_inspect):
        user = User.objects.create_user(username='pro_user', email='pro@example.com', password='Password123!')
        user.profile.is_premium = True
        user.profile.save()
        self.client.force_login(user)
        mock_inspect.return_value = self.inspect_ok
        response = self.client.post(self.inspect_url, self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        locked_flags = [fmt.get('is_locked') for fmt in data['video_formats']]
        self.assertTrue(all(not flag for flag in locked_flags))
        self.assertEqual(data['quota_info']['user_type'], 'premium')
        self.assertTrue(data['quota_info']['is_premium'])
        self.assertIsNone(data['quota_info']['max_searches'])

    def test_failed_inspect_does_not_consume_quota(self):
        with patch('downloader.views.YtDlpService.inspect_url') as mock_inspect:
            mock_inspect.return_value = {'status': 'error', 'error': 'Unsupported URL'}
            response = self.client.post(self.inspect_url, self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(DailySearchTracker.objects.count(), 1)
        self.assertEqual(DailySearchTracker.objects.first().search_count, 0)


class HistoryAndAdminApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='hist', email='hist@example.com', password='Password123!')
        self.other = User.objects.create_user(username='other', email='other@example.com', password='Password123!')
        self.own = DownloadRecord.objects.create(
            title='Mine',
            original_url='https://example.com/a.mp4',
            owner=self.user,
            status='completed',
        )
        self.foreign = DownloadRecord.objects.create(
            title='Theirs',
            original_url='https://example.com/b.mp4',
            owner=self.other,
            status='completed',
        )

    def test_history_is_scoped_to_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('downloader:api_history'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [item['title'] for item in response.json()['history']]
        self.assertEqual(titles, ['Mine'])

    def test_delete_history_rejects_foreign_records(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('downloader:api_delete_history'),
            {'id': str(self.foreign.id)},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(DownloadRecord.objects.filter(id=self.foreign.id).exists())

    def test_delete_and_clear_own_history(self):
        self.client.force_login(self.user)
        deleted = self.client.post(
            reverse('downloader:api_delete_history'),
            {'id': str(self.own.id)},
            format='json',
        )
        self.assertEqual(deleted.status_code, status.HTTP_200_OK)
        extra = DownloadRecord.objects.create(
            title='Second',
            original_url='https://example.com/c.mp4',
            owner=self.user,
            status='completed',
        )
        cleared = self.client.post(reverse('downloader:api_clear_history'), {}, format='json')
        self.assertEqual(cleared.status_code, status.HTTP_200_OK)
        self.assertEqual(cleared.json()['deleted_count'], 1)
        self.assertFalse(DownloadRecord.objects.filter(id=extra.id).exists())
        self.assertTrue(DownloadRecord.objects.filter(id=self.foreign.id).exists())

    def test_admin_apis_require_staff(self):
        self.client.force_login(self.user)
        users = self.client.get(reverse('downloader:api_admin_users'))
        history = self.client.get(reverse('downloader:api_admin_history'))
        toggle = self.client.post(
            reverse('downloader:api_admin_toggle_premium'),
            {'user_id': self.other.id, 'is_premium': True, 'days': 7},
            format='json',
        )
        dashboard = self.client.get(reverse('downloader:admin_dashboard'))
        self.assertEqual(users.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(history.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(toggle.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(dashboard.status_code, 302)

    def test_staff_can_list_users_and_history(self):
        admin = User.objects.create_superuser(username='boss', email='boss@test.com', password='AdminPassword123!')
        self.client.force_login(admin)
        users = self.client.get(reverse('downloader:api_admin_users'))
        history = self.client.get(reverse('downloader:api_admin_history') + '?query=Mine')
        self.assertEqual(users.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(users.json()['users']), 3)
        self.assertEqual(history.status_code, status.HTTP_200_OK)
        self.assertEqual(history.json()['history'][0]['title'], 'Mine')

    def test_expired_premium_is_not_active(self):
        self.user.profile.is_premium = True
        self.user.profile.premium_expires_at = timezone.now() - timedelta(days=1)
        self.user.profile.save()
        self.assertFalse(self.user.profile.is_premium_active)

    def test_convert_images_rejects_empty_upload(self):
        response = self.client.post(reverse('downloader:api_convert_images'), {'target_format': 'pdf'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_download_missing_record_returns_404(self):
        response = self.client.get(
            reverse('downloader:download_file', kwargs={'record_id': '00000000-0000-0000-0000-000000000000'})
        )
        self.assertEqual(response.status_code, 404)

    def test_login_requires_credentials(self):
        response = self.client.post(reverse('downloader:api_auth_login'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_auth_me_reports_guest_quota(self):
        response = self.client.get(reverse('downloader:api_auth_me'))
        quota = response.json()['quota']
        self.assertEqual(quota['user_type'], 'unregistered')
        self.assertEqual(quota['max_searches'], 2)







class OwnershipSecurityTests(TestCase):
    """Regression tests for the client-controlled identity bugs."""

    def setUp(self):
        self.victim = User.objects.create_user(username='victim', email='victim@example.com', password='Password123!')
        self.attacker = User.objects.create_user(username='attacker', email='attacker@example.com', password='Password123!')
        self.victim_record = DownloadRecord.objects.create(title='Private', original_url='https://example.com/v.mp4', owner=self.victim)
        self.guest_record = DownloadRecord.objects.create(title='Guest', original_url='https://example.com/g.mp4', guest_id='usr_abc_123456')

    def test_email_in_x_user_id_header_is_ignored(self):
        response = self.client.get(reverse('downloader:api_history'), HTTP_X_USER_ID='victim@example.com')
        self.assertEqual(response.json()['history'], [])

    def test_login_cannot_claim_another_users_records(self):
        self.client.cookies['user_unique_id'] = 'victim@example.com'
        response = self.client.post(
            reverse('downloader:api_auth_login'),
            {'login_id': 'attacker', 'password': 'Password123!'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.victim_record.refresh_from_db()
        self.assertEqual(self.victim_record.owner, self.victim)

    def test_login_claims_own_guest_records(self):
        self.client.cookies['user_unique_id'] = 'usr_abc_123456'
        response = self.client.post(
            reverse('downloader:api_auth_login'),
            {'login_id': 'attacker', 'password': 'Password123!'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.guest_record.refresh_from_db()
        self.assertEqual(self.guest_record.owner, self.attacker)

    def test_guest_sees_only_records_with_matching_guest_id(self):
        response = self.client.get(reverse('downloader:api_history'), HTTP_X_USER_ID='usr_abc_123456')
        self.assertEqual([r['title'] for r in response.json()['history']], ['Guest'])
        response = self.client.get(reverse('downloader:api_history'), HTTP_X_USER_ID='usr_other_999999')
        self.assertEqual(response.json()['history'], [])

    def test_history_query_param_user_id_is_ignored(self):
        response = self.client.get(reverse('downloader:api_history') + '?user_id=usr_abc_123456')
        self.assertEqual(response.json()['history'], [])

    @patch('downloader.views.is_safe_public_url', return_value=True)
    @patch('downloader.views.YtDlpService.inspect_url')
    def test_guest_quota_is_not_reset_by_rotating_guest_id(self, mock_inspect, _safe):
        mock_inspect.return_value = {'status': 'success', 'title': 'x', 'video_formats': []}
        url = reverse('downloader:api_inspect')
        payload = {'url': 'https://www.youtube.com/watch?v=abc'}
        self.assertEqual(self.client.post(url, payload, format='json', HTTP_X_USER_ID='usr_one_111111').status_code, 200)
        self.assertEqual(self.client.post(url, payload, format='json', HTTP_X_USER_ID='usr_two_222222').status_code, 200)
        blocked = self.client.post(url, payload, format='json', HTTP_X_USER_ID='usr_three_33333')
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_history_shows_owner_label(self):
        admin = User.objects.create_superuser(username='root', email='root@test.com', password='AdminPassword123!')
        self.client.force_login(admin)
        response = self.client.get(reverse('downloader:api_admin_history'))
        labels = {r['title']: r['user_id'] for r in response.json()['history']}
        self.assertEqual(labels['Private'], 'victim@example.com')
        self.assertEqual(labels['Guest'], 'usr_abc_123456')

    def test_admin_toggle_premium_rejects_bad_days(self):
        admin = User.objects.create_superuser(username='root', email='root@test.com', password='AdminPassword123!')
        self.client.force_login(admin)
        response = self.client.post(
            reverse('downloader:api_admin_toggle_premium'),
            {'user_id': self.victim.id, 'is_premium': True, 'days': 'thirty'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_email_rule_is_configurable(self):
        with self.settings(ADMIN_EMAILS=['victim@example.com']):
            response = self.client.post(
                reverse('downloader:api_auth_login'),
                {'login_id': 'victim', 'password': 'Password123!'},
                format='json',
            )
        self.assertEqual(response.status_code, 200)
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.is_superuser)
        self.assertEqual(response.json()['redirect_url'], '/admin-dashboard/')
        # Not configured -> no promotion
        self.attacker.refresh_from_db()
        self.assertFalse(self.attacker.is_superuser)


class DownloadStreamGateTests(TestCase):
    def test_locked_format_is_rejected(self):
        response = self.client.get(
            reverse('downloader:api_download_media_stream'),
            {'original_url': 'https://www.youtube.com/watch?v=abc', 'format_id': 'premium_required'},
        )
        self.assertEqual(response.status_code, 403)

    @patch('downloader.views.YtDlpService.download_media', side_effect=RuntimeError('boom'))
    @patch('downloader.views.is_safe_public_url', return_value=True)
    def test_free_user_download_is_capped_at_1080p(self, _safe, mock_download):
        with patch('downloader.views.safe_stream_get', side_effect=ValueError('no stream')):
            self.client.get(
                reverse('downloader:api_download_media_stream'),
                {'original_url': 'https://www.youtube.com/watch?v=abc', 'url': 'https://cdn.example.com/x.mp4', 'format_id': '313'},
            )
        self.assertEqual(mock_download.call_args.kwargs['max_height'], 1080)

    @patch('downloader.views.is_safe_public_url', return_value=False)
    def test_unsafe_direct_url_is_rejected(self, _safe):
        response = self.client.get(
            reverse('downloader:api_download_media_stream'),
            {'url': 'http://169.254.169.254/latest/meta-data/'},
        )
        self.assertEqual(response.status_code, 404)


class SsrfGuardTests(SimpleTestCase):
    def _addrinfo(self, ip):
        return [(None, None, None, None, (ip, 0))]

    def test_rejects_private_and_metadata_addresses(self):
        for ip in ['127.0.0.1', '10.0.0.5', '192.168.1.1', '169.254.169.254', '0.0.0.0', '::1', 'fd00::1']:
            with patch('downloader.views.socket.getaddrinfo', return_value=self._addrinfo(ip)):
                self.assertFalse(downloader_views.is_safe_public_url('https://host.example/x'), ip)

    def test_rejects_when_any_resolved_address_is_private(self):
        infos = self._addrinfo('93.184.216.34') + self._addrinfo('10.0.0.1')
        with patch('downloader.views.socket.getaddrinfo', return_value=infos):
            self.assertFalse(downloader_views.is_safe_public_url('https://host.example/x'))

    def test_accepts_public_address(self):
        with patch('downloader.views.socket.getaddrinfo', return_value=self._addrinfo('93.184.216.34')):
            self.assertTrue(downloader_views.is_safe_public_url('https://example.com/video.mp4'))

    def test_rejects_non_http_schemes(self):
        self.assertFalse(downloader_views.is_safe_public_url('file:///etc/passwd'))
        self.assertFalse(downloader_views.is_safe_public_url('ftp://example.com/x'))

    def test_inspect_rejects_internal_url(self):
        with patch('downloader.views.socket.getaddrinfo', return_value=self._addrinfo('10.0.0.1')):
            response = self.client.post(reverse('downloader:api_inspect'), {'url': 'http://internal.local/'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('downloader.views.requests.get')
    def test_safe_stream_get_revalidates_redirect_target(self, mock_get):
        redirect = mock_get.return_value
        redirect.is_redirect = True
        redirect.is_permanent_redirect = False
        redirect.headers = {'Location': 'http://169.254.169.254/latest/meta-data/'}

        def fake_safe(url):
            return '169.254.169.254' not in url

        with patch('downloader.views.is_safe_public_url', side_effect=fake_safe):
            with self.assertRaises(ValueError):
                downloader_views.safe_stream_get('https://public.example/file.mp4', headers={})
        self.assertEqual(mock_get.call_count, 1)
        self.assertFalse(mock_get.call_args.kwargs['allow_redirects'])

    @patch('downloader.services.requests.head')
    def test_unshorten_only_touches_known_shorteners(self, mock_head):
        YtDlpService._unshorten_url('https://test.com/watch?v=1')          # contains 't.co' as a substring
        YtDlpService._unshorten_url('https://www.youtube.com/watch?v=1')
        mock_head.assert_not_called()
        mock_head.return_value.url = 'https://www.tiktok.com/@u/video/1'
        self.assertEqual(YtDlpService._unshorten_url('https://vm.tiktok.com/ZM123/'), 'https://www.tiktok.com/@u/video/1')


class GoogleAccessTokenBindingTests(SimpleTestCase):
    @patch('downloader.views.requests.get')
    def test_rejects_token_issued_to_another_app(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'aud': 'someone-else.apps.googleusercontent.com', 'azp': 'someone-else'}
        self.assertIsNone(downloader_views.verify_google_access_token('tok', client_id='ours.apps.googleusercontent.com'))
        self.assertEqual(mock_get.call_count, 1)  # never reached userinfo

    @patch('downloader.views.requests.get')
    def test_accepts_token_for_our_client_id(self, mock_get):
        tokeninfo = type('R', (), {'status_code': 200, 'json': lambda self: {'aud': 'ours', 'azp': 'ours'}})()
        userinfo = type('R', (), {'status_code': 200, 'json': lambda self: {'email': 'u@example.com', 'sub': '1'}})()
        mock_get.side_effect = [tokeninfo, userinfo]
        info = downloader_views.verify_google_access_token('tok', client_id='ours')
        self.assertEqual(info['email'], 'u@example.com')


class DownloadMediaFormatSelectionTests(SimpleTestCase):
    @patch('downloader.services.yt_dlp.YoutubeDL')
    def test_max_height_caps_requested_format(self, mock_ydl):
        instance = mock_ydl.return_value.__enter__.return_value
        instance.extract_info.return_value = {'title': 'x'}
        instance.prepare_filename.return_value = 'nonexistent.mp4'
        with patch('downloader.services.os.listdir', return_value=[]):
            YtDlpService.download_media('https://youtube.com/watch?v=1', '313', False, '/tmp', max_height=1080)
        fmt = mock_ydl.call_args.args[0]['format']
        self.assertTrue(fmt.startswith('313[height<=1080]/'))
        self.assertIn('bestvideo[height<=1080]', fmt)

    @patch('downloader.services.yt_dlp.YoutubeDL')
    def test_yt_dlp_failure_propagates_instead_of_downloading_page_html(self, mock_ydl):
        mock_ydl.return_value.__enter__.return_value.extract_info.side_effect = RuntimeError('extract failed')
        with patch('downloader.services.FileDownloadService.download_direct_file') as direct:
            with self.assertRaises(RuntimeError):
                YtDlpService.download_media('https://youtube.com/watch?v=1', '137', False, '/tmp')
            direct.assert_not_called()
