"""Endpoints para download e streaming de arquivos processados."""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from api.state import progress_store
from api.utils.helpers import get_mime_type

router = APIRouter()


def _content_disposition(name: str, disp: str = 'attachment') -> str:
    """Gera Content-Disposition com RFC 5987 para nomes com caracteres não-ASCII."""
    encoded = quote(name, safe='')
    if encoded == name:
        return f'{disp}; filename="{name}"'
    return f"{disp}; filename*=UTF-8''{encoded}"


def _find_file(file_id: str) -> Path:
    """Localiza o arquivo no progress_store e valida existência."""
    for prog in progress_store.values():
        for info in prog.get('completed_files', []):
            if info['id'] == file_id:
                path = Path(info['path'])
                if path.exists():
                    return path
                raise HTTPException(404, 'Arquivo não encontrado no disco')
    raise HTTPException(404, 'ID de arquivo inválido')


@router.get('/file/{file_id}')
async def download_file(file_id: str):
    """Retorna o arquivo como attachment (força download no browser)."""
    path = _find_file(file_id)
    return FileResponse(
        path,
        media_type=get_mime_type(path),
        headers={'Content-Disposition': _content_disposition(path.name, 'attachment')},
    )


@router.get('/stream/{file_id}')
async def stream_file(file_id: str, request: Request):
    """Streaming com suporte a HTTP Range — necessário para players de vídeo/áudio."""
    path = _find_file(file_id)
    file_size = path.stat().st_size
    mime = get_mime_type(path)
    range_header = request.headers.get('Range')

    if range_header:
        start, end = _parse_range(range_header, file_size)
        chunk = end - start + 1

        async def _iter_range():
            with open(path, 'rb') as f:
                f.seek(start)
                remaining = chunk
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return StreamingResponse(
            _iter_range(),
            status_code=206,
            media_type=mime,
            headers={
                'Content-Range': f'bytes {start}-{end}/{file_size}',
                'Accept-Ranges': 'bytes',
                'Content-Length': str(chunk),
            },
        )

    # Resposta completa com Accept-Ranges para habilitar seek posterior
    async def _iter_full():
        with open(path, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                yield data

    return StreamingResponse(
        _iter_full(),
        media_type=mime,
        headers={
            'Accept-Ranges': 'bytes',
            'Content-Length': str(file_size),
            'Content-Disposition': _content_disposition(path.name, 'inline'),
        },
    )


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """Retorna (start, end) a partir do header Range: bytes=start-end."""
    try:
        unit, ranges = range_header.strip().split('=')
        if unit != 'bytes':
            raise ValueError
        start_str, end_str = ranges.split('-')
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        end = min(end, file_size - 1)
        if start > end:
            raise ValueError
        return start, end
    except Exception:
        raise HTTPException(416, 'Range inválido')
