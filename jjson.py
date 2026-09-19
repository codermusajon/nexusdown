import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import yt_dlp

DEFAULT_URL = "https://youtu.be/ddhGg-7jS58?si=s9kVRkOx-MJEzbKD"
CHECK_TIMEOUT = 5
MAX_WORKERS = 8
COOKIES_FILE = "cookies.txt"

# 1080p+ formats are DASH/adaptive-only (video-only, no muxed audio) and YouTube
# gates them behind a GVS PO Token. A logged-in cookie session + a JS runtime
# (for the 'n' signature challenge) + a running bgutil PO-token provider
# (http://127.0.0.1:4416, see README) unlock the full itag ladder as plain
# HTTPS direct_urls. Without those, only the legacy 360p muxed format survives.
YDL_OPTS = {
    'quiet': True,
    'js_runtimes': {'node': {}},
    'remote_components': ['ejs:npm'],
}
if os.path.exists(COOKIES_FILE):
    YDL_OPTS['cookiefile'] = COOKIES_FILE


def check_url(url, session):
    """So'rov yuborib, havola to'g'ridan-to'g'ri ochilishini tekshiradi."""
    try:
        resp = session.get(url, stream=True, timeout=CHECK_TIMEOUT)
        resp.close()
        return resp.status_code
    except requests.RequestException:
        return None


def describe_format(f):
    has_video = bool(f.get('vcodec') and f.get('vcodec') != 'none')
    has_audio = bool(f.get('acodec') and f.get('acodec') != 'none')

    if has_video and has_audio:
        media_type = "To'liq video (Video + Ovoz)"
    elif has_video:
        media_type = "Faqat Video (Ovozsiz)"
    elif has_audio:
        media_type = "Faqat Audio (Ovoz)"
    else:
        media_type = "Media oqimi"

    filesize = f.get('filesize') or f.get('filesize_approx') or 0
    filesize_mb = round(filesize / (1024 * 1024), 2) if filesize else "Noma'lum"

    width, height = f.get('width'), f.get('height')
    res_str = f.get('resolution') or (f"{width}x{height}" if width and height else "Video")

    return {
        "media_type": media_type,
        "filesize_mb": filesize_mb,
        "res_str": res_str,
    }


def collect_direct_formats(formats):
    candidates = [
        f for f in formats
        if f.get('url') and not str(f.get('format_id', '')).startswith('sb')
    ]

    direct_formats = []
    print(f"Jami {len(formats)} ta format topildi. "
          f"{len(candidates)} tasi tekshirilmoqda...")

    with requests.Session() as session, ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_format = {
            pool.submit(check_url, f['url'], session): f for f in candidates
        }
        for future in as_completed(future_to_format):
            f = future_to_format[future]
            format_id = str(f.get('format_id', ''))
            status_code = future.result()

            if status_code not in (200, 206):
                print(f"[RAD ETILDI - HTTP {status_code}] Format {format_id}")
                continue

            info = describe_format(f)
            desc = {
                "format_id": format_id,
                "tavsif": f"{info['res_str']} ({f.get('format_note') or 'standard'}) - {info['media_type']}",
                "media_turi": info['media_type'],
                "kengaytma": f.get('ext'),
                "aniqlik": info['res_str'],
                "sifat_darajasi": f.get('format_note') or f.get('format'),
                "hajmi_mb": info['filesize_mb'],
                "fps": f.get('fps'),
                "video_codec": f.get('vcodec'),
                "audio_codec": f.get('acodec'),
                "tbr_kbps": f.get('tbr'),
                "http_status": status_code,
                # Bu havola faqat shu skript ishlagan kompyuter/IP dan ochiladi (googlevideo
                # havolalari IP va sessiyaga bog'langan) - boshqa brauzerda 403 berishi mumkin.
                "faqat_shu_kompyuterdan_ishlaydi": True,
                "direct_url": f['url'],
                "http_headers": f.get('http_headers', {}),
            }
            direct_formats.append(desc)
            print(f"[OK] Format {format_id} ({info['res_str']}, {info['media_type']}) - To'g'ridan-to'g'ri ochiladi!")

    # Natijalarni asl format tartibida saqlab qo'yamiz
    order = {str(f.get('format_id', '')): i for i, f in enumerate(candidates)}
    direct_formats.sort(key=lambda d: order.get(d['format_id'], 0))
    return direct_formats


def collect_direct_images(thumbnails):
    direct_images = []
    seen_urls = set()
    candidates = []

    for t in thumbnails:
        t_url = t.get('url')
        if not t_url or t_url in seen_urls:
            continue
        if any(keyword in t_url for keyword in ('maxresdefault', 'hq720', 'sddefault')):
            seen_urls.add(t_url)
            candidates.append(t)

    with requests.Session() as session, ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_thumb = {
            pool.submit(check_url, t['url'], session): t for t in candidates
        }
        for future in as_completed(future_to_thumb):
            t = future_to_thumb[future]
            status_code = future.result()
            if status_code not in (200, 206):
                continue

            direct_images.append({
                "id": t.get('id'),
                "tavsif": "Video muqovasi (High Resolution Cover Photo)",
                "kengaytma": "webp" if ".webp" in t['url'] else "jpg",
                "aniqlik": f"{t.get('width')}x{t.get('height')}" if t.get('width') else "Yuqori sifat",
                "http_status": status_code,
                "brauzerda_ochiladimi": True,
                "direct_url": t['url'],
            })  # i.ytimg.com rasm havolalari IP-ga bog'lanmagan, istalgan brauzerda ochiladi
            print(f"[OK] Rasm ({t['url'].split('/')[-1]}): Ishlayapti!")

    return direct_images


def format_duration(seconds):
    if not seconds:
        return "Noma'lum"
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def main(url):
    print("Videodan ma'lumotlar olinmoqda...")
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        print(f"[XATO] Video ma'lumotlarini olib bo'lmadi: {e}")
        sys.exit(1)

    formats = info.get('formats') or []
    direct_formats = collect_direct_formats(formats)
    direct_images = collect_direct_images(info.get('thumbnails') or [])

    result_data = {
        "video_nomi": info.get('title'),
        "kanal": info.get('uploader') or info.get('channel'),
        "davomiyligi_sekund": info.get('duration'),
        "davomiyligi_matn": format_duration(info.get('duration')),
        "youtube_asl_havola": info.get('webpage_url'),
        "jami_ishlaydigan_video_havolalari": len(direct_formats),
        "jami_ishlaydigan_rasm_havolalari": len(direct_images),
        "to_gridan_to_gri_video_havolalari": direct_formats,
        "to_gridan_to_gri_rasm_havolalari": direct_images,
    }

    with open("vfile.json", "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=4)

    print(f"\nBarcha to'g'ridan-to'g'ri ochiladigan havolalar "
          f"(Video: {len(direct_formats)}, Rasmlar: {len(direct_images)}) 'vfile.json' ga saqlandi!")


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    main(target_url)
