import os
import subprocess
import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent.parent.parent))
    return base / relative


def ffmpeg_location() -> str | None:
    if not getattr(sys, 'frozen', False):
        return None
    exe_name = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    ffmpeg_dir = resource_path('ffmpeg')
    if (ffmpeg_dir / exe_name).exists():
        return str(ffmpeg_dir)
    return None


def ffmpeg_ok() -> bool:
    loc = ffmpeg_location()
    exe_name = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    exe = str(Path(loc) / exe_name) if loc else 'ffmpeg'
    try:
        r = subprocess.run([exe, '-version'], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent.parent

# DATA_DIR permite separar dados (volumes Docker) do código da aplicação
_data_env = os.getenv('DATA_DIR', '')
DATA_DIR = Path(_data_env) if _data_env else BASE_DIR

DOWNLOAD_DIR  = DATA_DIR / 'downloads'
CONVERTED_DIR = DATA_DIR / 'converted'
TEMP_DIR      = DATA_DIR / 'temp'
DB_PATH       = DATA_DIR / 'fasttube.db'

for _d in [DOWNLOAD_DIR, CONVERTED_DIR, TEMP_DIR]:
    _d.mkdir(parents=True, exist_ok=True)
