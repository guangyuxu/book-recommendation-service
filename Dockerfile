# FastAPI BFF image, built with uv. (The agent uses langchain/langgraph-api as its base; this
# service is a plain ASGI app, so it uses a slim Python base + uv and runs uvicorn.)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv from the official distroless image (pinned by digest-free tag; Dependabot bumps it).
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

WORKDIR /app

# 1) Install dependencies first (cached layer) from the lockfile, without the project itself.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 2) Copy the source and install the project.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

EXPOSE 8000

# Run the API. --host 0.0.0.0 so it is reachable from outside the container.
CMD ["uv", "run", "--no-dev", "uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
