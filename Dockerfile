FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# gosu lets the entrypoint fix volume ownership as root, then drop privileges.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependencies first, in their own layer: source changes shouldn't reinstall
# the whole environment on every deploy.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY mtb_analyzer/ ./mtb_analyzer/
COPY scripts/ ./scripts/
COPY races.yml ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home --uid 10001 velo \
 && chown -R velo:velo /app \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "mtb_analyzer.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
