"""Testes de integração da FastTube API (sem chamadas reais ao YouTube)."""

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app

BASE = '/api'


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        yield c


# ── /api/health ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_health(client):
    r = await client.get(f'{BASE}/health')
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ok'
    assert 'uptime_seconds' in body
    assert 'ffmpeg' in body


# ── / (Web UI) ────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_web_ui(client):
    r = await client.get('/')
    assert r.status_code == 200
    assert 'text/html' in r.headers['content-type']
    assert b'<title>' in r.content


# ── /api/analyze — validações de entrada ─────────────────────────────────────

@pytest.mark.anyio
async def test_analyze_missing_url(client):
    r = await client.post(f'{BASE}/analyze', json={'url': ''})
    assert r.status_code == 400
    assert 'URL' in r.json()['detail']


@pytest.mark.anyio
async def test_analyze_channel_url(client):
    r = await client.post(
        f'{BASE}/analyze',
        json={'url': 'https://www.youtube.com/@PewDiePie'},
    )
    assert r.status_code == 400
    assert 'canal' in r.json()['detail'].lower()


# ── /api/download — validações de entrada ────────────────────────────────────

@pytest.mark.anyio
async def test_download_missing_url(client):
    r = await client.post(f'{BASE}/download', json={'url': '', 'format_id': '720p'})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_download_returns_job_id(client, monkeypatch):
    """Confirma que o endpoint retorna job_id sem chamar yt_dlp."""
    from api.services import downloader

    def fake_start(job_id, urls, metadata, fmt, mp3):
        pass  # não inicia thread real

    monkeypatch.setattr(downloader, 'start_download_thread', fake_start)

    r = await client.post(
        f'{BASE}/download',
        json={'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'format_id': 'mp3'},
    )
    assert r.status_code == 200
    body = r.json()
    assert body['success'] is True
    assert 'job_id' in body


# ── /api/progress — job inexistente ──────────────────────────────────────────

@pytest.mark.anyio
async def test_progress_unknown_job(client):
    """SSE deve retornar evento de erro para job desconhecido."""
    r = await client.get(f'{BASE}/progress/nao-existe-esse-job')
    # StreamingResponse sempre retorna 200; o erro vem no payload SSE
    assert r.status_code == 200
    assert b'error' in r.content


# ── /api/cancel — job inexistente ────────────────────────────────────────────

@pytest.mark.anyio
async def test_cancel_unknown_job(client):
    r = await client.post(f'{BASE}/cancel/nao-existe')
    assert r.status_code == 404


# ── /api/file e /api/stream — id inválido ────────────────────────────────────

@pytest.mark.anyio
async def test_file_not_found(client):
    r = await client.get(f'{BASE}/file/id-invalido')
    assert r.status_code == 404


@pytest.mark.anyio
async def test_stream_not_found(client):
    r = await client.get(f'{BASE}/stream/id-invalido')
    assert r.status_code == 404
