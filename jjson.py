import yt_dlp

url = "https://www.instagram.com/p/Dbi-k58lx-H/"

# Options to only print JSON metadata
ydl_opts = {
    'dump_single_json': True,   # Output JSON for a single URL
    'skip_download': True       # Do not download the media itself
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info_dict = ydl.extract_info(url, download=False)
    print(info_dict)  # This is a Python dict; you can also convert to JSON
