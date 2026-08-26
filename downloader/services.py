import os
import uuid
import re
import html
import requests
from pathlib import Path
from urllib.parse import urlparse, unquote
from PIL import Image
import img2pdf
import yt_dlp


class InstagramFallbackError(Exception):
    """Raised when Instagram fallback parsing fails to find media."""


class YtDlpService:
    YOUTUBE_EXTRACTOR_ARGS = {
        'youtube': {
            'player_client': ['tv', 'android_vr', 'web_creator', 'ios', 'android'],
        }
    }

    # Cookies file path — export from Chrome/Edge while logged into Instagram
    COOKIES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cookies.txt')

    @staticmethod
    def _parse_instagram_fallback(url, page_html):
        """Extract usable media URLs from Instagram HTML when yt-dlp returns empty metadata."""
        cleaned_html = page_html or ''
        video_formats = []
        thumbnail = ''

        patterns = [
            r'"video_url":"([^"]+)"',
            r'"display_url":"([^"]+)"',
            r'"thumbnail_src":"([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned_html)
            if match:
                media_url = match.group(1).replace('\\u0026', '&').replace('&amp;', '&')
                if 'mp4' in media_url.lower() or 'video' in media_url.lower():
                    video_formats.append({
                        'format_id': 'ig_fallback_video',
                        'resolution': 'HD Video',
                        'height': 1080,
                        'ext': 'mp4',
                        'filesize_mb': 0,
                        'label': 'Instagram Video (Fallback)',
                        'download_url': media_url,
                    })
                else:
                    thumbnail = media_url
                    video_formats.append({
                        'format_id': 'ig_fallback_photo',
                        'resolution': 'HQ Photo',
                        'height': 1080,
                        'ext': 'jpg',
                        'filesize_mb': 0,
                        'label': 'Instagram Photo (Fallback)',
                        'download_url': media_url,
                    })
                break

        if not video_formats and 'instagram.com' in url:
            og_image = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', cleaned_html)
            if og_image:
                photo_url = og_image.group(1).replace('&amp;', '&')
                video_formats.append({
                    'format_id': 'ig_fallback_photo',
                    'resolution': 'HQ Photo',
                    'height': 1080,
                    'ext': 'jpg',
                    'filesize_mb': 0,
                    'label': 'Instagram Photo (Fallback)',
                    'download_url': photo_url,
                })
                thumbnail = photo_url

        return {
            'title': 'Instagram Media',
            'thumbnail': thumbnail,
            'video_formats': video_formats,
        }

    @staticmethod
    def _get_base_opts():
        """Base yt-dlp options shared across all operations."""
        opts = {
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'extractor_args': YtDlpService.YOUTUBE_EXTRACTOR_ARGS,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.instagram.com/',
            },
        }
        if os.path.exists(YtDlpService.COOKIES_FILE):
            opts['cookiefile'] = YtDlpService.COOKIES_FILE
        return opts

    @staticmethod
    def _unshorten_url(url):
        """Expand short URLs like vm.tiktok.com, vt.tiktok.com, youtu.be, t.co."""
        if any(domain in url for domain in ['vm.tiktok.com', 'vt.tiktok.com', 'youtu.be', 't.co', 'bit.ly', 'tinyurl.com']):
            try:
                resp = requests.head(
                    url,
                    allow_redirects=True,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                    timeout=10,
                    verify=False
                )
                if resp.url:
                    return resp.url
            except Exception:
                pass
        return url

    @staticmethod
    def _fetch_tiktok_fallback(url):
        """Fallback extractor for TikTok using unblocked API service to bypass regional ISP blocks."""
        try:
            # Unshorten vm.tiktok.com / vt.tiktok.com links via external unblocked API if local connection is blocked
            if 'vm.tiktok.com' in url or 'vt.tiktok.com' in url:
                try:
                    unshort_resp = requests.get(f"https://unshorten.me/json/{url}", timeout=8)
                    if unshort_resp.ok:
                        unshort_data = unshort_resp.json()
                        if unshort_data.get('success') and unshort_data.get('resolved_url'):
                            url = unshort_data['resolved_url']
                except Exception:
                    pass

            resp = requests.post(
                'https://www.tikwm.com/api/',
                data={'url': url, 'hd': 1},
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                timeout=12,
                verify=False
            )
            if resp.ok:
                res = resp.json()
                if res.get('code') == 0 and res.get('data'):
                    d = res['data']
                    title = d.get('title', 'TikTok Media')
                    author_data = d.get('author') or {}
                    uploader = author_data.get('nickname') or author_data.get('unique_id') or 'TikTok User'
                    cover = d.get('cover', '') or d.get('origin_cover', '')
                    video_url = d.get('hdplay') or d.get('play', '')
                    audio_url = d.get('music', '')
                    images = d.get('images', [])

                    video_formats = []
                    if images:
                        for idx, img_url in enumerate(images, 1):
                            video_formats.append({
                                'format_id': f'photo_{idx}',
                                'resolution': f'Photo #{idx}',
                                'height': 1080,
                                'ext': 'jpg',
                                'filesize_mb': 0,
                                'label': f'Photo #{idx} (HQ)',
                                'download_url': img_url
                            })
                    elif video_url:
                        video_formats.append({
                            'format_id': 'tiktok_hd',
                            'resolution': 'HD Video',
                            'height': 1080,
                            'ext': 'mp4',
                            'filesize_mb': round((d.get('hd_size') or d.get('size') or 0) / (1024 * 1024), 1),
                            'label': 'HD Video (Suvsiz / No Watermark)',
                            'download_url': video_url
                        })

                    return {
                        'status': 'success',
                        'title': title,
                        'uploader': uploader,
                        'thumbnail': cover,
                        'video_formats': video_formats,
                        'audio_url': audio_url,
                        'duration': d.get('duration', 0),
                        'duration_str': YtDlpService._format_duration(d.get('duration', 0)),
                        'fallback_url': video_url,
                        'original_url': url
                    }
        except Exception:
            pass
        return None

    @staticmethod
    def inspect_url(url):
        """Extract metadata and direct media stream links for videos, audio, and photo carousels."""
        url = YtDlpService._unshorten_url(url)
        
        # Immediate fallback check for TikTok URLs to bypass regional ISP restrictions
        if 'tiktok.com' in url:
            tiktok_res = YtDlpService._fetch_tiktok_fallback(url)
            if tiktok_res and tiktok_res.get('video_formats'):
                return tiktok_res

        ydl_opts = YtDlpService._get_base_opts()
        ydl_opts['skip_download'] = True
        ydl_opts['ignoreerrors'] = True

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 1st pass: Raw extraction with process=False for carousels & photo posts
                info = ydl.extract_info(url, download=False, process=False)

                title = info.get('title', 'Unknown Title') if info else 'Unknown Title'
                thumbnail = info.get('thumbnail', '') if info else ''
                duration = info.get('duration', 0) if info else 0
                uploader = info.get('uploader', info.get('channel', info.get('extractor_key', 'Unknown Uploader'))) if info else 'Unknown Uploader'
                fallback_url = info.get('url', '') if info else ''
                video_formats_local = []
                audio_url = ""

                entries = info.get('entries') or [] if info else []
                if entries:
                    for idx, entry in enumerate(entries, 1):
                        if not entry or not isinstance(entry, dict):
                            continue
                        entry_title = entry.get('title') or f"Media #{idx}"
                        
                        # Extract video formats in carousel entry
                        entry_formats = entry.get('formats') or []
                        for f in entry_formats:
                            height = f.get('height')
                            f_url = f.get('url')
                            if height and height >= 144 and f_url:
                                video_formats_local.append({
                                    'format_id': f.get('format_id', f"entry_vid_{idx}"),
                                    'resolution': f"{height}p",
                                    'height': height,
                                    'ext': f.get('ext', 'mp4'),
                                    'filesize_mb': round((f.get('filesize') or 0) / (1024 * 1024), 1),
                                    'label': f"Video #{idx} ({height}p)",
                                    'download_url': f_url
                                })

                        # Extract highest-res photo in carousel entry
                        entry_thumbs = entry.get('thumbnails') or []
                        if entry_thumbs:
                            best_thumb = max(entry_thumbs, key=lambda t: (t.get('width') or 0) * (t.get('height') or 0))
                            thumb_url = best_thumb.get('url')
                            if thumb_url:
                                w = best_thumb.get('width', 0)
                                h = best_thumb.get('height', 0)
                                dim_str = f"{w}x{h}" if w and h else "HQ"
                                video_formats_local.append({
                                    'format_id': f"photo_{idx}",
                                    'resolution': f"Photo #{idx}",
                                    'height': h or 1080,
                                    'ext': 'jpg',
                                    'filesize_mb': 0,
                                    'label': f"Photo #{idx} ({dim_str})",
                                    'download_url': thumb_url
                                })

                # 2nd pass: Full process inspection for single videos/audio if no carousel entries found
                if not video_formats_local:
                    full_info = ydl.extract_info(url, download=False)
                    if full_info:
                        title = full_info.get('title', title)
                        thumbnail = full_info.get('thumbnail', thumbnail)
                        uploader = full_info.get('uploader', uploader)
                        duration = full_info.get('duration', duration)
                        fallback_url = full_info.get('url', fallback_url)
                        raw_formats = full_info.get('formats', [])

                        seen_res = set()
                        for f in raw_formats:
                            format_id = f.get('format_id')
                            ext = f.get('ext', 'mp4')
                            vcodec = f.get('vcodec', 'none')
                            acodec = f.get('acodec', 'none')
                            height = f.get('height')
                            filesize = f.get('filesize') or f.get('filesize_approx') or 0
                            download_url = f.get('url', '') or fallback_url

                            if height and height >= 144:
                                res_label = f"{height}p"
                                if res_label not in seen_res:
                                    seen_res.add(res_label)
                                    video_formats_local.append({
                                        'format_id': format_id,
                                        'resolution': res_label,
                                        'height': height,
                                        'ext': ext if ext in ['mp4', 'webm'] else 'mp4',
                                        'filesize': filesize,
                                        'filesize_mb': round(filesize / (1024 * 1024), 1) if filesize else 0,
                                        'label': f"{res_label} ({ext.upper()})",
                                        'download_url': download_url
                                    })

                            if vcodec == 'none' and acodec != 'none' and f.get('url'):
                                if not audio_url:
                                    audio_url = f.get('url')

                        # Single photo thumbnail fallback
                        if not video_formats_local and full_info.get('thumbnails'):
                            best_thumb = max(full_info['thumbnails'], key=lambda t: (t.get('width') or 0) * (t.get('height') or 0))
                            if best_thumb.get('url'):
                                video_formats_local.append({
                                    'format_id': 'photo_hq',
                                    'resolution': 'Photo',
                                    'height': best_thumb.get('height', 1080),
                                    'ext': 'jpg',
                                    'filesize_mb': 0,
                                    'label': 'High-Res Photo',
                                    'download_url': best_thumb['url']
                                })

                # Instagram Fallback parser if still no formats found
                if 'instagram.com' in url and not video_formats_local:
                    ig_res = YtDlpService._fetch_instagram_fallback(url)
                    if ig_res and ig_res.get('video_formats'):
                        return ig_res

                # TikTok Fallback parser if yt-dlp pass produced no video_formats
                if 'tiktok.com' in url and not video_formats_local:
                    tiktok_res = YtDlpService._fetch_tiktok_fallback(url)
                    if tiktok_res and tiktok_res.get('video_formats'):
                        return tiktok_res

                if not video_formats_local and (thumbnail or fallback_url):
                    photo_link = thumbnail or fallback_url
                    if photo_link:
                        video_formats_local.append({
                            'format_id': 'photo_default',
                            'resolution': 'Photo',
                            'height': 1080,
                            'ext': 'jpg',
                            'filesize_mb': 0,
                            'label': 'Photo / Media',
                            'download_url': photo_link
                        })

                if not video_formats_local and not audio_url and not fallback_url:
                    if 'instagram.com' in url:
                        ig_res = YtDlpService._fetch_instagram_fallback(url)
                        if ig_res and ig_res.get('video_formats'):
                            return ig_res

                    if any(domain in url.lower() for domain in ['tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com', 'instagram.com', 'twitter.com', 'x.com']):
                        return {
                            'status': 'error',
                            'error': 'Instagram/TikTok saytidan media o\'qib bo\'lmadi. Qayta urinib ko\'ring.'
                        }
                    return {
                        'status': 'error',
                        'error': 'Media extraction failed or no playable media found for this link.'
                    }

                video_formats_local.sort(key=lambda x: x.get('height', 0), reverse=True)

                if not thumbnail and video_formats_local:
                    thumbnail = video_formats_local[0]['download_url']

                if not audio_url:
                    audio_url = fallback_url

                return {
                    'status': 'success',
                    'title': title,
                    'thumbnail': thumbnail,
                    'duration': duration,
                    'duration_str': YtDlpService._format_duration(duration),
                    'uploader': uploader,
                    'video_formats': video_formats_local,
                    'audio_url': audio_url,
                    'fallback_url': fallback_url,
                    'original_url': url
                }
        except Exception as e:
            if 'instagram.com' in url:
                ig_res = YtDlpService._fetch_instagram_fallback(url)
                if ig_res and ig_res.get('video_formats'):
                    return ig_res

            err_msg = str(e).lower()
            if any(k in err_msg for k in ['timeout', 'connectionreseterror', 'ssl', 'connection', '10054', 'blocked', 'banned']):
                return {
                    'status': 'error',
                    'error': 'Serverda tarmoq ulanishi xatoligi yuz berdi. Qayta urinib ko\'ring.'
                }
            return {
                'status': 'error',
                'error': str(e)
            }

    @staticmethod
    def _fetch_instagram_fallback(url):
        """Fallback extractor for Instagram using Mobile User-Agents to extract media metadata."""
        mobile_user_agents = [
            'Instagram 219.0.0.12.117 Android (31/12; 480dpi; 1080x2400; samsung; SM-G998B; o1s; exynos2100; en_US; 340454471)',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (Linux; Android 12; SM-S906B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Mobile Safari/537.36',
        ]

        video_formats = []
        thumbnail = ""
        title = "Instagram Media"

        for ua in mobile_user_agents:
            try:
                resp = requests.get(
                    url,
                    headers={
                        'User-Agent': ua,
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                    },
                    timeout=12,
                    verify=False
                )
                if resp.ok:
                    page_html = resp.text

                    # Check og:video
                    og_video_match = re.search(r'<meta[^>]+property=["\']og:video["\'][^>]+content=["\']([^"\']+)', page_html) or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video["\']', page_html)
                    if og_video_match:
                        video_url = og_video_match.group(1).replace('&amp;', '&')
                        video_formats.append({
                            'format_id': 'ig_mobile_video',
                            'resolution': 'HD Video',
                            'height': 1080,
                            'ext': 'mp4',
                            'filesize_mb': 0,
                            'label': 'Instagram HD Video',
                            'download_url': video_url
                        })

                    # Check og:image
                    og_image_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page_html) or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', page_html)
                    if og_image_match:
                        photo_url = og_image_match.group(1).replace('&amp;', '&')
                        thumbnail = photo_url
                        if not video_formats:
                            video_formats.append({
                                'format_id': 'ig_mobile_photo',
                                'resolution': 'HQ Photo',
                                'height': 1080,
                                'ext': 'jpg',
                                'filesize_mb': 0,
                                'label': 'Instagram HQ Photo',
                                'download_url': photo_url
                            })

                    # Check og:title
                    og_title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page_html) or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', page_html)
                    if og_title_match:
                        title = html.unescape(og_title_match.group(1).replace('&amp;', '&'))



                    if video_formats:
                        break
            except Exception:
                pass

        if video_formats:
            return {
                'status': 'success',
                'title': html.unescape(title),
                'thumbnail': thumbnail or (video_formats[0]['download_url'] if video_formats else ''),
                'uploader': 'Instagram User',
                'video_formats': video_formats,
                'audio_url': video_formats[0]['download_url'] if video_formats else '',
                'duration': 0,
                'duration_str': '00:00',
                'fallback_url': video_formats[0]['download_url'] if video_formats else '',
                'original_url': url
            }

        return None



    @staticmethod
    def download_media(url, format_id, is_audio, output_dir):
        """Download video or audio using yt_dlp to local output directory."""
        if format_id and str(format_id).startswith('ig_fallback'):
            # Directly stream download fallback URLs
            res = FileDownloadService.download_direct_file(url, output_dir)
            return {
                'title': res['file_name'],
                'file_name': res['file_name'],
                'file_path': res['file_path'],
                'file_size': res['file_size'],
                'duration': 0
            }

        filename_tmpl = f"%(title).50s_{uuid.uuid4().hex[:8]}.%(ext)s"
        output_template = os.path.join(output_dir, filename_tmpl)

        ydl_opts = YtDlpService._get_base_opts()
        ydl_opts['outtmpl'] = output_template

        if is_audio:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [],
            })
        else:
            if format_id and format_id not in ['photo_default', 'ig_fallback_photo', 'ig_fallback_video']:
                ydl_opts['format'] = format_id
            else:
                ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                
                # Check if file exists or check actual created file
                if not os.path.exists(downloaded_file):
                    # Search directory for file with matching UUID prefix
                    base_name = os.path.basename(downloaded_file).split('_')[-1].split('.')[0]
                    for file in os.listdir(output_dir):
                        if base_name in file:
                            downloaded_file = os.path.join(output_dir, file)
                            break

                file_size = os.path.getsize(downloaded_file) if os.path.exists(downloaded_file) else 0
                file_name = os.path.basename(downloaded_file)

                return {
                    'title': info.get('title', file_name),
                    'file_name': file_name,
                    'file_path': downloaded_file,
                    'file_size': file_size,
                    'duration': info.get('duration', 0)
                }
        except Exception:
            # Fallback to direct HTTP download if yt-dlp failed
            res = FileDownloadService.download_direct_file(url, output_dir)
            return {
                'title': res['file_name'],
                'file_name': res['file_name'],
                'file_path': res['file_path'],
                'file_size': res['file_size'],
                'duration': 0
            }

    @staticmethod
    def _format_duration(seconds):
        if not seconds:
            return "00:00"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


class FileDownloadService:
    @staticmethod
    def download_direct_file(url, output_dir):
        """Download file directly from HTTP/HTTPS URL with streaming."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()

        # Determine file name
        content_disposition = response.headers.get('Content-Disposition')
        file_name = None
        
        if content_disposition:
            names = re.findall('filename=["\']?([^"\';]+)["\']?', content_disposition)
            if names:
                file_name = names[0]

        if not file_name:
            parsed_path = urlparse(url).path
            file_name = unquote(os.path.basename(parsed_path))

        if not file_name or '.' not in file_name:
            file_name = f"download_{uuid.uuid4().hex[:8]}.bin"
            
        file_name = f"{uuid.uuid4().hex[:6]}_{file_name}"
        file_path = os.path.join(output_dir, file_name)

        total_size = 0
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)

        return {
            'file_name': file_name,
            'file_path': file_path,
            'file_size': total_size,
            'original_url': url
        }


import zipfile
from PIL import ImageDraw, ImageFont

class ImageConverterService:
    PAGE_SIZES_300DPI = {
        'a4': (2480, 3508),
        'letter': (2550, 3300),
        'legal': (2550, 4200),
        'a3': (3508, 4960),
        'a5': (1748, 2480),
    }

    @staticmethod
    def convert_images_to_pdf(image_paths, output_path, rotations=None, page_size='a4', orientation='auto', margin_mm=0, quality=90, page_numbers=False):
        """
        Convert a list of images to a customized single PDF document.
        Supports rotations per image, page sizes (A4, Letter, Legal, etc.), orientation, margins, quality, and page numbers.
        """
        valid_paths = [p for p in image_paths if os.path.exists(p)]
        if not valid_paths:
            raise ValueError("No valid image files provided.")

        rotations = rotations or [0] * len(valid_paths)
        if len(rotations) < len(valid_paths):
            rotations += [0] * (len(valid_paths) - len(rotations))

        margin_px = int(float(margin_mm) * 11.81)  # ~11.81 px per mm at 300 DPI
        processed_pages = []
        total_pages = len(valid_paths)

        for idx, path in enumerate(valid_paths):
            rot_deg = int(rotations[idx] or 0) % 360
            with Image.open(path) as img:
                img = img.convert('RGB')
                
                # Apply rotation (Pillow rotate is CCW, so -rot_deg for CW)
                if rot_deg != 0:
                    img = img.rotate(-rot_deg, expand=True)

                img_w, img_h = img.size

                # Determine canvas size based on page_size & orientation
                ps_key = str(page_size).lower().strip()
                if ps_key == 'fit' or ps_key not in ImageConverterService.PAGE_SIZES_300DPI:
                    canvas_w = img_w + (2 * margin_px)
                    canvas_h = img_h + (2 * margin_px)
                else:
                    base_w, base_h = ImageConverterService.PAGE_SIZES_300DPI[ps_key]
                    ori_key = str(orientation).lower().strip()
                    if ori_key == 'landscape':
                        canvas_w, canvas_h = max(base_w, base_h), min(base_w, base_h)
                    elif ori_key == 'portrait':
                        canvas_w, canvas_h = min(base_w, base_h), max(base_w, base_h)
                    else:  # auto
                        if img_w > img_h:
                            canvas_w, canvas_h = max(base_w, base_h), min(base_w, base_h)
                        else:
                            canvas_w, canvas_h = min(base_w, base_h), max(base_w, base_h)

                canvas = Image.new('RGB', (canvas_w, canvas_h), (255, 255, 255))

                # Calculate available printable space
                avail_w = max(canvas_w - (2 * margin_px), 100)
                avail_h = max(canvas_h - (2 * margin_px), 100)

                # Scale image proportionally
                ratio = min(avail_w / img_w, avail_h / img_h)
                scaled_w = int(img_w * ratio)
                scaled_h = int(img_h * ratio)

                resample_method = getattr(Image, 'Resampling', Image).LANCZOS
                scaled_img = img.resize((scaled_w, scaled_h), resample=resample_method)

                pos_x = margin_px + (avail_w - scaled_w) // 2
                pos_y = margin_px + (avail_h - scaled_h) // 2

                canvas.paste(scaled_img, (pos_x, pos_y))

                # Draw page numbers if enabled
                if page_numbers:
                    draw = ImageDraw.Draw(canvas)
                    text = f"Page {idx + 1} of {total_pages}"
                    font_size = max(int(canvas_h * 0.018), 24)
                    try:
                        font = ImageFont.truetype("arial.ttf", font_size)
                    except Exception:
                        font = ImageFont.load_default()
                    
                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]

                    tx = (canvas_w - text_w) // 2
                    ty = canvas_h - margin_px - text_h - 20 if margin_px > 30 else canvas_h - text_h - 40
                    ty = max(ty, canvas_h - 80)

                    # Draw subtle background pill behind text
                    draw.rectangle([tx - 12, ty - 6, tx + text_w + 12, ty + text_h + 6], fill=(240, 240, 240, 200))
                    draw.text((tx, ty), text, fill=(60, 60, 60), font=font)

                processed_pages.append(canvas)

        if not processed_pages:
            raise ValueError("Failed to process images for PDF generation.")

        # Save to PDF
        q_val = min(max(int(quality or 90), 10), 100)
        first_page = processed_pages[0]
        first_page.save(
            output_path,
            "PDF",
            resolution=300.0,
            save_all=True,
            append_images=processed_pages[1:],
            quality=q_val
        )
        return output_path

    @staticmethod
    def convert_image_format(input_path, target_format, output_path, rotation=0, quality=90):
        """Convert single image from one format to another (PNG, JPEG, WEBP)."""
        with Image.open(input_path) as img:
            rot_deg = int(rotation or 0) % 360
            if rot_deg != 0:
                img = img.rotate(-rot_deg, expand=True)

            target_format_upper = target_format.upper()
            if target_format_upper in ['JPG', 'JPEG']:
                img = img.convert('RGB')
                img.save(output_path, format='JPEG', quality=int(quality or 90))
            elif target_format_upper == 'WEBP':
                img.save(output_path, format='WEBP', quality=int(quality or 90))
            else:
                img.save(output_path, format=target_format_upper)
        return output_path

    @staticmethod
    def create_converted_zip(image_paths, output_path, rotations=None, target_format='pdf', page_size='a4', orientation='auto', margin_mm=0, quality=90, page_numbers=False):
        """Create a ZIP archive containing individually converted files or PDFs."""
        valid_paths = [p for p in image_paths if os.path.exists(p)]
        if not valid_paths:
            raise ValueError("No valid image files provided.")

        rotations = rotations or [0] * len(valid_paths)
        temp_dir = os.path.dirname(output_path)

        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for idx, path in enumerate(valid_paths):
                rot = rotations[idx] if idx < len(rotations) else 0
                base_name = os.path.splitext(os.path.basename(path))[0].replace('upload_', '')
                
                if target_format.lower() == 'pdf':
                    single_out_name = f"{base_name}_p{idx+1}.pdf"
                    single_out_path = os.path.join(temp_dir, f"temp_{idx}_{single_out_name}")
                    ImageConverterService.convert_images_to_pdf(
                        [path], single_out_path, rotations=[rot], page_size=page_size,
                        orientation=orientation, margin_mm=margin_mm, quality=quality, page_numbers=page_numbers
                    )
                else:
                    ext = target_format.lower()
                    if ext == 'jpeg':
                        ext = 'jpg'
                    single_out_name = f"{base_name}_converted.{ext}"
                    single_out_path = os.path.join(temp_dir, f"temp_{idx}_{single_out_name}")
                    ImageConverterService.convert_image_format(path, target_format, single_out_path, rotation=rot, quality=quality)

                zipf.write(single_out_path, arcname=single_out_name)
                if os.path.exists(single_out_path):
                    try:
                        os.remove(single_out_path)
                    except Exception:
                        pass

        return output_path

