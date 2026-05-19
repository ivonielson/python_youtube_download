import time
from fastapi import APIRouter

router = APIRouter()
_start = time.time()


@router.get('/health')
async def health():
    from api.utils.paths import ffmpeg_ok
    return {
        'status': 'ok',
        'uptime_seconds': round(time.time() - _start),
        'ffmpeg': ffmpeg_ok(),
    }
