FROM python:3.12-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev
ENV EVIDENCE_GATEWAY=fixture
EXPOSE 8000
CMD ["uv", "run", "python", "-m", "evidence_api"]
