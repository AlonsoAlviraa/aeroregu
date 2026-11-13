FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVIDENCE_HOME=/app/data \
    EVIDENCE_GATEWAY=auto

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
CMD ["uv", "run", "--no-dev", "python", "-m", "evidence_api"]
