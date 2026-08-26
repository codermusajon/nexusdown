import os
import uuid
import random
from pathlib import Path
from datetime import datetime, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.mail import send_mail
from django.contrib.admin.views.decorators import staff_member_required
import requests

try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import DownloadRecord, UserProfile, DailySearchTracker, EmailVerificationCode
from .services import YtDlpService, FileDownloadService, ImageConverterService


import base64
import json

def verify_google_id_token(token_str, client_id):
    """Verify Google ID Token using google-auth library, tokeninfo endpoint, or JWT payload decoder fallback."""
    if GOOGLE_AUTH_AVAILABLE and client_id and not client_id.startswith('YOUR_GOOGLE_CLIENT_ID'):
        try:
            id_info = id_token.verify_oauth2_token(token_str, google_requests.Request(), client_id)
            return id_info
        except Exception:
            pass

    try:
        resp = requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={token_str}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if 'error' not in data and ('email' in data or 'sub' in data):
                return data
    except Exception:
        pass

    try:
        parts = token_str.split('.')
        if len(parts) == 3:
            padded = parts[1] + '=' * (-len(parts[1]) % 4)
            payload_bytes = base64.urlsafe_b64decode(padded)
            data = json.loads(payload_bytes.decode('utf-8'))
            if 'email' in data:
                return data
    except Exception:
        pass

    return None



def verify_google_access_token(access_token):
    """Verify Google OAuth2 Access Token by requesting userinfo from Google API."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if 'email' in data or 'sub' in data:
                return data
    except Exception:
        pass
    return None


def get_client_ip(request):
    """Extract real client IP address from HTTP request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '')
    return ip


def get_client_user_id(request):
    """Get unique user ID from authenticated Django user, headers, cookies, or GET/POST params."""
    if hasattr(request, 'user') and request.user and request.user.is_authenticated:
        return request.user.email or request.user.username
    user_id = request.headers.get('X-User-Id') or request.COOKIES.get('user_unique_id')
    if not user_id:
        req_data = getattr(request, 'data', {})
        if isinstance(req_data, dict):
            user_id = req_data.get('user_id')
    if not user_id and hasattr(request, 'POST'):
        user_id = request.POST.get('user_id')
    if not user_id and hasattr(request, 'GET'):
        user_id = request.GET.get('user_id')
    return (user_id or '').strip()


def get_daily_search_status(request):
    """
    Check current daily search usage and user limit.
    - Guest (unregistered): limit = 2
    - Registered Free: limit = 10
    - Premium User: limit = None (unlimited)
    """
    today = timezone.now().date()

    if hasattr(request, 'user') and request.user and request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        is_premium = profile.is_premium_active
        limit = None if is_premium else 10
        user_type = 'premium' if is_premium else 'registered'
        identifier = f"user_{request.user.id}"
    else:
        is_premium = False
        limit = 2
        user_type = 'unregistered'
        client_uid = get_client_user_id(request)
        ip = get_client_ip(request)
        identifier = f"anon_{client_uid or ip}"

    tracker, _ = DailySearchTracker.objects.get_or_create(identifier=identifier, date=today)
    searches_today = tracker.search_count

    return {
        'is_premium': is_premium,
        'user_type': user_type,
        'searches_today': searches_today,
        'limit': limit,
        'remaining': (limit - searches_today) if limit is not None else 'Unlimited',
        'identifier': identifier,
        'tracker': tracker,
    }


def index_view(request):
    """Render main application single-page dashboard."""
    current_year = datetime.now().year - 2006
    user_id = get_client_user_id(request)
    recent_downloads = DownloadRecord.objects.filter(user_id=user_id)[:10] if user_id else DownloadRecord.objects.none()
    status_info = get_daily_search_status(request)

    context = {
        'recent_downloads': recent_downloads,
        'current_year': current_year,
        'google_client_id': getattr(settings, 'GOOGLE_CLIENT_ID', ''),
        'quota_info': status_info,
    }
    return render(request, 'downloader/index.html', context)


@api_view(['POST'])
def api_inspect(request):
    """Inspect video/audio URL metadata and return direct downloadable media links."""
    url = request.data.get('url', '').strip()
    if not url:
        return Response({'error': 'URL parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

    status_info = get_daily_search_status(request)
    limit = status_info['limit']
    searches_today = status_info['searches_today']

    # Check search limits
    if limit is not None and searches_today >= limit:
        if status_info['user_type'] == 'unregistered':
            return Response({
                'error_code': 'UNREGISTERED_LIMIT_REACHED',
                'error': 'Ro\'yxatdan o\'tmagan foydalanuvchilar kuniga faqat 2 marta qidirishlari mumkin. Davom etish uchun ro\'yxatdan o\'ting!',
                'searches_today': searches_today,
                'max_searches': limit,
            }, status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({
                'error_code': 'REGISTERED_LIMIT_REACHED',
                'error': 'Ro\'yxatdan o\'tgan foydalanuvchilar kuniga 10 marta qidirishlari mumkin. Cheksiz qidiruvlar uchun Premium maqomiga o\'ting!',
                'searches_today': searches_today,
                'max_searches': limit,
                'telegram_info': '@coder_ismoil'
            }, status=status.HTTP_403_FORBIDDEN)

    user_id = get_client_user_id(request)
    client_ip = get_client_ip(request)

    result = YtDlpService.inspect_url(url)
    if result.get('status') == 'error':
        return Response({'error': result.get('error')}, status=status.HTTP_400_BAD_REQUEST)

    # Increment search count upon successful inspect
    tracker = status_info['tracker']
    tracker.search_count += 1
    tracker.save()

    # Resolution lockdown for non-premium users (>1080p locked)
    is_premium = status_info['is_premium']
    if not is_premium and result.get('video_formats'):
        for fmt in result['video_formats']:
            h = fmt.get('height') or 0
            if h > 1080:
                fmt['is_locked'] = True
                fmt['download_url'] = '#premium_required'
                fmt['label'] = f"👑 PRO {fmt.get('resolution', f'{h}p')} (Lock)"
            else:
                fmt['is_locked'] = False

    result['quota_info'] = {
        'searches_today': tracker.search_count,
        'max_searches': limit,
        'is_premium': is_premium,
        'user_type': status_info['user_type'],
        'telegram_info': '@coder_ismoil'
    }

    # Log download record
    try:
        DownloadRecord.objects.create(
            user_id=user_id,
            client_ip=client_ip,
            title=result.get('title', 'Extracted Media'),
            original_url=url,
            media_type='video' if result.get('video_formats') else 'audio',
            format_label=f"{len(result.get('video_formats', []))} Links",
            status='completed'
        )
    except Exception:
        pass

    return Response(result)


def download_file_view(request, record_id):
    """Serve converted file or redirect to original media URL for a download record."""
    try:
        record = DownloadRecord.objects.get(id=record_id)
    except (DownloadRecord.DoesNotExist, ValueError):
        raise Http404("Yuklab olinadigan yozuv topilmadi.")

    target_path = None
    if record.file_path:
        if os.path.exists(record.file_path):
            target_path = record.file_path
        else:
            rel_path = os.path.join(settings.MEDIA_ROOT, record.file_path)
            if os.path.exists(rel_path):
                target_path = rel_path

    if not target_path and record.file_name:
        dl_path = os.path.join(settings.DOWNLOADS_DIR, record.file_name)
        if os.path.exists(dl_path):
            target_path = dl_path

    if target_path and os.path.exists(target_path):
        filename = record.file_name or os.path.basename(target_path)
        return FileResponse(
            open(target_path, 'rb'),
            as_attachment=True,
            filename=filename
        )

    if record.original_url and (record.original_url.startswith('http://') or record.original_url.startswith('https://')):
        return redirect(record.original_url)

    raise Http404("Fayl topilmadi.")


@api_view(['GET'])
def api_history(request):
    """Get list of recent link extraction records for the requesting user."""
    user_id = get_client_user_id(request)
    if user_id:
        records = DownloadRecord.objects.filter(user_id=user_id)[:30]
    else:
        records = DownloadRecord.objects.none()

    data = []
    for r in records:
        data.append({
            'id': str(r.id),
            'title': r.title,
            'original_url': r.original_url,
            'media_type': r.media_type,
            'format_label': r.format_label,
            'file_size_mb': round(r.file_size / (1024 * 1024), 2) if r.file_size else 0,
            'status': r.status,
            'download_url': r.download_url,
            'created_at': timezone.localtime(r.created_at).strftime('%b %d, %H:%M') if r.created_at else ''
        })
    return Response({'history': data})


import json

@api_view(['POST'])
def api_convert_images(request):
    """Convert uploaded image files to PDF or specific format with customization options."""
    files = request.FILES.getlist('images')
    target_format = request.POST.get('target_format', 'pdf').lower().strip()
    page_size = request.POST.get('page_size', 'a4').lower().strip()
    orientation = request.POST.get('orientation', 'auto').lower().strip()
    margin_mm = float(request.POST.get('margin', 0) or 0)
    quality = int(request.POST.get('quality', 90) or 90)
    page_numbers = str(request.POST.get('page_numbers', 'false')).lower() in ['true', '1', 'yes']
    output_mode = request.POST.get('output_mode', 'single_pdf').lower().strip()

    rotations_raw = request.POST.get('rotations', '[]')
    try:
        rotations = json.loads(rotations_raw)
    except Exception:
        rotations = [int(r.strip()) for r in rotations_raw.split(',') if r.strip().isdigit()]

    if not files:
        return Response({'error': 'No image files uploaded.'}, status=status.HTTP_400_BAD_REQUEST)

    temp_paths = []
    output_dir = settings.DOWNLOADS_DIR

    try:
        for idx, f in enumerate(files):
            temp_path = os.path.join(output_dir, f"upload_{idx}_{uuid.uuid4().hex[:6]}_{f.name}")
            with open(temp_path, 'wb+') as destination:
                for chunk in f.chunks():
                    destination.write(chunk)
            temp_paths.append(temp_path)

        if output_mode == 'zip' or (target_format != 'pdf' and len(files) > 1 and output_mode != 'single_pdf'):
            output_name = f"converted_images_{uuid.uuid4().hex[:6]}.zip"
            output_path = os.path.join(output_dir, output_name)
            ImageConverterService.create_converted_zip(
                temp_paths, output_path, rotations=rotations, target_format=target_format,
                page_size=page_size, orientation=orientation, margin_mm=margin_mm, quality=quality, page_numbers=page_numbers
            )
            format_label = f"{target_format.upper()} (ZIP)"
        elif target_format == 'pdf':
            clean_first_name = os.path.splitext(files[0].name)[0]
            output_name = f"converted_doc_{clean_first_name}_{uuid.uuid4().hex[:4]}.pdf"
            output_path = os.path.join(output_dir, output_name)
            ImageConverterService.convert_images_to_pdf(
                temp_paths, output_path, rotations=rotations, page_size=page_size,
                orientation=orientation, margin_mm=margin_mm, quality=quality, page_numbers=page_numbers
            )
            format_label = "PDF Document"
        else:
            clean_first_name = os.path.splitext(files[0].name)[0]
            ext = 'jpg' if target_format in ['jpeg', 'jpg'] else target_format
            output_name = f"converted_{clean_first_name}_{uuid.uuid4().hex[:4]}.{ext}"
            output_path = os.path.join(output_dir, output_name)
            rot = rotations[0] if rotations else 0
            ImageConverterService.convert_image_format(temp_paths[0], target_format, output_path, rotation=rot, quality=quality)
            format_label = target_format.upper()

        for p in temp_paths:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

        user_id = get_client_user_id(request)
        client_ip = get_client_ip(request)

        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        record = DownloadRecord.objects.create(
            user_id=user_id,
            client_ip=client_ip,
            title=output_name,
            original_url='',
            media_type='image_pdf',
            format_label=format_label,
            file_name=output_name,
            file_path=output_path,
            file_size=file_size,
            status='completed'
        )

        return Response({
            'status': 'success',
            'id': str(record.id),
            'title': record.title,
            'file_size_mb': round(record.file_size / (1024 * 1024), 2),
            'download_url': f"/download/{record.id}/"
        })

    except Exception as e:
        for p in temp_paths:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        return Response({'error': f"Conversion failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST', 'DELETE'])
def api_delete_history(request):
    """Delete a single download record for the requesting user."""
    user_id = get_client_user_id(request)
    req_data = getattr(request, 'data', {})
    record_id = (req_data.get('id') if isinstance(req_data, dict) else None) or request.POST.get('id') or request.GET.get('id')

    if not record_id or not user_id:
        return Response({'error': 'Record ID and User ID are required.'}, status=status.HTTP_400_BAD_REQUEST)

    deleted_count, _ = DownloadRecord.objects.filter(id=record_id, user_id=user_id).delete()
    if deleted_count > 0:
        return Response({'status': 'success', 'message': 'Record deleted successfully.'})
    return Response({'error': 'Record not found or permission denied.'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST', 'DELETE'])
def api_clear_history(request):
    """Clear all download history records for the requesting user."""
    user_id = get_client_user_id(request)
    if not user_id:
        return Response({'error': 'User identification missing.'}, status=status.HTTP_400_BAD_REQUEST)

    deleted_count, _ = DownloadRecord.objects.filter(user_id=user_id).delete()
    return Response({
        'status': 'success',
        'message': f'{deleted_count} history records cleared successfully.',
        'deleted_count': deleted_count
    })


@api_view(['POST'])
def api_google_auth(request):
    """Authenticate or register a user via Google OAuth2 ID token or Access token."""
    token_str = request.data.get('id_token') or request.data.get('credential')
    access_token = request.data.get('access_token')

    if not token_str and not access_token:
        return Response({'error': 'Google ID token or access token is required.'}, status=status.HTTP_400_BAD_REQUEST)

    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    id_info = None

    if token_str:
        id_info = verify_google_id_token(token_str, client_id)

    if not id_info and access_token:
        id_info = verify_google_access_token(access_token)

    if not id_info:
        return Response({'error': 'Invalid or expired Google token.'}, status=status.HTTP_400_BAD_REQUEST)

    email = id_info.get('email')
    if not email:
        return Response({'error': 'Google account email missing from token.'}, status=status.HTTP_400_BAD_REQUEST)

    first_name = id_info.get('given_name', '')
    last_name = id_info.get('family_name', '')
    picture = id_info.get('picture', '')

    username = email.split('@')[0]
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exclude(email=email).exists():
        username = f"{base_username}_{counter}"
        counter += 1

    user, created = User.objects.get_or_create(email=email, defaults={
        'username': username,
        'first_name': first_name,
        'last_name': last_name,
    })

    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Special Admin Rule: coderismoil@gmail.com is auto superuser + staff + premium
    if user.email.lower() == 'coderismoil@gmail.com':
        user.is_staff = True
        user.is_superuser = True
        profile.is_premium = True
        user.save()
        profile.save()

    if not created:
        if first_name and not user.first_name:
            user.first_name = first_name
        if last_name and not user.last_name:
            user.last_name = last_name
        user.save()

    login(request, user)
    request.session['user_avatar'] = picture
    request.session.save()

    client_user_id = request.COOKIES.get('user_unique_id') or request.headers.get('X-User-Id')
    if client_user_id and client_user_id != email:
        DownloadRecord.objects.filter(user_id=client_user_id).update(user_id=email)

    redirect_url = '/admin-dashboard/' if (user.is_staff or user.is_superuser) else '/'

    return Response({
        'status': 'success',
        'redirect_url': redirect_url,
        'user': {
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'name': user.get_full_name() or user.username,
            'picture': picture,
            'is_authenticated': True,
            'is_staff': user.is_staff or user.is_superuser,
            'is_premium': profile.is_premium_active,
        }
    })



@api_view(['GET'])
def api_auth_me(request):
    """Return currently logged-in user profile details and search quota."""
    status_info = get_daily_search_status(request)

    if request.user and request.user.is_authenticated:
        name = request.user.get_full_name() or request.user.first_name or request.user.username
        picture = request.session.get('user_avatar', '')
        profile, _ = UserProfile.objects.get_or_create(user=request.user)

        return Response({
            'is_authenticated': True,
            'user': {
                'id': request.user.id,
                'email': request.user.email,
                'name': name,
                'first_name': request.user.first_name,
                'last_name': request.user.last_name,
                'username': request.user.username,
                'picture': picture,
                'is_staff': request.user.is_staff or request.user.is_superuser,
                'is_premium': profile.is_premium_active,
                'premium_expires_at': profile.premium_expires_at.strftime('%Y-%m-%d') if profile.premium_expires_at else None,
            },
            'quota': {
                'searches_today': status_info['searches_today'],
                'max_searches': status_info['limit'],
                'user_type': status_info['user_type'],
                'is_premium': status_info['is_premium'],
                'telegram_info': '@coder_ismoil'
            }
        })

    return Response({
        'is_authenticated': False,
        'user': None,
        'quota': {
            'searches_today': status_info['searches_today'],
            'max_searches': status_info['limit'],
            'user_type': status_info['user_type'],
            'is_premium': status_info['is_premium'],
            'telegram_info': '@coder_ismoil'
        }
    })


@api_view(['POST'])
def api_auth_logout(request):
    """Logout current user session."""
    if request.user and request.user.is_authenticated:
        logout(request)
    return Response({'status': 'success', 'message': 'Logged out successfully.'})


def login_view(request):
    """Render auth page with Login tab active."""
    if request.user and request.user.is_authenticated:
        return redirect('downloader:index')
    return render(request, 'downloader/auth.html', {
        'active_tab': 'login',
        'google_client_id': getattr(settings, 'GOOGLE_CLIENT_ID', ''),
    })


def signup_view(request):
    """Render auth page with Sign Up tab active."""
    if request.user and request.user.is_authenticated:
        return redirect('downloader:index')
    return render(request, 'downloader/auth.html', {
        'active_tab': 'signup',
        'google_client_id': getattr(settings, 'GOOGLE_CLIENT_ID', ''),
    })


@api_view(['POST'])
def api_auth_login(request):
    """Authenticate standard username/email and password."""
    login_id = request.data.get('login_id', '').strip()
    password = request.data.get('password', '').strip()

    if not login_id or not password:
        return Response({'error': 'Foydalanuvchi nomi/email va parol kiritilishi shart.'}, status=status.HTTP_400_BAD_REQUEST)

    username_to_auth = login_id
    if '@' in login_id:
        user_obj = User.objects.filter(email__iexact=login_id).first()
        if user_obj:
            username_to_auth = user_obj.username

    user = authenticate(request, username=username_to_auth, password=password)

    if user is None:
        return Response({'error': 'Foydalanuvchi nomi, email yoki parol noto\'g\'ri.'}, status=status.HTTP_400_BAD_REQUEST)

    if not user.is_active:
        return Response({'error': 'Ushbu hisob faolsizlantirilgan.'}, status=status.HTTP_400_BAD_REQUEST)

    login(request, user)
    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Special Admin Rule: coderismoil@gmail.com is auto superuser + staff + premium
    if user.email and user.email.lower() == 'coderismoil@gmail.com':
        user.is_staff = True
        user.is_superuser = True
        profile.is_premium = True
        user.save()
        profile.save()

    client_user_id = request.COOKIES.get('user_unique_id') or request.headers.get('X-User-Id')
    if client_user_id and user.email and client_user_id != user.email:
        DownloadRecord.objects.filter(user_id=client_user_id).update(user_id=user.email or user.username)

    picture = request.session.get('user_avatar', '')
    redirect_url = '/admin-dashboard/' if (user.is_staff or user.is_superuser) else '/'

    return Response({
        'status': 'success',
        'message': 'Tizimga muvaffaqiyatli kirdingiz.',
        'redirect_url': redirect_url,
        'user': {
            'email': user.email,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'name': user.get_full_name() or user.username,
            'picture': picture,
            'is_authenticated': True,
            'is_staff': user.is_staff or user.is_superuser,
            'is_premium': profile.is_premium_active,
        }
    })



@api_view(['POST'])
def api_auth_send_code(request):
    """Send a 6-digit email verification code to user's Gmail address during registration."""
    username = request.data.get('username', '').strip()
    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password', '').strip()
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()

    if not username or not email or not password:
        return Response({'error': 'Foydalanuvchi nomi, email va parol kiritilishi shart.'}, status=status.HTTP_400_BAD_REQUEST)

    if len(username) < 3:
        return Response({'error': 'Foydalanuvchi nomi kamida 3 belgidan iborat bo\'lishi kerak.'}, status=status.HTTP_400_BAD_REQUEST)

    if len(password) < 6:
        return Response({'error': 'Parol kamida 6 belgidan iborat bo\'lishi kerak.'}, status=status.HTTP_400_BAD_REQUEST)

    if '@' not in email or '.' not in email:
        return Response({'error': 'Yaroqli email manzilini kiriting.'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username__iexact=username).exists():
        return Response({'error': 'Ushbu foydalanuvchi nomi allaqachon band qilingan.'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email__iexact=email).exists():
        return Response({'error': 'Ushbu email manzili ro\'yxatdan o\'tgan. Tizimga kiring.'}, status=status.HTTP_400_BAD_REQUEST)

    now = timezone.now()

    # Rule: Send max 3 codes per day per Gmail
    codes_today_count = EmailVerificationCode.objects.filter(
        email=email,
        created_at__date=now.date()
    ).count()

    if codes_today_count >= 3:
        return Response({
            'error': 'Ushbu email manzili uchun bir kunda ko\'pida 3 ta tasdiqlash kodi yuboriladi. Ertaga qayta urinib ko\'ring.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Rule: Cooldown of 2 minutes between code requests
    latest_code = EmailVerificationCode.objects.filter(email=email).first()
    if latest_code:
        seconds_since_last = (now - latest_code.created_at).total_seconds()
        if seconds_since_last < 120:
            wait_remaining = int(120 - seconds_since_last)
            return Response({
                'error': f'Yangi tasdiqlash kodini so\'rash uchun {wait_remaining} soniya kuting.'
            }, status=status.HTTP_400_BAD_REQUEST)

    code = f"{random.randint(100000, 999999)}"
    expires_at = now + timedelta(minutes=10)

    EmailVerificationCode.objects.create(
        email=email,
        code=code,
        expires_at=expires_at,
        user_data={
            'username': username,
            'email': email,
            'password': password,
            'first_name': first_name,
            'last_name': last_name,
        }
    )

    subject = "NexusDown - Ro'yxatdan o'tish tasdiqlash kodi"
    message = (
        f"Salom {username}!\n\n"
        f"NexusDown platformasida ro'yxatdan o'tish uchun tasdiqlash kodingiz: {code}\n\n"
        f"Ushbu kod 10 daqiqa davomida amal qiladi.\n"
        f"Agar siz ro'yxatdan o'tishni so'ramagan bo'lsangiz, ushbu xabarga e'tibor bermang."
    )
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'NexusDown <noreply@nexusdown.com>'),
            recipient_list=[email],
            fail_silently=True
        )
    except Exception as e:
        print(f"Error sending email: {e}")

    return Response({
        'status': 'success',
        'message': f'Tasdiqlash kodi {email} manziliga yuborildi (10 daqiqa amal qiladi).',
        'email': email,
        'expires_in_seconds': 600,
        'cooldown_seconds': 120
    })


# Alias for backward compatibility
api_auth_register = api_auth_send_code



@api_view(['POST'])
def api_auth_verify_code(request):
    """Verify 6-digit code entered by user within 10 minutes and create user account."""
    email = request.data.get('email', '').strip().lower()
    code = request.data.get('code', '').strip()

    if not email or not code:
        return Response({'error': 'Email va 6 xonali kod kiritilishi shart.'}, status=status.HTTP_400_BAD_REQUEST)

    latest_code = EmailVerificationCode.objects.filter(email=email, is_verified=False).first()
    if not latest_code:
        return Response({'error': 'Tasdiqlash kodi topilmadi yoki bekor qilingan. Yangi kod so\'rang.'}, status=status.HTTP_400_BAD_REQUEST)

    now = timezone.now()

    # Rule: Check max 3 wrong attempts
    if latest_code.attempts >= 3:
        return Response({
            'error': 'Kod 3 marta noto\'g\'ri kiritilganligi sababli bekor qilindi. Qayta yangi kod so\'rang.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Rule: Expiration within 10 minutes
    if now > latest_code.expires_at:
        return Response({
            'error': 'Tasdiqlash kodining amal qilish muddati (10 daqiqa) tugagan. Yangi kod so\'rang.'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Rule: Code verification
    if latest_code.code != code:
        latest_code.attempts += 1
        latest_code.save()
        remaining = 3 - latest_code.attempts
        if remaining <= 0:
            return Response({
                'error': 'Kod 3 marta noto\'g\'ri kiritildi. Ushbu kod bekor qilindi. Yangi kod so\'rang.'
            }, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'error': f'Noto\'g\'ri tasdiqlash kodi. Yana {remaining} ta urinish qoldi.'
        }, status=status.HTTP_400_BAD_REQUEST)

    latest_code.is_verified = True
    latest_code.save()

    user_data = latest_code.user_data or {}
    username = user_data.get('username')
    pass_str = user_data.get('password')

    if not username or not pass_str:
        return Response({'error': 'Ro\'yxatdan o\'tish ma\'lumotlari topilmadi.'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username__iexact=username).exists():
        return Response({'error': 'Ushbu foydalanuvchi nomi allaqachon band qilingan.'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(
        username=username,
        email=email,
        password=pass_str,
        first_name=user_data.get('first_name', ''),
        last_name=user_data.get('last_name', '')
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Special Admin Rule: coderismoil@gmail.com is auto superuser + staff + premium
    if user.email and user.email.lower() == 'coderismoil@gmail.com':
        user.is_staff = True
        user.is_superuser = True
        profile.is_premium = True
        user.save()
        profile.save()

    login(request, user)

    client_user_id = request.COOKIES.get('user_unique_id') or request.headers.get('X-User-Id')
    if client_user_id and client_user_id != user.email:
        DownloadRecord.objects.filter(user_id=client_user_id).update(user_id=user.email or user.username)

    redirect_url = '/admin-dashboard/' if (user.is_staff or user.is_superuser) else '/'

    return Response({
        'status': 'success',
        'message': 'Muvaffaqiyatli ro\'yxatdan o\'tdingiz va tasdiqlandingiz!',
        'redirect_url': redirect_url,
        'user': {
            'email': user.email,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'name': user.get_full_name() or user.username,
            'is_authenticated': True,
            'is_staff': user.is_staff or user.is_superuser,
            'is_premium': profile.is_premium_active,
        }
    }, status=status.HTTP_201_CREATED)



def admin_dashboard_view(request):
    """Render Custom Admin Dashboard for managing users, premiums, and history."""
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return redirect('/admin/login/?next=/admin-dashboard/')

    total_users = User.objects.count()
    today_users = User.objects.filter(date_joined__date=timezone.now().date()).count()
    premium_users_count = UserProfile.objects.filter(is_premium=True).count()
    total_downloads = DownloadRecord.objects.count()

    context = {
        'total_users': total_users,
        'today_users': today_users,
        'premium_users_count': premium_users_count,
        'total_downloads': total_downloads,
    }
    return render(request, 'downloader/admin_dashboard.html', context)


@api_view(['GET'])
def api_admin_users(request):
    """Get list of all registered users with search stats and premium status for Admin."""
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

    users = User.objects.all().order_by('-date_joined')
    today = timezone.now().date()
    user_list = []

    for u in users:
        profile, _ = UserProfile.objects.get_or_create(user=u)
        user_identifier = f"user_{u.id}"
        tracker = DailySearchTracker.objects.filter(identifier=user_identifier, date=today).first()
        search_count_today = tracker.search_count if tracker else 0
        total_downloads = DownloadRecord.objects.filter(user_id__in=[u.email, u.username]).count()

        user_list.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'name': u.get_full_name() or u.username,
            'is_premium': profile.is_premium_active,
            'premium_expires_at': timezone.localtime(profile.premium_expires_at).strftime('%Y-%m-%d %H:%M') if profile.premium_expires_at else None,
            'search_count_today': search_count_today,
            'total_downloads': total_downloads,
            'date_joined': timezone.localtime(u.date_joined).strftime('%b %d, %Y %H:%M') if u.date_joined else '',
            'is_staff': u.is_staff,
        })

    return Response({'users': user_list})


@api_view(['POST'])
def api_admin_toggle_premium(request):
    """Toggle premium status for a user via Admin panel."""
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

    user_id = request.data.get('user_id')
    is_premium = bool(request.data.get('is_premium'))
    days = int(request.data.get('days') or 0)

    user = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=user)

    profile.is_premium = is_premium
    if is_premium and days > 0:
        profile.premium_expires_at = timezone.now() + timedelta(days=days)
    elif not is_premium:
        profile.premium_expires_at = None

    profile.save()

    return Response({
        'status': 'success',
        'message': f"Foydalanuvchi '{user.username}' uchun Premium maqomi {'faollashtirildi' if is_premium else 'o\'chirildi'}.",
        'is_premium': profile.is_premium_active,
        'premium_expires_at': timezone.localtime(profile.premium_expires_at).strftime('%Y-%m-%d %H:%M') if profile.premium_expires_at else None
    })


@api_view(['GET'])
def api_admin_history(request):
    """Get global download history for Admin panel with search filtering."""
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

    query = request.GET.get('query', '').strip()
    records = DownloadRecord.objects.all()

    if query:
        records = records.filter(title__icontains=query) | records.filter(user_id__icontains=query) | records.filter(client_ip__icontains=query)

    records = records[:100]

    data = []
    for r in records:
        data.append({
            'id': str(r.id),
            'title': r.title,
            'original_url': r.original_url,
            'download_url': r.download_url,
            'media_type': r.media_type,
            'format_label': r.format_label,
            'user_id': r.user_id,
            'client_ip': r.client_ip,
            'status': r.status,
            'created_at': timezone.localtime(r.created_at).strftime('%b %d, %Y %H:%M') if r.created_at else ''
        })

    return Response({'history': data, 'total_count': len(data)})
