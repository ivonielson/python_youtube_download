import random
import time
from typing import Callable

from api.utils.paths import ffmpeg_location

_MOBILE_USER_AGENTS = [
    'com.google.android.youtube/17.36.4 (Linux; U; Android 13; Pixel 7) gzip',
    'com.google.android.youtube/17.31.35 (Linux; U; Android 12; SM-G991B) gzip',
    'com.google.android.youtube/17.29.34 (Linux; U; Android 11; Redmi Note 10) gzip',
    'com.google.ios.youtube/17.33.2 (iPhone14,3; U; CPU iOS 16_0 like Mac OS X)',
    'com.google.ios.youtube/17.30.1 (iPhone13,2; U; CPU iOS 15_6 like Mac OS X)',
]


def analyze_ydl_opts() -> dict:
    """Opções para extração de metadados — cliente web padrão, mais compatível com playlists."""
    return {
        'quiet': True,
        'no_warnings': True,
        'retries': 4,
        'socket_timeout': 30,
    }


def base_ydl_opts() -> dict:
    """Opções para download com anti-detecção: cliente mobile, headers realistas, delays."""
    ua = random.choice(_MOBILE_USER_AGENTS)
    opts: dict = {
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
            }
        },
        'http_headers': {
            'User-Agent': ua,
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
        'sleep_interval_requests': random.uniform(1.0, 3.0),
        'retries': 6,
        'fragment_retries': 6,
        'file_access_retries': 3,
        'socket_timeout': 30,
    }
    loc = ffmpeg_location()
    if loc:
        opts['ffmpeg_location'] = loc
    return opts


def playlist_delay(on_message: Callable[[str], None], idx: int, total: int):
    """Aguarda tempo aleatório entre vídeos de playlist para evitar detecção."""
    if idx >= total - 1:
        return
    delay = random.uniform(4.0, 14.0)
    on_message(f'Aguardando {delay:.0f}s antes do próximo vídeo… ({idx + 1}/{total})')
    time.sleep(delay)
