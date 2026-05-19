"""Lógica de download via yt_dlp — roda em threads separadas."""

import threading
from datetime import datetime
from pathlib import Path

import yt_dlp

from api.database import save_job
from api.state import active_downloads, download_threads, progress_store
from api.utils.anti_detect import base_ydl_opts, playlist_delay
from api.utils.paths import DOWNLOAD_DIR


def _make_progress_hook(job_id: str, total: int, prog: dict):
    def _hook(d):
        if d['status'] != 'downloading':
            return
        if active_downloads.get(job_id, {}).get('cancel', False):
            raise Exception("Download cancelado pelo usuário")
        try:
            pct_raw = d.get('_percent_str', '0%').strip().replace('%', '')
            pct = float(pct_raw) if pct_raw else 0.0
            completed = len(prog.get('completed_files', []))
            overall = ((completed + pct / 100) / total) * 100 if total else 0
            prog['percent'] = min(overall, 100)
        except ValueError:
            pass
        completed = len(prog.get('completed_files', []))
        prog['message'] = (
            f"Baixando: {prog.get('current_video', '...')} "
            f"({completed + 1}/{total})"
        )
    return _hook


def _build_ydl_opts(job_id: str, total: int, prog: dict, out_dir: Path,
                    format_id: str, is_mp3: bool) -> dict:
    hook = _make_progress_hook(job_id, total, prog)
    opts = {
        **base_ydl_opts(),
        'outtmpl': str(out_dir / '%(title)s.%(ext)s'),
        'noplaylist': True,
        'ignoreerrors': True,
        'progress_hooks': [hook],
    }
    if is_mp3:
        opts['format'] = 'bestaudio/worstaudio/worst'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        opts['postprocessor_args'] = ['-ar', '44100']
        opts['keepvideo'] = False
    else:
        opts['format'] = format_id
        opts['merge_output_format'] = 'mp4'
        opts['postprocessors'] = [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }]
    return opts


def do_individual_download(
    job_id: str,
    urls: list[str],
    metadata_list: list[dict],
    format_id: str,
    is_mp3: bool,
):
    """Processa cada vídeo individualmente com suporte a cancelamento."""
    prog = progress_store[job_id]
    out_dir = DOWNLOAD_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    completed_paths: list[str] = []
    failed_videos: list[dict] = []
    successful = 0
    ext = '.mp3' if is_mp3 else '.mp4'

    try:
        prog['status'] = 'running'
        prog['message'] = f'Preparando download de {len(urls)} vídeo(s)...'

        for idx, video_url in enumerate(urls):
            # Verificar cancelamento antes de cada vídeo
            if active_downloads.get(job_id, {}).get('cancel', False):
                prog['status'] = 'cancelled'
                prog['message'] = (
                    f'⚠️ Cancelado após {successful} vídeo(s) baixado(s). '
                    'Os arquivos já concluídos estão disponíveis.'
                )
                break

            metadata = metadata_list[idx] if idx < len(metadata_list) else {}
            video_title = metadata.get('title', f'Vídeo {idx + 1}')
            prog['current_video'] = video_title
            prog['current_index'] = idx + 1
            prog['message'] = f'Processando {idx + 1}/{len(urls)}: {video_title[:50]}...'

            # Pular se o arquivo já existe
            existing = next(
                (f for f in out_dir.iterdir()
                 if f.suffix.lower() == ext and video_title[:50] in f.stem),
                None
            )
            if existing:
                file_id = f"{job_id}_{idx}"
                prog['completed_files'].append({
                    'id': file_id,
                    'name': existing.name,
                    'path': str(existing),
                    'url': f"/api/file/{file_id}",
                    'stream_url': f"/api/stream/{file_id}",
                    'title': video_title,
                    'thumbnail': metadata.get('thumbnail', ''),
                    'index': idx + 1,
                })
                completed_paths.append(str(existing))
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

            ydl_opts = _build_ydl_opts(job_id, len(urls), prog, out_dir, format_id, is_mp3)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])

                downloaded = next(
                    (f for f in out_dir.iterdir()
                     if f.suffix.lower() == ext
                     and f.stem not in [Path(p).stem for p in completed_paths]),
                    None
                )
                if not downloaded:
                    raise Exception("Arquivo não encontrado após download")

                file_id = f"{job_id}_{idx}"
                prog['completed_files'].append({
                    'id': file_id,
                    'name': downloaded.name,
                    'path': str(downloaded),
                    'url': f"/api/file/{file_id}",
                    'stream_url': f"/api/stream/{file_id}",
                    'title': video_title,
                    'thumbnail': metadata.get('thumbnail', ''),
                    'index': idx + 1,
                })
                completed_paths.append(str(downloaded))
                successful += 1
                prog['downloaded'] = successful
                prog['percent'] = (successful / len(urls)) * 100
                prog['message'] = f'✅ {video_title[:40]} concluído! ({successful}/{len(urls)})'

                playlist_delay(
                    lambda msg: prog.update({'message': msg}),
                    idx,
                    len(urls),
                )

            except Exception as e:
                msg = str(e)
                if 'cancelado' in msg.lower() or 'cancelled' in msg.lower():
                    prog['status'] = 'cancelled'
                    prog['message'] = f'⚠️ Cancelado após {successful} vídeos baixados.'
                    break
                failed_videos.append({'url': video_url, 'title': video_title, 'error': msg})
                prog['failed'] = failed_videos
                successful += 1
                prog['downloaded'] = successful
                prog['percent'] = (successful / len(urls)) * 100
                prog['message'] = f'⚠️ Falha em "{video_title[:40]}": {msg[:60]}'

        if prog['status'] not in ('cancelled',):
            if failed_videos:
                prog['message'] = (
                    f'✅ Processamento concluído! {successful}/{len(urls)} '
                    f'vídeos baixados. {len(failed_videos)} falharam.'
                )
            else:
                prog['message'] = f'✅ Todos os {successful} vídeos baixados com sucesso!'
            prog['status'] = 'done'

        prog['percent'] = 100

    except Exception as e:
        prog['status'] = 'error'
        prog['error'] = str(e)
    finally:
        # Persistir no SQLite independente do resultado
        try:
            save_job(job_id, prog)
        except Exception as db_err:
            print(f'[DB] Erro ao salvar job {job_id}: {db_err}')
        active_downloads.pop(job_id, None)
        download_threads.pop(job_id, None)


def start_download_thread(
    job_id: str,
    urls: list[str],
    metadata_list: list[dict],
    format_id: str,
    is_mp3: bool,
):
    t = threading.Thread(
        target=do_individual_download,
        args=(job_id, urls, metadata_list, format_id, is_mp3),
        daemon=True,
    )
    download_threads[job_id] = t
    t.start()
