from flask import Flask, render_template, request, send_file, jsonify, Response, session
import yt_dlp
import os
import re
import json
import zipfile
import threading
import uuid
from pathlib import Path
import subprocess
import time
import random
import sys
import socket
import webbrowser
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime, timedelta
import shutil
import atexit
import signal


def _resource_path(relative: str) -> Path:
    """Retorna caminho correto para recursos — funciona em dev e no executável PyInstaller."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    return base / relative


def _ffmpeg_location() -> str | None:
    """Retorna pasta do FFmpeg embutido no executável, ou None para usar o do sistema."""
    if not getattr(sys, 'frozen', False):
        return None
    exe_name = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    ffmpeg_dir = _resource_path('ffmpeg')
    if (ffmpeg_dir / exe_name).exists():
        return str(ffmpeg_dir)
    return None


app = Flask(__name__, template_folder=str(_resource_path('templates')))
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024 * 1024  # 4GB max
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = os.urandom(24)

# ── Pastas ao lado do executável (ou ao lado do app.py em dev) ──────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent  # pasta do .exe
else:
    BASE_DIR = Path(__file__).parent        # pasta do app.py

DOWNLOAD_DIR  = BASE_DIR / 'downloads'
CONVERTED_DIR = BASE_DIR / 'converted'
TEMP_DIR      = BASE_DIR / 'temp'

for d in [DOWNLOAD_DIR, CONVERTED_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Estado de progresso em memória ──────────────────────────────────────────
progress_store: dict[str, dict] = {}
active_downloads: dict[str, dict] = {}
download_threads: dict[str, threading.Thread] = {}


# ── Limpeza automática de arquivos antigos ──────────────────────────────────

def cleanup_old_files(max_age_hours: int = 24):
    """Remove arquivos e pastas com mais de X horas, exceto downloads em andamento."""
    try:
        now = datetime.now()
        cutoff = now - timedelta(hours=max_age_hours)
        deleted_count = 0
        
        # Coletar jobs ativos
        active_jobs = set(active_downloads.keys())
        
        for folder in [DOWNLOAD_DIR, CONVERTED_DIR, TEMP_DIR]:
            if not folder.exists():
                continue
                
            for item in folder.iterdir():
                try:
                    # Verificar se é um job ativo
                    is_active_job = False
                    for job_id in active_jobs:
                        if job_id in str(item):
                            is_active_job = True
                            break
                    
                    if is_active_job:
                        continue  # Pular jobs ativos
                    
                    mod_time = datetime.fromtimestamp(item.stat().st_mtime)
                    if mod_time < cutoff:
                        if item.is_file():
                            item.unlink()
                            deleted_count += 1
                        elif item.is_dir():
                            shutil.rmtree(item)
                            deleted_count += 1
                except Exception as e:
                    print(f"Erro ao limpar {item}: {e}")
        
        # Limpar progress_store de jobs antigos e concluídos
        jobs_to_remove = []
        for job_id, prog in progress_store.items():
            if job_id in active_jobs:
                continue  # Pular jobs ativos
            if 'created_at' in prog:
                created = datetime.fromisoformat(prog['created_at'])
                if created < cutoff:
                    jobs_to_remove.append(job_id)
        
        for job_id in jobs_to_remove:
            if job_id in progress_store:
                del progress_store[job_id]
        
        if deleted_count > 0:
            print(f"[Cleanup] Removidos {deleted_count} arquivos/pastas com mais de {max_age_hours}h")
            
    except Exception as e:
        print(f"Erro na limpeza automática: {e}")


def start_cleanup_scheduler():
    """Inicia um scheduler para limpeza automática a cada 6 horas."""
    def cleanup_loop():
        while True:
            time.sleep(6 * 3600)  # 6 horas
            cleanup_old_files(24)
    
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    print("[Scheduler] Limpeza automática agendada (a cada 6 horas)")


start_cleanup_scheduler()
cleanup_old_files(24)


# ── Helpers ──────────────────────────────────────────────────────────────────

def sanitize(name: str, max_len: int = 180) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip('. ')
    return name[:max_len] or 'video'


def ffmpeg_ok() -> bool:
    loc = _ffmpeg_location()
    exe_name = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    ffmpeg_exe = str(Path(loc) / exe_name) if loc else 'ffmpeg'
    try:
        r = subprocess.run([ffmpeg_exe, '-version'], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def format_duration(seconds: int) -> str:
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
    """Detecta se a URL é explicitamente de uma playlist REAL do YouTube."""
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
    """Detecta URLs de canal."""
    channel_patterns = [
        r'/channel/', r'/c/', r'/user/', r'/@[\w-]+/?$', r'youtube\.com/@',
    ]
    for pattern in channel_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


def extract_clean_url(url: str) -> str:
    """Remove parâmetros de playlist/mix que causam problemas."""
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


def get_thumbnail_url(video_id: str, quality: str = 'hqdefault') -> str:
    """Gera URL da thumbnail do YouTube baseado no ID do vídeo."""
    qualities = {
        'maxres': f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg',
        'hq': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
        'mq': f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg',
        'default': f'https://img.youtube.com/vi/{video_id}/default.jpg',
    }
    return qualities.get(quality, qualities['hq'])


# ── Opções anti-detecção ─────────────────────────────────────────────────────

# User-Agents de apps mobile do YouTube para rotacionar
_MOBILE_USER_AGENTS = [
    # Android YouTube app
    'com.google.android.youtube/17.36.4 (Linux; U; Android 13; Pixel 7) gzip',
    'com.google.android.youtube/17.31.35 (Linux; U; Android 12; SM-G991B) gzip',
    'com.google.android.youtube/17.29.34 (Linux; U; Android 11; Redmi Note 10) gzip',
    # iOS YouTube app
    'com.google.ios.youtube/17.33.2 (iPhone14,3; U; CPU iOS 16_0 like Mac OS X)',
    'com.google.ios.youtube/17.30.1 (iPhone13,2; U; CPU iOS 15_6 like Mac OS X)',
]


def _analyze_ydl_opts() -> dict:
    """Opções para extração de metadados — usa cliente web padrão (mais compatível com playlists)."""
    return {
        'quiet': True,
        'no_warnings': True,
        'retries': 4,
        'socket_timeout': 30,
    }


def _base_ydl_opts() -> dict:
    """Opções para download com anti-detecção: cliente mobile, headers realistas e delays."""
    ua = random.choice(_MOBILE_USER_AGENTS)
    return {
        'quiet': True,
        'no_warnings': True,
        # Cliente Android é menos restrito que web durante downloads
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
        **({'ffmpeg_location': _ffmpeg_location()} if _ffmpeg_location() else {}),
    }


def _playlist_delay(prog: dict, idx: int, total: int):
    """Aguarda um tempo aleatório entre vídeos de playlist para evitar detecção."""
    if idx >= total - 1:
        return
    delay = random.uniform(4.0, 14.0)
    prog['message'] = f'Aguardando {delay:.0f}s antes do próximo vídeo… ({idx + 1}/{total})'
    time.sleep(delay)


# ── Análise de URL ────────────────────────────────────────────────────────────

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify(success=False, error='URL não fornecida'), 400

    clean_url = extract_clean_url(url)
    
    if is_channel_url(clean_url):
        return jsonify(
            success=False, 
            error='❌ URL de canal detectada. Cole a URL de um vídeo específico ou playlist verdadeira (com "list=PL...").'
        ), 400

    is_playlist = is_playlist_url(clean_url)

    ydl_opts = {
        **_analyze_ydl_opts(),
        'extract_flat': False,
        'skip_download': True,
        'noplaylist': not is_playlist,
        'ignoreerrors': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

    if not info:
        return jsonify(success=False, error='Não foi possível obter informações do vídeo. Verifique a URL ou tente novamente.'), 400

    if is_playlist and (info.get('_type') == 'playlist' or 'entries' in info):
        entries = list(info.get('entries') or [])
        
        if not entries:
            return jsonify(success=False, error='Nenhum vídeo encontrado na playlist.'), 400
            
        items = []
        failed_count = 0
        
        for idx, e in enumerate(entries):
            if not e:
                failed_count += 1
                continue
            
            if e.get('availability', 'public') in ['private', 'deleted', 'unavailable']:
                failed_count += 1
                continue
            
            video_id = e.get('id', '')
            video_url = e.get('url') or e.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}"
            
            thumbnail = e.get('thumbnail') or e.get('thumbnails', [{}])[0].get('url') if e.get('thumbnails') else None
            if not thumbnail and video_id:
                thumbnail = get_thumbnail_url(video_id, 'hq')
            
            items.append({
                'id': video_id,
                'index': idx + 1,
                'title': e.get('title', 'Sem título'),
                'duration': format_duration(e.get('duration', 0)),
                'thumbnail': thumbnail,
                'url': video_url,
            })
        
        if len(items) > 200:
            items = items[:200]
        
        if failed_count > 0:
            print(f"Aviso: {failed_count} vídeo(s) indisponível(is) na playlist")
            
        return jsonify(
            success=True,
            type='playlist',
            title=info.get('title', 'Playlist'),
            count=len(items),
            failed_count=failed_count,
            items=items,
            formats=_common_formats(),
        )

    if info.get('availability') in ['private', 'deleted', 'unavailable']:
        return jsonify(success=False, error='Este vídeo não está mais disponível (privado ou removido).'), 400
        
    formats = _extract_formats(info)
    
    thumbnail = info.get('thumbnail')
    if not thumbnail and info.get('id'):
        thumbnail = get_thumbnail_url(info.get('id'), 'maxres')
    
    return jsonify(
        success=True,
        type='video',
        title=info.get('title', 'Vídeo'),
        thumbnail=thumbnail,
        duration=format_duration(info.get('duration', 0)),
        formats=formats,
    )


def _common_formats():
    return [
        {'id': 'bestvideo[height<=2160]+bestaudio/best', 'label': '4K (melhor disponível)', 'height': 2160},
        {'id': 'bestvideo[height<=1080]+bestaudio/best', 'label': '1080p', 'height': 1080},
        {'id': 'bestvideo[height<=720]+bestaudio/best', 'label': '720p', 'height': 720},
        {'id': 'bestvideo[height<=480]+bestaudio/best', 'label': '480p', 'height': 480},
        {'id': 'bestvideo[height<=360]+bestaudio/best', 'label': '360p', 'height': 360},
        {'id': 'mp3', 'label': '🎵 Somente MP3', 'height': 0},
    ]


def _extract_formats(info: dict) -> list:
    raw = info.get('formats', [])
    seen = {}

    for f in raw:
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        height = f.get('height') or 0

        if vcodec == 'none' or height == 0:
            continue

        has_audio = acodec != 'none'
        existing = seen.get(height)

        if existing is None:
            seen[height] = {**f, '_has_audio': has_audio}
        elif has_audio and not existing['_has_audio']:
            seen[height] = {**f, '_has_audio': has_audio}

    result = []
    for height, f in sorted(seen.items(), reverse=True):
        label = height_to_label(height)
        fps = f.get('fps') or 0
        fps_s = f' • {int(fps)}fps' if fps and fps > 30 else ''
        fsize = f.get('filesize') or f.get('filesize_approx') or 0
        size_s = f' • ~{fsize/1024/1024:.0f} MB' if fsize else ''

        selector = f'bestvideo[height<={height}]+bestaudio/bestvideo[height<={height}]/best[height<={height}]'

        result.append({
            'id': selector,
            'label': f'{label}{fps_s}{size_s}',
            'height': height,
        })

    result.append({'id': 'mp3', 'label': '🎵 Somente MP3', 'height': 0})
    return result[:12]


# ── Download com suporte a cancelamento (mantém arquivos já baixados) ─────

@app.route('/download', methods=['POST'])
def start_download():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    format_id = (data.get('format_id') or 'bestvideo+bestaudio/best').strip()
    is_mp3 = format_id == 'mp3'
    urls = data.get('urls')
    video_metadata = data.get('video_metadata')

    if not url and not urls:
        return jsonify(success=False, error='URL não fornecida'), 400

    job_id = str(uuid.uuid4())
    progress_store[job_id] = {
        'status': 'pending',
        'percent': 0,
        'message': 'Iniciando…',
        'filename': None,
        'error': None,
        'downloaded': 0,
        'total': 0,
        'failed': [],
        'completed_files': [],
        'current_video': None,
        'current_index': 0,
        'is_playlist': urls is not None and len(urls) > 1,
        'created_at': datetime.now().isoformat(),
        'cancelled': False,
        'session_id': request.headers.get('X-Session-ID', '')
    }

    clean_url = extract_clean_url(url) if url else None
    target_urls = urls if urls else [clean_url] if clean_url else []
    metadata_list = video_metadata if video_metadata else []
    
    progress_store[job_id]['total'] = len(target_urls)
    
    # Armazenar informações para cancelamento
    active_downloads[job_id] = {
        'cancel': False,
        'out_dir': DOWNLOAD_DIR / job_id,
        'completed_before_cancel': []  # Para rastrear arquivos já concluídos
    }

    thread = threading.Thread(
        target=_do_individual_download,
        args=(job_id, target_urls, metadata_list, format_id, is_mp3),
        daemon=True,
    )
    download_threads[job_id] = thread
    thread.start()

    return jsonify(success=True, job_id=job_id)


@app.route('/cancel/<job_id>', methods=['POST'])
def cancel_download(job_id: str):
    """Cancela um download em andamento, mas mantém arquivos já baixados."""
    if job_id in active_downloads:
        active_downloads[job_id]['cancel'] = True
        
        if job_id in progress_store:
            progress_store[job_id]['cancelled'] = True
            progress_store[job_id]['status'] = 'cancelled'
            progress_store[job_id]['message'] = '⚠️ Download cancelado - Vídeos já baixados estão disponíveis'
        
        # NÃO remover a pasta - apenas marcar como cancelado
        # Os arquivos já baixados permanecem
        
        return jsonify(success=True, message='Download cancelado. Vídeos já baixados estão disponíveis.')
    
    return jsonify(success=False, error='Job não encontrado'), 404


def _do_individual_download(job_id: str, urls: list, metadata_list: list, format_id: str, is_mp3: bool):
    """Processa cada vídeo individualmente com suporte a cancelamento que mantém arquivos já baixados."""
    prog = progress_store[job_id]
    out_dir = DOWNLOAD_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    completed_files = []
    failed_videos = []
    successful = len(prog.get('completed_files', []))  # Começar com os já concluídos
    download_cancelled = False
    current_video_index = 0

    def _hook(d):
        if d['status'] == 'downloading':
            # Verificar se foi cancelado
            if job_id in active_downloads and active_downloads[job_id].get('cancel', False):
                raise Exception("Download cancelado pelo usuário")
            
            try:
                pct_raw = d.get('_percent_str', '0%').strip().replace('%', '')
                pct = float(pct_raw) if pct_raw else 0
                prog['current_progress'] = pct
                # Progresso baseado em vídeos concluídos + progresso atual
                overall_pct = ((successful + (pct / 100)) / len(urls)) * 100 if urls else 0
                prog['percent'] = min(overall_pct, 100)
            except ValueError:
                pass
            prog['message'] = f"Baixando: {prog.get('current_video', '...')} ({successful + 1}/{len(urls)})"

    try:
        prog['status'] = 'running'
        prog['message'] = f'Preparando download de {len(urls)} vídeo(s)...'

        for idx, video_url in enumerate(urls):
            current_video_index = idx
            
            # Verificar cancelamento antes de cada vídeo
            if job_id in active_downloads and active_downloads[job_id].get('cancel', False):
                download_cancelled = True
                prog['message'] = f'⚠️ Cancelado após {successful} vídeos baixados. Os arquivos já concluídos estão disponíveis.'
                break
            
            metadata = metadata_list[idx] if idx < len(metadata_list) else {}
            video_title = metadata.get('title', f'Vídeo {idx + 1}')
            prog['current_video'] = video_title
            prog['current_index'] = idx + 1
            prog['message'] = f'Processando {idx + 1}/{len(urls)}: {video_title[:50]}...'
            
            # Verificar se este vídeo já foi baixado (útil em caso de retomada)
            ext = '.mp3' if is_mp3 else '.mp4'
            existing_file = None
            for f in out_dir.iterdir():
                if f.suffix.lower() == ext and video_title[:50] in f.stem:
                    existing_file = f
                    break
            
            if existing_file:
                # Arquivo já existe, pular
                file_id = f"{job_id}_{idx}"
                file_url = f"/download-file/{file_id}"
                
                prog['completed_files'].append({
                    'id': file_id,
                    'name': existing_file.name,
                    'path': str(existing_file),
                    'url': file_url,
                    'title': video_title,
                    'thumbnail': metadata.get('thumbnail', ''),
                    'index': idx + 1
                })
                completed_files.append(str(existing_file))
                successful += 1
                prog['downloaded'] = successful
                prog['percent'] = (successful / len(urls)) * 100
                prog['message'] = f'⏭️ {video_title[:40]} já existe, pulando... ({successful}/{len(urls)})'
                continue
            
            if not video_url or 'youtube.com/watch' not in video_url:
                failed_videos.append({'url': video_url, 'title': video_title, 'error': 'URL inválida'})
                prog['failed'] = failed_videos
                successful += 1
                prog['downloaded'] = successful
                prog['percent'] = (successful / len(urls)) * 100
                continue
            
            if is_mp3:
                ydl_opts = {
                    **_base_ydl_opts(),
                    'format': 'bestaudio/best',
                    'outtmpl': str(out_dir / '%(title)s.%(ext)s'),
                    'noplaylist': True,
                    'ignoreerrors': True,
                    'progress_hooks': [_hook],
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'postprocessor_args': ['-ar', '44100'],
                    'keepvideo': False,
                }
            else:
                ydl_opts = {
                    **_base_ydl_opts(),
                    'format': format_id,
                    'outtmpl': str(out_dir / '%(title)s.%(ext)s'),
                    'noplaylist': True,
                    'ignoreerrors': True,
                    'progress_hooks': [_hook],
                    'merge_output_format': 'mp4',
                    'postprocessors': [{
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4',
                    }],
                }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                
                downloaded_file = None
                for f in out_dir.iterdir():
                    if f.suffix.lower() == ext and f.stem not in [Path(cf).stem for cf in completed_files]:
                        downloaded_file = f
                        break
                
                if downloaded_file:
                    file_id = f"{job_id}_{idx}"
                    file_url = f"/download-file/{file_id}"

                    prog['completed_files'].append({
                        'id': file_id,
                        'name': downloaded_file.name,
                        'path': str(downloaded_file),
                        'url': file_url,
                        'title': video_title,
                        'thumbnail': metadata.get('thumbnail', ''),
                        'index': idx + 1
                    })
                    completed_files.append(str(downloaded_file))
                    successful += 1
                    prog['downloaded'] = successful
                    prog['percent'] = (successful / len(urls)) * 100
                    prog['message'] = f'✅ {video_title[:40]} concluído! ({successful}/{len(urls)})'
                    # Delay aleatório entre vídeos para evitar detecção
                    _playlist_delay(prog, idx, len(urls))
                else:
                    raise Exception("Arquivo não encontrado após download")
                    
            except Exception as e:
                error_msg = str(e)
                if "cancelado" in error_msg.lower() or "cancelled" in error_msg.lower():
                    download_cancelled = True
                    prog['message'] = f'⚠️ Cancelado após {successful} vídeos baixados.'
                    break
                failed_videos.append({'url': video_url, 'title': video_title, 'error': error_msg})
                prog['failed'] = failed_videos
                successful += 1
                prog['downloaded'] = successful
                prog['percent'] = (successful / len(urls)) * 100
                prog['message'] = f'⚠️ Falha em "{video_title[:40]}": {error_msg[:60]}'
                continue

        if download_cancelled:
            prog['status'] = 'cancelled'
            prog['message'] = f'⚠️ Download cancelado - {successful} vídeos baixados com sucesso. Os arquivos estão disponíveis para download.'
            # NÃO remover a pasta - manter arquivos já baixados
        elif failed_videos:
            if successful == len(urls):
                prog['message'] = f'✅ Todos os {successful} vídeos processados! {len(failed_videos)} falharam.'
            else:
                prog['message'] = f'✅ Processamento concluído! {successful}/{len(urls)} vídeos baixados com sucesso.'
            prog['status'] = 'done'
        else:
            prog['message'] = f'✅ Todos os {successful} vídeos baixados com sucesso!'
            prog['status'] = 'done'
        
        prog['percent'] = 100

    except Exception as e:
        prog['status'] = 'error'
        prog['error'] = str(e)
    finally:
        # Limpar referências de cancelamento, mas manter a pasta
        if job_id in active_downloads:
            # Não remover a pasta - manter arquivos
            del active_downloads[job_id]
        if job_id in download_threads:
            del download_threads[job_id]


@app.route('/download-file/<file_id>')
def download_individual_file(file_id):
    """Endpoint para baixar arquivos individuais da playlist."""
    for job_id, prog in progress_store.items():
        for file_info in prog.get('completed_files', []):
            if file_info['id'] == file_id:
                filepath = Path(file_info['path'])
                if filepath.exists():
                    mime = 'audio/mpeg' if filepath.suffix == '.mp3' else 'video/mp4'
                    return send_file(
                        filepath,
                        as_attachment=True,
                        download_name=filepath.name,
                        mimetype=mime,
                    )
                else:
                    return jsonify(error='Arquivo não encontrado'), 404
    return jsonify(error='Arquivo não encontrado'), 404


@app.route('/progress/<job_id>')
def progress(job_id: str):
    def generate():
        last_completed_count = 0
        while True:
            prog = progress_store.get(job_id)
            if not prog:
                yield f"data: {json.dumps({'status':'error','error':'Job não encontrado'})}\n\n"
                break
            
            current_count = len(prog.get('completed_files', []))
            if current_count > last_completed_count:
                last_completed_count = current_count
                prog_copy = prog.copy()
                prog_copy['new_files'] = prog.get('completed_files', [])[last_completed_count - current_count:]
                yield f"data: {json.dumps(prog_copy)}\n\n"
            else:
                yield f"data: {json.dumps(prog)}\n\n"
            
            if prog['status'] in ('done', 'error', 'cancelled'):
                break
            time.sleep(0.5)
    
    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Limpeza manual de arquivos antigos (mais de 1 hora e não ativos)."""
    count = 0
    now = datetime.now()
    cutoff = now - timedelta(hours=1)
    
    # Coletar jobs ativos
    active_jobs = set(active_downloads.keys())
    
    for folder in [DOWNLOAD_DIR, CONVERTED_DIR, TEMP_DIR]:
        if folder.exists():
            for item in folder.iterdir():
                try:
                    # Verificar se é um job ativo
                    is_active = False
                    for job_id in active_jobs:
                        if job_id in str(item):
                            is_active = True
                            break
                    
                    if is_active:
                        continue
                    
                    mod_time = datetime.fromtimestamp(item.stat().st_mtime)
                    if mod_time < cutoff:
                        if item.is_file():
                            item.unlink()
                            count += 1
                        elif item.is_dir():
                            shutil.rmtree(item)
                            count += 1
                except Exception:
                    pass
    
    # Limpar jobs antigos do progress_store
    jobs_to_remove = []
    for job_id, prog in progress_store.items():
        if job_id in active_jobs:
            continue
        if 'created_at' in prog:
            created = datetime.fromisoformat(prog['created_at'])
            if created < cutoff:
                jobs_to_remove.append(job_id)
    
    for job_id in jobs_to_remove:
        if job_id in progress_store:
            del progress_store[job_id]
    
    return jsonify(success=True, message=f'{count} itens removidos, {len(jobs_to_remove)} jobs limpos')


@app.route('/analyze-playlist')
def analyze_playlist_stream():
    """SSE: transmite entradas da playlist conforme são processadas."""
    url = request.args.get('url', '').strip()
    clean_url = extract_clean_url(url) if url else ''

    def generate():
        if not clean_url:
            yield f"data: {json.dumps({'event': 'error', 'message': 'URL não fornecida'})}\n\n"
            return

        ydl_opts = {
            **_analyze_ydl_opts(),
            'extract_flat': True,
            'skip_download': True,
            'ignoreerrors': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(clean_url, download=False)

            if not info:
                yield f"data: {json.dumps({'event': 'error', 'message': 'Playlist não encontrada.'})}\n\n"
                return

            entries = [
                e for e in (info.get('entries') or [])
                if e and e.get('availability', 'public') not in ['private', 'deleted', 'unavailable']
            ][:200]

            yield f"data: {json.dumps({'event': 'header', 'title': info.get('title', 'Playlist'), 'count': len(entries), 'formats': _common_formats()})}\n\n"

            for idx, e in enumerate(entries):
                video_id = e.get('id', '')
                thumbnail = e.get('thumbnail') or (get_thumbnail_url(video_id, 'hq') if video_id else None)
                video_url = (
                    e.get('url') or e.get('webpage_url')
                    or (f"https://www.youtube.com/watch?v={video_id}" if video_id else '')
                )
                yield f"data: {json.dumps({'event': 'item', 'id': video_id, 'index': idx + 1, 'title': e.get('title', 'Sem título'), 'duration': format_duration(e.get('duration', 0)), 'thumbnail': thumbnail, 'url': video_url})}\n\n"

            yield f"data: {json.dumps({'event': 'done'})}\n\n"

        except Exception as ex:
            yield f"data: {json.dumps({'event': 'error', 'message': str(ex)})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/')
def index():
    return render_template('index.html')


def _find_free_port(start: int = 5000) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start


def _open_browser(port: int):
    """Aguarda o servidor subir e abre o browser."""
    for _ in range(40):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                webbrowser.open(f'http://127.0.0.1:{port}')
                return
        except OSError:
            time.sleep(0.25)


if __name__ == '__main__':
    cleanup_old_files(24)
    port = _find_free_port()
    threading.Thread(target=_open_browser, args=(port,), daemon=True).start()
    print(f'YTDownloader rodando em http://127.0.0.1:{port}')
    app.run(debug=False, host='127.0.0.1', port=port, threaded=True)