"""vfile.json dagi googlevideo havolalarini shu kompyuter orqali (ishlaydigan
tarmoq bilan) qayta uzatadigan mahalliy server. Havolalar to'g'ridan-to'g'ri
brauzerga berilmaydi (IP/sessiyaga bog'langani uchun 403 beradi) - buning
o'rniga http://127.0.0.1:<port>/ ochiladi va u orqali istalgan formatni
o'ynatish/ko'rish mumkin.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests

VFILE = "vfile.json"
DEFAULT_PORT = 8899
VIDEO_KEY = "to_gridan_to_gri_video_havolalari"
IMAGE_KEY = "to_gridan_to_gri_rasm_havolalari"


def load_data():
    with open(VFILE, encoding="utf-8") as f:
        return json.load(f)


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.serve_index()
        if parsed.path.startswith("/stream/video/"):
            return self.serve_stream(parsed.path.rsplit("/", 1)[-1], "video")
        if parsed.path.startswith("/stream/image/"):
            return self.serve_stream(parsed.path.rsplit("/", 1)[-1], "image")
        self.send_error(404)

    def serve_index(self):
        try:
            data = load_data()
        except FileNotFoundError:
            return self.send_error(404, "vfile.json topilmadi - avval jjson.py ni ishga tushiring")

        videos = data.get(VIDEO_KEY, [])
        images = data.get(IMAGE_KEY, [])

        rows = [
            "<meta charset='utf-8'>",
            f"<h1>{data.get('video_nomi', '')}</h1>",
            "<h2>Video havolalari</h2><ul>",
        ]
        for i, v in enumerate(videos):
            rows.append(
                f"<li><a href='/stream/video/{i}' target='_blank'>"
                f"{v['tavsif']} &mdash; {v['hajmi_mb']} MB</a></li>"
            )
        rows.append("</ul><h2>Rasm havolalari</h2><ul>")
        for i, im in enumerate(images):
            rows.append(
                f"<li><a href='/stream/image/{i}' target='_blank'>"
                f"{im['tavsif']} &mdash; {im['aniqlik']}</a></li>"
            )
        rows.append("</ul>")

        body = "".join(rows).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_stream(self, idx_str, kind):
        try:
            idx = int(idx_str)
            data = load_data()
            items = data.get(VIDEO_KEY if kind == "video" else IMAGE_KEY, [])
            item = items[idx]
        except (ValueError, IndexError, FileNotFoundError):
            return self.send_error(404)

        url = item["direct_url"]
        req_headers = dict(item.get("http_headers", {})) if kind == "video" else {}
        range_header = self.headers.get("Range")
        if range_header:
            req_headers["Range"] = range_header

        try:
            upstream = requests.get(url, headers=req_headers, stream=True, timeout=15)
        except requests.RequestException as e:
            return self.send_error(502, str(e))

        if kind == "video":
            content_type = f"video/{item.get('kengaytma') or 'mp4'}"
        else:
            content_type = "image/webp" if item.get("kengaytma") == "webp" else "image/jpeg"

        self.send_response(upstream.status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        for h in ("Content-Length", "Content-Range"):
            if h in upstream.headers:
                self.send_header(h, upstream.headers[h])
        self.end_headers()

        try:
            for chunk in upstream.iter_content(chunk_size=262144):
                if chunk:
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        finally:
            upstream.close()

    def log_message(self, fmt, *args):
        print(f"[server] {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), ProxyHandler)
    print(f"Server tayyor: http://127.0.0.1:{port}/  (to'xtatish uchun Ctrl+C)")
    server.serve_forever()
