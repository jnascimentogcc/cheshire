FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev

FROM python:3.12-slim
RUN useradd --system --uid 10001 --create-home cheshire
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
COPY catalog ./catalog
COPY scenarios ./scenarios
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER cheshire
EXPOSE 8000
CMD ["cheshire", "serve", "--host", "0.0.0.0", "--port", "8000"]
