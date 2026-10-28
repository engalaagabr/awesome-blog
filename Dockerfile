FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN --mount=type=cache,id=awesome-blog-pip,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin blog \
    && mkdir -p /data /app/app/media/profile_pics \
    && chown -R blog:blog /data /app/app/media

USER blog

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/posts/?per_page=1', timeout=3).close()"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
