import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from api.config import settings
from api.services.downloader import start_download_thread
from api.state import active_downloads, progress_store
from api.utils.cleanup import cleanup_old_files
from api.utils.helpers import extract_clean_url
from api.utils.paths import CONVERTED_DIR, DOWNLOAD_DIR, TEMP_DIR

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class DownloadRequest(BaseModel):
    url: str = ''
    format_id: str = 'bestvideo+bestaudio/best'
    urls: list[str] | None = None
    video_metadata: list[dict] | None = None


@router.post('/download')
@limiter.limit(settings.RATE_LIMIT_DOWNLOAD)
async def start_download(request: Request, body: DownloadRequest):
    url = body.url.strip()
    format_id = body.format_id.strip() or 'bestvideo+bestaudio/best'
    is_mp3 = format_id == 'mp3'

    if not url and not body.urls:
        raise HTTPException(400, 'URL não fornecida')

    # Limitar downloads simultâneos
    running = sum(
        1 for p in progress_store.values() if p.get('status') == 'running'
    )
    if running >= settings.MAX_CONCURRENT_DOWNLOADS:
        raise HTTPException(
            429,
            f'Servidor ocupado ({running} downloads ativos). Tente em instantes.',
        )

    job_id = str(uuid.uuid4())
    clean_url = extract_clean_url(url) if url else None
    target_urls = body.urls if body.urls else ([clean_url] if clean_url else [])
    metadata_list = body.video_metadata or []

    progress_store[job_id] = {
        'status': 'pending',
        'percent': 0,
        'message': 'Iniciando…',
        'filename': None,
        'error': None,
        'downloaded': 0,
        'total': len(target_urls),
        'failed': [],
        'completed_files': [],
        'current_video': None,
        'current_index': 0,
        'is_playlist': len(target_urls) > 1,
        'created_at': datetime.now().isoformat(),
        'cancelled': False,
        'session_id': request.headers.get('X-Session-ID', ''),
    }
    active_downloads[job_id] = {
        'cancel': False,
        'out_dir': str(DOWNLOAD_DIR / job_id),
    }

    start_download_thread(job_id, target_urls, metadata_list, format_id, is_mp3)

    return {'success': True, 'job_id': job_id}


@router.post('/cancel/{job_id}')
async def cancel_download(job_id: str):
    if job_id not in active_downloads:
        raise HTTPException(404, 'Job não encontrado')
    active_downloads[job_id]['cancel'] = True
    if job_id in progress_store:
        progress_store[job_id]['cancelled'] = True
        progress_store[job_id]['status'] = 'cancelled'
        progress_store[job_id]['message'] = '⚠️ Download cancelado — vídeos já baixados estão disponíveis'
    return {'success': True, 'message': 'Download cancelado. Arquivos já concluídos estão disponíveis.'}


@router.get('/progress/{job_id}')
async def progress(job_id: str):
    async def generate():
        last_count = 0
        while True:
            prog = progress_store.get(job_id)
            if not prog:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Job não encontrado'})}\n\n"
                break

            current_count = len(prog.get('completed_files', []))
            payload = dict(prog)
            if current_count > last_count:
                payload['new_files'] = prog['completed_files'][last_count:current_count]
                last_count = current_count

            yield f"data: {json.dumps(payload)}\n\n"

            if prog['status'] in ('done', 'error', 'cancelled'):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@router.get('/jobs')
async def list_jobs():
    """Retorna todos os jobs concluídos com arquivos disponíveis (para biblioteca)."""
    result = []
    for job_id, prog in progress_store.items():
        if prog.get('status') not in ('done', 'cancelled'):
            continue
        files = [
            f for f in prog.get('completed_files', [])
            if f.get('path') and Path(f['path']).exists()
        ]
        if not files:
            continue
        result.append({
            'id': job_id,
            'status': prog['status'],
            'is_playlist': prog.get('is_playlist', False),
            'created_at': prog.get('created_at', ''),
            'files': files,
        })
    result.sort(key=lambda x: x['created_at'], reverse=True)
    return result


@router.post('/cleanup')
async def cleanup():
    count_before = len(progress_store)
    await asyncio.to_thread(
        cleanup_old_files,
        [DOWNLOAD_DIR, CONVERTED_DIR, TEMP_DIR],
        progress_store,
        active_downloads,
        30,
    )
    removed_jobs = count_before - len(progress_store)
    return {'success': True, 'message': f'Limpeza concluída. {removed_jobs} jobs removidos.'}
