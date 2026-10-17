# The nightly compactor job (deploy/compactor/README.md). Build from the repository root:
#   docker build -f deploy/compactor/Dockerfile -t flightdeck-compactor .
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --extra gcs --no-editable && rm -rf /root/.cache
COPY deploy/compactor/nightly.sh /app/nightly.sh
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER 65532
ENTRYPOINT ["/bin/sh", "/app/nightly.sh"]
