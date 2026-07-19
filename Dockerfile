# syntax=docker/dockerfile:1
#
# uv 管理のマルチステージイメージ。現行の公式パターンに従う:
# https://docs.astral.sh/uv/guides/integration/docker/
#
# ステージ構成:
#   base    - python + uv、実行時依存のみ（プロジェクトコードなし）
#   test    - 開発依存 + ソース + テスト。CMD で pytest を実行
#   runtime - 最終イメージ（デフォルトのビルドターゲット）、開発依存なし
#
# `docker build .` は `runtime`（最後のステージ）を生成するため、既存の
# ビルドコマンドはそのまま動く。テストイメージは `--target test` でビルド。
#
# pyogrio の wheel は GDAL を同梱しているため、OSGeo/GDAL ベースイメージは不要。

# --------------------------------------------------------------------------- #
FROM python:3.12-slim-bookworm AS base

# Astral の distroless イメージから uv バイナリをコピー（バージョン固定）。
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

WORKDIR /app

# ハードリンクではなくコピーで書き込む（キャッシュマウントが別ファイル
# システム上にあるため）。
ENV UV_LINK_MODE=copy

# 層キャッシュを効かせるため、まず「実行時依存のみ」をインストールする。
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# --------------------------------------------------------------------------- #
FROM base AS test

# 実行時依存の上に dev グループ（pytest, ruff, mypy）を追加する。
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

ENV PATH="/app/.venv/bin:$PATH"

CMD ["pytest", "-v"]

# --------------------------------------------------------------------------- #
# 最終ステージ: デフォルトのビルドターゲット（--target なしでは最後のステージが選ばれる）。
FROM base AS runtime

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# venv を PATH に載せ、コンソールスクリプトを直接実行可能にする。
ENV PATH="/app/.venv/bin:$PATH"

# データはマウントされたボリュームに置く（`docker run` の例は README 参照）。
VOLUME ["/app/data"]

ENTRYPOINT ["roadnet"]
CMD ["all"]
