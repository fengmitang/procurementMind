FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 procurement \
    && useradd --uid 10001 --gid procurement --create-home --shell /usr/sbin/nologin procurement

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY agent_app ./agent_app
COPY migrations ./migrations
COPY frontend ./frontend

RUN python -m pip install . \
    && mkdir -p /app/.data/chroma \
    && chown -R procurement:procurement /app/.data

USER procurement

EXPOSE 8000 8100

CMD ["python", "-m", "uvicorn", "agent_app.main:app", "--host", "0.0.0.0", "--port", "8100"]
