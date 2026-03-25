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

COPY apps/ib-bridge/pyproject.toml apps/ib-bridge/uv.lock ./
RUN uv sync --frozen --no-dev

COPY apps/ib-bridge /app

EXPOSE 8040 8041

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8040"]
