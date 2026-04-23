@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title YTDownloader - Build

echo.
echo ============================================
echo   YTDownloader - Gerando executavel Windows
echo ============================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale em https://python.org
    pause & exit /b 1
)

:: Criar/ativar venv
if not exist "venv" (
    echo =^> Criando ambiente virtual...
    python -m venv venv
)
echo =^> Ativando ambiente virtual...
call venv\Scripts\activate.bat

:: Instalar dependencias
echo =^> Instalando dependencias...
pip install -r requeriments.txt --quiet
pip install pyinstaller --quiet

:: Baixar FFmpeg para Windows
echo =^> Baixando FFmpeg para Windows...
if not exist "ffmpeg" mkdir ffmpeg

if exist "ffmpeg\ffmpeg.exe" (
    echo    FFmpeg ja existe, pulando download.
) else (
    set FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip
    echo    Baixando de !FFMPEG_URL!
    powershell -Command "Invoke-WebRequest -Uri '!FFMPEG_URL!' -OutFile 'ffmpeg_temp.zip' -UseBasicParsing"
    if errorlevel 1 (
        echo [ERRO] Falha ao baixar FFmpeg. Verifique a conexao com a internet.
        pause & exit /b 1
    )

    echo    Extraindo...
    powershell -Command "Expand-Archive -Path 'ffmpeg_temp.zip' -DestinationPath 'ffmpeg_extract' -Force"

    :: Copiar somente os executaveis necessarios
    for /d %%D in (ffmpeg_extract\ffmpeg-*) do (
        copy "%%D\bin\ffmpeg.exe"  "ffmpeg\ffmpeg.exe"  >nul
        copy "%%D\bin\ffprobe.exe" "ffmpeg\ffprobe.exe" >nul
    )

    del ffmpeg_temp.zip >nul 2>&1
    rmdir /s /q ffmpeg_extract >nul 2>&1
    echo    FFmpeg pronto.
)

:: Gerar executavel com PyInstaller
echo =^> Gerando executavel...
pyinstaller ^
    --name "YTDownloader" ^
    --onedir ^
    --add-data "templates;templates" ^
    --add-binary "ffmpeg\ffmpeg.exe;ffmpeg" ^
    --add-binary "ffmpeg\ffprobe.exe;ffmpeg" ^
    --collect-all yt_dlp ^
    --hidden-import flask ^
    --hidden-import werkzeug ^
    --hidden-import jinja2 ^
    --hidden-import click ^
    --hidden-import flask_cors ^
    --noconfirm ^
    --clean ^
    app.py

if errorlevel 1 (
    echo [ERRO] Falha ao gerar executavel.
    pause & exit /b 1
)

echo.
echo ============================================
echo   Concluido com sucesso!
echo   Executavel: dist\YTDownloader\YTDownloader.exe
echo ============================================
echo.
pause
