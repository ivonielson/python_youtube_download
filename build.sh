#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "==> Ativando venv..."
source venv/bin/activate

echo "==> Instalando PyInstaller..."
pip install pyinstaller --quiet

echo "==> Gerando executável..."
pyinstaller \
    --name "YTDownloader" \
    --onedir \
    --add-data "templates:templates" \
    --collect-all yt_dlp \
    --hidden-import flask \
    --hidden-import werkzeug \
    --hidden-import jinja2 \
    --hidden-import click \
    --hidden-import flask_cors \
    --noconfirm \
    --clean \
    app.py

echo ""
echo "✅ Pronto! Executável gerado em:"
echo "   $(pwd)/dist/YTDownloader/YTDownloader"
echo ""
echo "Para rodar: ./dist/YTDownloader/YTDownloader"
