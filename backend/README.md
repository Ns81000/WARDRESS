# Wardress backend

FastAPI application (`app/`), Celery worker with the nine detection layers
(`worker/`), Alembic migrations (`alembic/`), and tests (`tests/`).

Managed exclusively with [uv](https://docs.astral.sh/uv/):

```
uv sync --frozen        # install exactly what uv.lock specifies
uv run uvicorn app.main:app --reload
uv run pytest
```
