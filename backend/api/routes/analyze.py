import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

import yt_dlp

from api.config import settings
from api.utils.anti_detect import analyze_ydl_opts
from api.utils.helpers import (
    extract_clean_url,
    format_duration,
    get_thumbnail_url,
    height_to_label,
    is_channel_url,
    is_playlist_url,
)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class AnalyzeRequest(BaseModel):
    url: str


def _extract_info(opts: dict, url: str):
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _common_formats() -> list:
    return [
        {'id': 'bestvideo[height<=2160]+bestaudio/best', 'label': '4K (melhor disponível)', 'height': 2160},
        {'id': 'bestvideo[height<=1080]+bestaudio/best', 'label': '1080p', 'height': 1080},
        {'id': 'bestvideo[height<=720]+bestaudio/best',  'label': '720p',  'height': 720},
        {'id': 'bestvideo[height<=480]+bestaudio/best',  'label': '480p',  'height': 480},
        {'id': 'bestvideo[height<=360]+bestaudio/best',  'label': '360p',  'height': 360},
        {'id': 'mp3', 'label': '🎵 Somente MP3', 'height': 0},
    ]


def _extract_formats(info: dict) -> list:
    seen: dict = {}
    for f in info.get('formats', []):
        vcodec = f.get('vcodec', 'none')
        height = f.get('height') or 0
        if vcodec == 'none' or height == 0:
            continue
        has_audio = f.get('acodec', 'none') != 'none'
        existing = seen.get(height)
        if existing is None or (has_audio and not existing['_has_audio']):
            seen[height] = {**f, '_has_audio': has_audio}

    result = []
    for height, f in sorted(seen.items(), reverse=True):
        fps = f.get('fps') or 0
        fps_s = f' • {int(fps)}fps' if fps and fps > 30 else ''
        fsize = f.get('filesize') or f.get('filesize_approx') or 0
        size_s = f' • ~{fsize/1024/1024:.0f} MB' if fsize else ''
        selector = f'bestvideo[height<={height}]+bestaudio/bestvideo[height<={height}]/best[height<={height}]'
        result.append({
            'id': selector,
            'label': f'{height_to_label(height)}{fps_s}{size_s}',
            'height': height,
        })
    result.append({'id': 'mp3', 'label': '🎵 Somente MP3', 'height': 0})
    return result[:12]


@router.post('/analyze')
@limiter.limit(settings.RATE_LIMIT_ANALYZE)
async def analyze(request: Request, body: AnalyzeRequest):
    url = body.url.strip()
    if not url:
        raise HTTPException(400, 'URL não fornecida')

    clean_url = extract_clean_url(url)

    if is_channel_url(clean_url):
        raise HTTPException(
            400,
            '❌ URL de canal detectada. Cole a URL de um vídeo específico '
            'ou playlist verdadeira (com "list=PL...").',
        )

    is_pl = is_playlist_url(clean_url)
    ydl_opts = {
        **analyze_ydl_opts(),
        'extract_flat': False,
        'skip_download': True,
        'noplaylist': not is_pl,
        'ignoreerrors': True,
    }

    try:
        info = await asyncio.to_thread(_extract_info, ydl_opts, clean_url)
    except Exception as e:
        raise HTTPException(500, str(e))

    if not info:
        raise HTTPException(400, 'Não foi possível obter informações. Verifique a URL.')

    if is_pl and (info.get('_type') == 'playlist' or 'entries' in info):
        return _build_playlist_response(info)

    if info.get('availability') in ('private', 'deleted', 'unavailable'):
        raise HTTPException(400, 'Vídeo não disponível (privado ou removido).')

    return _build_video_response(info)


def _build_playlist_response(info: dict) -> dict:
    entries = list(info.get('entries') or [])
    if not entries:
        raise HTTPException(400, 'Nenhum vídeo encontrado na playlist.')

    items, failed = [], 0
    for idx, e in enumerate(entries[:200]):
        if not e or e.get('availability', 'public') in ('private', 'deleted', 'unavailable'):
            failed += 1
            continue
        vid = e.get('id', '')
        thumb = e.get('thumbnail')
        if not thumb and e.get('thumbnails'):
            thumb = e['thumbnails'][0].get('url')
        if not thumb and vid:
            thumb = get_thumbnail_url(vid, 'hq')
        items.append({
            'id': vid,
            'index': idx + 1,
            'title': e.get('title', 'Sem título'),
            'duration': format_duration(e.get('duration', 0)),
            'thumbnail': thumb,
            'url': e.get('url') or e.get('webpage_url') or f"https://www.youtube.com/watch?v={vid}",
        })

    return {
        'success': True,
        'type': 'playlist',
        'title': info.get('title', 'Playlist'),
        'count': len(items),
        'failed_count': failed,
        'items': items,
        'formats': _common_formats(),
    }


def _build_video_response(info: dict) -> dict:
    vid = info.get('id', '')
    thumb = info.get('thumbnail') or (get_thumbnail_url(vid, 'maxres') if vid else None)
    return {
        'success': True,
        'type': 'video',
        'title': info.get('title', 'Vídeo'),
        'thumbnail': thumb,
        'duration': format_duration(info.get('duration', 0)),
        'formats': _extract_formats(info),
    }


@router.get('/analyze-playlist')
@limiter.limit(settings.RATE_LIMIT_ANALYZE)
async def analyze_playlist_stream(request: Request, url: str = ''):
    clean_url = extract_clean_url(url) if url else ''

    async def generate():
        if not clean_url:
            yield f"data: {json.dumps({'event': 'error', 'message': 'URL não fornecida'})}\n\n"
            return

        ydl_opts = {
            **analyze_ydl_opts(),
            'extract_flat': True,
            'skip_download': True,
            'ignoreerrors': True,
        }
        try:
            info = await asyncio.to_thread(_extract_info, ydl_opts, clean_url)

            if not info:
                yield f"data: {json.dumps({'event': 'error', 'message': 'Playlist não encontrada.'})}\n\n"
                return

            entries = [
                e for e in (info.get('entries') or [])
                if e and e.get('availability', 'public') not in ('private', 'deleted', 'unavailable')
            ][:200]

            yield f"data: {json.dumps({'event': 'header', 'title': info.get('title', 'Playlist'), 'count': len(entries), 'formats': _common_formats()})}\n\n"

            for idx, e in enumerate(entries):
                vid = e.get('id', '')
                thumb = e.get('thumbnail') or (get_thumbnail_url(vid, 'hq') if vid else None)
                video_url = (
                    e.get('url') or e.get('webpage_url')
                    or (f"https://www.youtube.com/watch?v={vid}" if vid else '')
                )
                yield f"data: {json.dumps({'event': 'item', 'id': vid, 'index': idx + 1, 'title': e.get('title', 'Sem título'), 'duration': format_duration(e.get('duration', 0)), 'thumbnail': thumb, 'url': video_url})}\n\n"
                await asyncio.sleep(0)  # ceder controle ao event loop

            yield f"data: {json.dumps({'event': 'done'})}\n\n"

        except Exception as ex:
            yield f"data: {json.dumps({'event': 'error', 'message': str(ex)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
