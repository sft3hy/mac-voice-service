FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    MODEL_DIR=/models/Kokoro-82M

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      espeak-ng ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY gateway/requirements.txt ./gateway/requirements.txt
# torch CPU only: the container has no Metal access, and this keeps the image small.
RUN pip install -r gateway/requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

COPY gateway/ ./gateway/
RUN useradd -m -u 1000 app && chown -R app:app /app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=70s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
