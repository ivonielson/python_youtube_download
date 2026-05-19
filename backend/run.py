"""Ponto de entrada do servidor FastTube.

Uso:
    python run.py                  # servidor local, abre browser
    HOST=0.0.0.0 python run.py    # servidor externo, sem browser
"""

import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from api.config import settings


def _find_free_port(start: int = 8000) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    return start


def _open_browser(host: str, port: int):
    url = f'http://127.0.0.1:{port}'
    for _ in range(40):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.25)


if __name__ == '__main__':
    port = _find_free_port(settings.PORT)

    if settings.HOST == '127.0.0.1':
        threading.Thread(target=_open_browser, args=(settings.HOST, port), daemon=True).start()

    print(f'[FastTube] Iniciando em http://{settings.HOST}:{port}')
    print(f'[FastTube] Documentação da API: http://{settings.HOST}:{port}/docs')

    uvicorn.run(
        'api.main:app',
        host=settings.HOST,
        port=port,
        reload=True,
        log_level='warning',
    )
