# syntax=docker/dockerfile:1

# --- web interface -------------------------------------------------------------------------
FROM node:24-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- application ---------------------------------------------------------------------------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DESKSIDE_CONFIG=/config/config.yaml DESKSIDE_PORT=8080
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/deskside ./deskside
COPY --from=frontend /src/backend/deskside/static ./deskside/static
RUN pip install --no-cache-dir . \
 && useradd --system --uid 10001 --home /data deskside \
 && mkdir -p /data /config && chown deskside /data
USER deskside
WORKDIR /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"DESKSIDE_PORT\"]}/api/health',timeout=4)"
CMD ["deskside"]
