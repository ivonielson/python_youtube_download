"""Busca de vídeos no YouTube via yt-dlp."""

import yt_dlp
from fastapi import APIRouter, Query

from api.utils.anti_detect import base_ydl_opts

router = APIRouter()


@router.get('/search')
async def search_youtube(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=20),
):
    opts = {
        **base_ydl_opts(),
        'quiet': True,
        'extract_flat': True,
        'skip_download': True,
        'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f'ytsearch{limit}:{q}', download=False)
        entries = (info.get('entries') or []) if info else []
        results = []
        for e in entries:
            if not e:
                continue
            vid_id = e.get('id', '')
            thumb = e.get('thumbnail') or (
                f'https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg' if vid_id else None
            )
            results.append({
                'id': vid_id,
                'title': e.get('title', ''),
                'url': e.get('url') or (
                    f'https://www.youtube.com/watch?v={vid_id}' if vid_id else ''
                ),
                'thumbnail': thumb,
                'duration': e.get('duration_string') or _fmt_duration(e.get('duration')),
                'channel': e.get('channel') or e.get('uploader', ''),
                'view_count': e.get('view_count'),
            })
        return {'success': True, 'results': results}
    except Exception as exc:
        return {'success': False, 'error': str(exc), 'results': []}


def _fmt_duration(secs: int | None) -> str | None:
    if not secs:
        return None
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'
