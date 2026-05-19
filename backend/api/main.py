from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.config import settings
from api.database import init_db, load_completed_jobs
from api.routes.analyze import router as analyze_router
from api.routes.download import router as download_router
from api.routes.files import router as files_router
from api.routes.health import router as health_router
from api.routes.search import router as search_router
from api.state import active_downloads, progress_store
from api.utils.cleanup import cleanup_old_files, start_cleanup_scheduler
from api.utils.paths import BASE_DIR, CONVERTED_DIR, DOWNLOAD_DIR, TEMP_DIR, ffmpeg_ok, resource_path

# ── Startup / Shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recovered = load_completed_jobs()
    progress_store.update(recovered)
    if recovered:
        print(f'[DB] {len(recovered)} job(s) restaurados do SQLite')

    dirs = [DOWNLOAD_DIR, CONVERTED_DIR, TEMP_DIR]
    cleanup_old_files(dirs, progress_store, active_downloads)
    start_cleanup_scheduler(dirs, progress_store, active_downloads)

    print('[OK] FFmpeg detectado' if ffmpeg_ok() else '[AVISO] FFmpeg não encontrado')
    print(f'[OK] FastTube API — docs em http://{settings.HOST}:{settings.PORT}/docs')
    yield

# ── Aplicação ─────────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title='FastTube API',
    version='2.0.0',
    description='API REST para download de vídeos do YouTube',
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────

origins = settings.CORS_ORIGINS
if origins == ['*']:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

# ── Autenticação por API Key (opcional) ───────────────────────────────────────

@app.middleware('http')
async def api_key_middleware(request: Request, call_next):
    path = request.url.path
    if settings.API_KEY and path.startswith('/api/') and path != '/api/health':
        key = request.headers.get('X-API-Key', '')
        if key != settings.API_KEY:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'API key inválida'}, status_code=403)
    return await call_next(request)

# ── Rotas da API ──────────────────────────────────────────────────────────────

app.include_router(analyze_router,  prefix='/api', tags=['Análise'])
app.include_router(download_router, prefix='/api', tags=['Download'])
app.include_router(files_router,    prefix='/api', tags=['Arquivos'])
app.include_router(health_router,   prefix='/api', tags=['Sistema'])
app.include_router(search_router,   prefix='/api', tags=['Busca'])

# ── Web UI (dev: serve frontend/; prod: nginx serve static) ──────────────────

_frontend_dir = BASE_DIR.parent / 'frontend'
_frontend_index = _frontend_dir / 'index.html'
_legacy_index = resource_path('templates') / 'index.html'

if (_frontend_dir / 'assets').exists():
    app.mount('/assets', StaticFiles(directory=str(_frontend_dir / 'assets')), name='assets')


@app.get('/', response_class=HTMLResponse)
async def index():
    html = _frontend_index if _frontend_index.exists() else _legacy_index
    return HTMLResponse(html.read_text(encoding='utf-8'))

