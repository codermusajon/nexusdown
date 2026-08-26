import requests
import re

url = "https://www.instagram.com/p/Dbi-k58Ix-H/"
oembed_url = f"https://api.instagram.com/oembed/?url={url}"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

r = requests.get(oembed_url, headers=headers)

# Find all meta tags
metas = re.findall(r'<meta\s+property="([^"]+)"\s+content="([^"]+)"', r.text) + re.findall(r'<meta\s+content="([^"]+)"\s+property="([^"]+)"', r.text)
print("METAS:", metas)

# Find any cdninstagram or fbcdn links in page
cdn_urls = re.findall(r'https://[^\s"\'<>]*(?:cdninstagram|fbcdn)[^\s"\'<>]*', r.text)
print("CDN URLS COUNT:", len(cdn_urls))
for u in cdn_urls[:10]:
    if '.jpg' in u or '.png' in u or '.mp4' in u or '.webp' in u:
        print("CDN URL:", u)
