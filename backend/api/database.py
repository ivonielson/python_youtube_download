"""Persistência SQLite para jobs e arquivos processados.

Estratégia: progress_store permanece em memória (acesso rápido durante download),
SQLite é escrito ao final de cada job e carregado no startup para restaurar
os links de arquivos já baixados após reinício do servidor.
"""

import sqlite3
from pathlib import Path

from api.utils.paths import DB_PATH

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    status     TEXT NOT NULL,
    percent    REAL DEFAULT 0,
    message    TEXT,
    total      INTEGER DEFAULT 0,
    downloaded INTEGER DEFAULT 0,
    error      TEXT,
    is_playlist INTEGER DEFAULT 0,
    created_at TEXT,
    session_id TEXT,
    cancelled  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    id         TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL,
    name       TEXT,
    path       TEXT,
    url        TEXT,
    stream_url TEXT,
    title      TEXT,
    thumbnail  TEXT,
    index_num  INTEGER,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_files_job ON files(job_id);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def init_db():
    with _conn() as c:
        c.executescript(_DDL)


def save_job(job_id: str, prog: dict):
    """Persiste o job e seus arquivos concluídos. Chamado ao terminar cada job."""
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO jobs
               (id, status, percent, message, total, downloaded,
                error, is_playlist, created_at, session_id, cancelled)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                prog.get('status'),
                prog.get('percent', 0),
                prog.get('message'),
                prog.get('total', 0),
                prog.get('downloaded', 0),
                prog.get('error'),
                1 if prog.get('is_playlist') else 0,
                prog.get('created_at'),
                prog.get('session_id'),
                1 if prog.get('cancelled') else 0,
            ),
        )
        for f in prog.get('completed_files', []):
            c.execute(
                """INSERT OR IGNORE INTO files
                   (id, job_id, name, path, url, stream_url, title, thumbnail, index_num)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    f['id'], job_id, f.get('name'), f.get('path'),
                    f.get('url'), f.get('stream_url'), f.get('title'),
                    f.get('thumbnail'), f.get('index'),
                ),
            )


def load_completed_jobs() -> dict[str, dict]:
    """Restaura jobs finalizados do SQLite para o progress_store em memória.
    Apenas restaura arquivos cujo arquivo físico ainda existe no disco.
    """
    result: dict[str, dict] = {}
    with _conn() as c:
        jobs = c.execute(
            "SELECT * FROM jobs WHERE status IN ('done','cancelled','error')"
        ).fetchall()
        for job in jobs:
            jid = job['id']
            rows = c.execute(
                'SELECT * FROM files WHERE job_id=? ORDER BY index_num', (jid,)
            ).fetchall()
            files = [
                {
                    'id': r['id'], 'name': r['name'], 'path': r['path'],
                    'url': r['url'], 'stream_url': r['stream_url'],
                    'title': r['title'], 'thumbnail': r['thumbnail'],
                    'index': r['index_num'],
                }
                for r in rows
                if r['path'] and Path(r['path']).exists()
            ]
            result[jid] = {
                'status':          job['status'],
                'percent':         job['percent'],
                'message':         job['message'],
                'total':           job['total'],
                'downloaded':      job['downloaded'],
                'error':           job['error'],
                'is_playlist':     bool(job['is_playlist']),
                'created_at':      job['created_at'],
                'session_id':      job['session_id'],
                'cancelled':       bool(job['cancelled']),
                'completed_files': files,
                'failed':          [],
                'current_video':   None,
                'current_index':   0,
            }
    return result
