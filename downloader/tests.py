from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework import status

from .services import YtDlpService
from .models import DownloadRecord


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
        me_res_after = self.client.get(reverse('downloader:api_auth_logout'))
        self.assertEqual(logout_res.status_code, status.HTTP_200_OK)

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
            status='completed'
        )
        response = self.client.get(reverse('downloader:download_file', kwargs={'record_id': str(record.id)}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://example.com/test.mp4')





