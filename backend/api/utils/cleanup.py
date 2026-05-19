import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


def cleanup_old_files(
    dirs: list[Path],
    progress_store: dict,
    active_downloads: dict,
    max_age_days: int = 30,
):
    try:
        cutoff = datetime.now() - timedelta(days=max_age_days)
        active_jobs = set(active_downloads.keys())
        deleted = 0

        for folder in dirs:
            if not folder.exists():
                continue
            for item in folder.iterdir():
                try:
                    if any(jid in str(item) for jid in active_jobs):
                        continue
                    if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                        deleted += 1
                except Exception as e:
                    print(f"[Cleanup] Erro em {item}: {e}")

        stale = [
            jid for jid, p in progress_store.items()
            if jid not in active_jobs
            and 'created_at' in p
            and datetime.fromisoformat(p['created_at']) < cutoff
        ]
        for jid in stale:
            progress_store.pop(jid, None)

        if deleted:
            print(f"[Cleanup] Removidos {deleted} itens com mais de {max_age_days} dias")
    except Exception as e:
        print(f"[Cleanup] Erro geral: {e}")


def start_cleanup_scheduler(dirs: list[Path], progress_store: dict, active_downloads: dict):
    def _loop():
        while True:
            time.sleep(24 * 3600)
            cleanup_old_files(dirs, progress_store, active_downloads)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("[Scheduler] Limpeza automática agendada (cada 24h, mantém 30 dias)")
