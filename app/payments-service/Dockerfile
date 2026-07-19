# Build context is app/ (one level up) so we can COPY the shared common/ package.
# Slim runtime image. Deps installed with uv into /app/.venv; no uv at runtime.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv

WORKDIR /app

# Dependency layer — cached until this service's pyproject.toml / uv.lock change.
COPY payments-service/pyproject.toml payments-service/uv.lock ./
RUN uv sync --frozen --no-dev

# Shared instrumentation module, then the service entrypoint.
COPY common/ ./common/
COPY payments-service/main.py ./

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Normal build bakes a value so the service boots. The fault-F3 `-bad` image is
# built with `--build-arg REQUIRED_SETTING=` (empty), so it exits 1 on boot.
ARG REQUIRED_SETTING=ok
ENV REQUIRED_SETTING=${REQUIRED_SETTING}

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
