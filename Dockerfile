# syntax=docker/dockerfile:1
#
# uv-managed image following the current official pattern:
# https://docs.astral.sh/uv/guides/integration/docker/
#
# pyogrio wheels bundle GDAL, so no OSGeo/GDAL base image is needed.

FROM python:3.12-slim-bookworm

# Copy the uv binary from Astral's distroless image (pinned).
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

WORKDIR /app

# Copy on write instead of hardlink (the cache mount is on a different fs).
ENV UV_LINK_MODE=copy

# 1) Install *dependencies only* first for better layer caching.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# 2) Copy the project source and install the package itself.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Put the venv on PATH so the console script is directly runnable.
ENV PATH="/app/.venv/bin:$PATH"

# Data lives on a mounted volume (see README for `docker run` example).
VOLUME ["/app/data"]

ENTRYPOINT ["roadnet"]
CMD ["all"]
