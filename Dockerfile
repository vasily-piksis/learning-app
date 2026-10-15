FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
COPY backend/app/word-count-profile.json /backend/app/word-count-profile.json
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data FRONTEND_DIR=/app/static
WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.lock \
    && groupadd --gid 10001 study \
    && useradd --uid 10001 --gid study --no-create-home study \
    && mkdir /data && chown study:study /data
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY --from=frontend /build/dist ./static
RUN chmod -R a+rX /app/app /app/alembic /app/static && chmod a+r /app/alembic.ini
USER study
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"
CMD ["uvicorn", "app.main:production_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
