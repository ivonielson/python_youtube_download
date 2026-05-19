FROM python:3.12-slim

# ffmpeg via apt (sistema — sem embutir no executável)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Porta e data dir padrão
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/data

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "warning"]
