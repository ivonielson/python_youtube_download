import threading

# Estado em memória compartilhado entre rotas e serviços.
# Será substituído por SQLite na Task #2.

progress_store: dict[str, dict] = {}
active_downloads: dict[str, dict] = {}
download_threads: dict[str, threading.Thread] = {}
