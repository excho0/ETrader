FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libstdc++6 && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY . /app
RUN rm -rf /app/.venv /app/.pytest_cache /app/.ruff_cache /app/.mypy_cache && \
    uv sync --frozen --no-dev

EXPOSE 8040 8041

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8040"]
