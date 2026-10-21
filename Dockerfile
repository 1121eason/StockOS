FROM ghcr.io/astral-sh/uv:0.13.0 AS uv
FROM python:3.12-slim-bookworm AS runtime
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app/src
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project && rm -rf /root/.cache/uv
COPY src ./src
COPY scripts/serve_ui.py scripts/serve_product.py scripts/product_backup.py ./scripts/
COPY ui ./ui
COPY deploy/healthcheck.py ./deploy/healthcheck.py
RUN groupadd --gid 10001 stockos && useradd --uid 10001 --gid stockos --no-create-home stockos \
    && mkdir -p /state /seed && chown stockos:stockos /state
USER 10001:10001
EXPOSE 8511
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD ["python", "/app/deploy/healthcheck.py"]
CMD ["python", "scripts/serve_product.py"]
