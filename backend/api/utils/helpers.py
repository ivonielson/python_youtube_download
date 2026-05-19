import re
from urllib.parse import urlparse, parse_qs, urlencode


def sanitize(name: str, max_len: int = 180) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    return name[:max_len] or 'video'


def format_duration(seconds) -> str:
    if not seconds:
        return '0:00'
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f'{h}:{m:02}:{s:02}' if h else f'{m}:{s:02}'


def height_to_label(h) -> str:
    h = h or 0
    if h >= 2160: return '4K'
    if h >= 1440: return '2K'
    if h >= 1080: return '1080p'
    if h >= 720:  return '720p'
    if h >= 480:  return '480p'
    if h >= 360:  return '360p'
    if h > 0:     return f'{h}p'
    return 'SD'


def is_playlist_url(url: str) -> bool:
    radio_patterns = [
        r'list=RD[^&]+', r'list=WL', r'list=LL', r'list=HL', r'list=LM',
        r'start_radio=1', r'end_radio=1',
    ]
    for pattern in radio_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return False
    playlist_patterns = [
        r'list=PL[^&]+', r'list=OL[^&]+', r'list=UU[^&]+',
        r'list=FL[^&]+', r'/playlist\?list=',
    ]
    for pattern in playlist_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


def is_channel_url(url: str) -> bool:
    channel_patterns = [
        r'/channel/', r'/c/', r'/user/', r'/@[\w-]+/?$', r'youtube\.com/@',
    ]
    for pattern in channel_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


def extract_clean_url(url: str) -> str:
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    problematic_params = ['list', 'start_radio', 'end_radio', 'playnext', 'index']
    for param in problematic_params:
        if param in query_params:
            if param == 'list':
                list_value = query_params['list'][0]
                if list_value.startswith('RD') or list_value in ['WL', 'LL', 'HL', 'LM']:
                    del query_params[param]
            else:
                del query_params[param]
    new_query = urlencode(query_params, doseq=True)
    clean_url = parsed._replace(query=new_query).geturl()
    if clean_url == parsed.netloc or not clean_url:
        return f"{parsed.scheme}://{parsed.netloc}"
    return clean_url


def get_thumbnail_url(video_id: str, quality: str = 'hq') -> str:
    qualities = {
        'maxres': f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg',
        'hq':     f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
        'mq':     f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg',
        'default':f'https://img.youtube.com/vi/{video_id}/default.jpg',
    }
    return qualities.get(quality, qualities['hq'])


def get_mime_type(path) -> str:
    from pathlib import Path
    ext = Path(path).suffix.lower()
    return {
        '.mp4':  'video/mp4',
        '.webm': 'video/webm',
        '.mkv':  'video/x-matroska',
        '.mp3':  'audio/mpeg',
        '.m4a':  'audio/mp4',
        '.ogg':  'audio/ogg',
    }.get(ext, 'application/octet-stream')
