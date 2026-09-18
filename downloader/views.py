import os
import re
import uuid
import random
import threading
from pathlib import Path
from datetime import datetime, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, FileResponse, Http404, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
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


import json
import ipaddress
import socket
from urllib.parse import urlparse
from django.contrib.auth.hashers import make_password


def is_safe_public_url(target_url):
    """Validate that the URL is public HTTP/HTTPS and not pointing to internal/private/loopback/cloud metadata IPs."""
    if not target_url or not isinstance(target_url, str):
        return False
    try:
        parsed = urlparse(target_url.strip())
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        
        hostname_lower = hostname.lower()
        if hostname_lower in ('localhost', '127.0.0.1', '::1', '0.0.0.0', '169.254.169.254'):
            return False
            
        try:
            # Check every address the host resolves to (A and AAAA), not just the first one.
            infos = socket.getaddrinfo(hostname, None)
        except Exception:
            return False
        if not infos:
            return False
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                return False
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return False

        return True
    except Exception:
        return False


def safe_stream_get(url, headers, timeout=30, max_redirects=5):
    """requests.get(stream=True) that re-validates every redirect hop against is_safe_public_url.

    requests follows redirects itself, which would let a public URL bounce us onto an internal
    address after the initial check passed.
    """
    current = url
    for _ in range(max_redirects + 1):
        if not is_safe_public_url(current):
            raise ValueError('Unsafe redirect target')
        resp = requests.get(current, headers=headers, stream=True, timeout=timeout, allow_redirects=False)
        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get('Location')
            resp.close()
            if not location:
                raise ValueError('Redirect without Location')
            current = requests.compat.urljoin(current, location)
            continue
        return resp
    raise ValueError('Too many redirects')


def verify_google_id_token(token_str, client_id):
    """Verify Google ID Token securely using google-auth library or Google tokeninfo endpoint."""
    if not token_str:
        return None

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
                if client_id and not client_id.startswith('YOUR_GOOGLE_CLIENT_ID'):
                    if data.get('aud') != client_id:
                        return None
                return data
    except Exception:
        pass

    return None



def verify_google_access_token(access_token, client_id=None):
    """Verify a Google OAuth2 access token and return the userinfo payload.

    The token is first checked against Google's tokeninfo endpoint so we only accept tokens
    that were issued *to this application* (aud/azp). Without that check any Google token a
    victim granted to some other app would log them in here.
    """
    if not access_token:
        return None
    try:
        if client_id:
            info_resp = requests.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"access_token": access_token},
                timeout=5,
            )
            if info_resp.status_code != 200:
                return None
            info = info_resp.json()
            if info.get('aud') != client_id and info.get('azp') != client_id:
                return None
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


GUEST_ID_RE = re.compile(r'^[A-Za-z0-9_\-]{6,100}$')


def get_guest_id(request):
    """Opaque browser-generated id for anonymous visitors (X-User-Id header or cookie).

    Only used to group an anonymous visitor's own history. It is never treated as a
    registered-user identity, and anything that does not look like the client-generated
    `usr_...` token (e.g. an email address) is ignored.
    """
    raw = (request.headers.get('X-User-Id') or request.COOKIES.get('user_unique_id') or '').strip()
    return raw if GUEST_ID_RE.match(raw) else ''


def _is_authenticated(request):
    return bool(getattr(request, 'user', None) and request.user.is_authenticated)


def records_for(request):
    """Queryset of DownloadRecords the requester is allowed to see/modify."""
    if _is_authenticated(request):
        return DownloadRecord.objects.filter(owner=request.user)
    guest_id = get_guest_id(request)
    if guest_id:
        return DownloadRecord.objects.filter(owner__isnull=True, guest_id=guest_id)
    return DownloadRecord.objects.none()


def record_owner_fields(request):
    """Kwargs to stamp ownership on a new DownloadRecord."""
    if _is_authenticated(request):
        return {'owner': request.user}
    return {'guest_id': get_guest_id(request)}


def claim_guest_records(request, user):
    """After login, attach the browser's anonymous history to the now-logged-in user."""
    guest_id = get_guest_id(request)
    if guest_id:
        DownloadRecord.objects.filter(owner__isnull=True, guest_id=guest_id).update(owner=user)


def apply_admin_email_rule(user, profile):
    """Grant staff/superuser/premium to emails listed in settings.ADMIN_EMAILS."""
    admin_emails = {e.strip().lower() for e in getattr(settings, 'ADMIN_EMAILS', []) if e.strip()}
    if user.email and user.email.lower() in admin_emails:
        user.is_staff = True
        user.is_superuser = True
        profile.is_premium = True
        user.save(update_fields=['is_staff', 'is_superuser'])
        profile.save(update_fields=['is_premium'])


def staff_required_api(view_func):
    """403 for anyone who is not staff/superuser (for DRF function views)."""
    def _wrapped(request, *args, **kwargs):
        if not _is_authenticated(request) or not (request.user.is_staff or request.user.is_superuser):
            return Response({'error': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        return view_func(request, *args, **kwargs)
    _wrapped.__name__ = view_func.__name__
    _wrapped.__doc__ = view_func.__doc__
    return _wrapped


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
        # Key anonymous quota on IP, not on the client-chosen guest id, otherwise the
        # daily limit is bypassed by simply generating a new id per request.
        identifier = f"anon_{get_client_ip(request) or 'unknown'}"

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
    recent_downloads = records_for(request)[:10]
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
    if not is_safe_public_url(url):
        return Response({'error': "Yaroqsiz yoki qo'llab-quvvatlanmaydigan havola."}, status=status.HTTP_400_BAD_REQUEST)

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
                fmt['format_id'] = 'premium_required'
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
            client_ip=client_ip,
            title=result.get('title', 'Extracted Media'),
            original_url=url,
            media_type='video' if result.get('video_formats') else 'audio',
            format_label=f"{len(result.get('video_formats', []))} Links",
            status='completed',
            **record_owner_fields(request),
        )
    except Exception:
        pass

    return Response(result)


def download_file_view(request, record_id):
    """Serve converted file or redirect to original media URL for a download record."""
    try:
        record = DownloadRecord.objects.get(id=record_id)
    except (DownloadRecord.DoesNotExist, ValueError, ValidationError):
        raise Http404("Yuklab olinadigan yozuv topilmadi.")

    is_staff = _is_authenticated(request) and (request.user.is_staff or request.user.is_superuser)
    if not is_staff and not records_for(request).filter(id=record.id).exists():
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


def api_download_media_stream(request):
    """Download or stream media file directly to user's browser, bypassing 403 blocks."""
    url = request.GET.get('url')
    original_url = request.GET.get('original_url')
    format_id = request.GET.get('format_id')
    is_audio = request.GET.get('is_audio') in ['true', '1', True]
    filename = request.GET.get('filename') or 'nexusdown_media'
    ext = request.GET.get('ext') or ('mp3' if is_audio else 'mp4')

    clean_name = re.sub(r'[^a-zA-Z0-9_\-\. ]', '_', filename).strip().replace(' ', '_')
    if not clean_name:
        clean_name = "nexusdown_media"
    if not clean_name.endswith(f".{ext}"):
        clean_filename = f"{clean_name}.{ext}"
    else:
        clean_filename = clean_name

    if format_id == 'premium_required':
        return JsonResponse({'error': 'Ushbu sifat faqat Premium foydalanuvchilar uchun.'}, status=403)

    # Non-premium users are capped at 1080p server-side; the lock in the UI is only cosmetic.
    is_premium = get_daily_search_status(request)['is_premium']
    max_height = None if is_premium else 1080

    # If original_url is provided (e.g. YouTube video / TikTok / Instagram), use YtDlpService
    if original_url and is_safe_public_url(original_url):
        try:
            download_res = YtDlpService.download_media(
                url=original_url,
                format_id=format_id,
                is_audio=is_audio,
                output_dir=settings.DOWNLOADS_DIR,
                max_height=max_height,
            )
            if download_res and download_res.get('file_path') and os.path.exists(download_res['file_path']):
                return FileResponse(
                    open(download_res['file_path'], 'rb'),
                    as_attachment=True,
                    filename=clean_filename
                )
        except Exception:
            pass

    # Direct URL streaming fallback (with SSRF protection)
    if not url or not is_safe_public_url(url):
        raise Http404("Yaroqsiz media havolasi.")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'identity;q=1, *;q=0',
        'Range': 'bytes=0-'
    }

    try:
        remote_resp = safe_stream_get(url, headers)
        if remote_resp.status_code in [200, 206]:
            content_type = remote_resp.headers.get('Content-Type') or f'video/{ext}'

            def file_iterator(chunk_size=1024 * 64):
                for chunk in remote_resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        yield chunk

            response = StreamingHttpResponse(file_iterator(), content_type=content_type)
            response['Content-Disposition'] = f'attachment; filename="{clean_filename}"'
            if 'Content-Length' in remote_resp.headers:
                response['Content-Length'] = remote_resp.headers['Content-Length']
            return response
    except Exception:
        pass

    return redirect(url)


@api_view(['GET'])
def api_history(request):
    """Get list of recent link extraction records for the requesting user."""
    records = records_for(request)[:30]

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

        client_ip = get_client_ip(request)

        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        record = DownloadRecord.objects.create(
            client_ip=client_ip,
            title=output_name,
            original_url='',
            media_type='image_pdf',
            format_label=format_label,
            file_name=output_name,
            file_path=output_path,
            file_size=file_size,
            status='completed',
            **record_owner_fields(request),
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
    req_data = getattr(request, 'data', {})
    record_id = (req_data.get('id') if isinstance(req_data, dict) else None) or request.POST.get('id') or request.GET.get('id')

    if not record_id or not (_is_authenticated(request) or get_guest_id(request)):
        return Response({'error': 'Record ID and User ID are required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        deleted_count, _ = records_for(request).filter(id=record_id).delete()
    except (ValueError, ValidationError):
        deleted_count = 0
    if deleted_count > 0:
        return Response({'status': 'success', 'message': 'Record deleted successfully.'})
    return Response({'error': 'Record not found or permission denied.'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST', 'DELETE'])
def api_clear_history(request):
    """Clear all download history records for the requesting user."""
    if not (_is_authenticated(request) or get_guest_id(request)):
        return Response({'error': 'User identification missing.'}, status=status.HTTP_400_BAD_REQUEST)

    deleted_count, _ = records_for(request).delete()
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
        id_info = verify_google_access_token(access_token, client_id)

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

    # Django's User.email is not unique; look up case-insensitively and take the oldest
    # match instead of get_or_create(), which raises on duplicates.
    user = User.objects.filter(email__iexact=email).order_by('id').first()
    created = user is None
    if created:
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        user.set_unusable_password()
        user.save(update_fields=['password'])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    apply_admin_email_rule(user, profile)

    if not created:
        if first_name and not user.first_name:
            user.first_name = first_name
        if last_name and not user.last_name:
            user.last_name = last_name
        user.save()

    login(request, user)
    request.session['user_avatar'] = picture
    request.session.save()
    claim_guest_records(request, user)

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
    apply_admin_email_rule(user, profile)
    claim_guest_records(request, user)

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
    hashed_password = make_password(password)

    EmailVerificationCode.objects.create(
        email=email,
        code=code,
        expires_at=expires_at,
        user_data={
            'username': username,
            'email': email,
            'password': hashed_password,
            'first_name': first_name,
            'last_name': last_name,
        }
    )

    def _send_email_task():
        subject = f"NexusDown - Tasdiqlash kodingiz: {code}"
        text_content = (
            f"Salom {username}!\n\n"
            f"NexusDown platformasida ro'yxatdan o'tish uchun tasdiqlash kodingiz: {code}\n\n"
            f"Ushbu kod 10 daqiqa davomida amal qiladi.\n"
            f"Agar siz ro'yxatdan o'tishni so'ramagan bo'lsangiz, ushbu xabarga e'tibor bermang."
        )
        html_content = f"""
        <div style="font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0f19; color: #f1f5f9; padding: 32px 20px; max-width: 480px; margin: 0 auto; border-radius: 16px; border: 1px solid #1e293b;">
            <div style="text-align: center; margin-bottom: 24px;">
                <h1 style="background: linear-gradient(135deg, #00f2fe, #4facfe); -webkit-background-clip: text; -webkit-text-fill-color: #00f2fe; font-size: 26px; font-weight: 800; margin: 0;">NexusDown</h1>
                <p style="color: #94a3b8; font-size: 13px; margin: 4px 0 0 0;">Ro'yxatdan o'tishni tasdiqlash</p>
            </div>
            <p style="font-size: 15px; color: #e2e8f0; margin-bottom: 12px;">Salom <strong>{username}</strong>,</p>
            <p style="font-size: 14px; color: #94a3b8; line-height: 1.5; margin-bottom: 20px;">
                Platformamizda hisob yaratish uchun quyidagi 6 xonali tasdiqlash kodidan foydalaning:
            </p>
            <div style="text-align: center; margin: 24px 0;">
                <div style="display: inline-block; background: linear-gradient(135deg, #6366f1, #a855f7); color: #ffffff; font-size: 30px; font-weight: 800; letter-spacing: 8px; padding: 14px 32px; border-radius: 12px; box-shadow: 0 4px 20px rgba(168, 85, 247, 0.4);">
                    {code}
                </div>
            </div>
            <p style="font-size: 13px; color: #fbbf24; text-align: center; margin-bottom: 24px;">
                ⏳ Ushbu kod <strong>10 daqiqa</strong> davomida amal qiladi.
            </p>
            <hr style="border: none; border-top: 1px solid #1e293b; margin: 20px 0;">
            <p style="font-size: 11px; color: #64748b; text-align: center; margin: 0;">
                Agar siz NexusDown'dan ro'yxatdan o'tishni so'ramagan bo'lsangiz, ushbu xabarni e'tiborsiz qoldiring.
            </p>
        </div>
        """
        try:
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'NexusDown <noreply@nexusdown.com>')
            msg = EmailMultiAlternatives(subject, text_content, from_email, [email])
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)
        except Exception as e:
            print(f"❌ [Email Send Error]: {e}")

    threading.Thread(target=_send_email_task, daemon=True).start()

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
    if User.objects.filter(email__iexact=email).exists():
        return Response({'error': "Ushbu email manzili ro'yxatdan o'tgan. Tizimga kiring."}, status=status.HTTP_400_BAD_REQUEST)

    user = User(
        username=username,
        email=email,
        first_name=user_data.get('first_name', ''),
        last_name=user_data.get('last_name', '')
    )
    user.password = pass_str  # Already hashed securely with make_password
    user.save()

    profile, _ = UserProfile.objects.get_or_create(user=user)
    apply_admin_email_rule(user, profile)

    login(request, user)
    claim_guest_records(request, user)

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
@staff_required_api
def api_admin_users(request):
    """Get list of all registered users with search stats and premium status for Admin."""
    today = timezone.now().date()
    users = (
        User.objects.all()
        .select_related('profile')
        .annotate(total_downloads=Count('download_records'))
        .order_by('-date_joined')
    )
    trackers_today = dict(
        DailySearchTracker.objects.filter(date=today, identifier__startswith='user_')
        .values_list('identifier', 'search_count')
    )
    user_list = []

    for u in users:
        profile = getattr(u, 'profile', None) or UserProfile.objects.get_or_create(user=u)[0]
        search_count_today = trackers_today.get(f"user_{u.id}", 0)
        total_downloads = u.total_downloads

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
@staff_required_api
def api_admin_toggle_premium(request):
    """Toggle premium status for a user via Admin panel."""
    user_id = request.data.get('user_id')
    is_premium = bool(request.data.get('is_premium'))
    try:
        days = int(request.data.get('days') or 0)
    except (TypeError, ValueError):
        return Response({'error': 'days must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)

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
@staff_required_api
def api_admin_history(request):
    """Get global download history for Admin panel with search filtering."""
    query = request.GET.get('query', '').strip()
    records = DownloadRecord.objects.select_related('owner')

    if query:
        records = records.filter(
            Q(title__icontains=query)
            | Q(owner__email__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(guest_id__icontains=query)
            | Q(client_ip__icontains=query)
        )

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
            'user_id': r.owner_label,
            'client_ip': r.client_ip,
            'status': r.status,
            'created_at': timezone.localtime(r.created_at).strftime('%b %d, %Y %H:%M') if r.created_at else ''
        })

    return Response({'history': data, 'total_count': len(data)})
