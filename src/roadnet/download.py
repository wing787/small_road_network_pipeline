"""I/O 層: メッシュ zip のダウンロード。

ネットワークとファイルシステムの副作用はこのモジュールに閉じ込め、変換層を
ユニットテスト可能に保つ。ダウンロードは冪等: 既存の空でないファイルは
再取得せずそのまま使う。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def filename_from_url(url: str) -> str:
    """URL の末尾のファイル名部分を返す（例: ``N13-24_3622_GEOJSON.zip``）。"""
    name = Path(urlparse(url).path).name
    if not name:
        raise ValueError(f"Cannot derive a filename from URL: {url!r}")
    return name


def download_one(
    url: str,
    dest_dir: Path,
    *,
    user_agent: str,
    timeout_seconds: float,
    client: httpx.Client | None = None,
) -> tuple[Path, bool]:
    """``url`` を ``dest_dir`` にダウンロードする（既存ならスキップ）。

    ``(path, downloaded)`` を返す。既存の空でないファイルを再利用した場合
    （冪等スキップ）、``downloaded`` は ``False``。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename_from_url(url)

    if dest.exists() and dest.stat().st_size > 0:
        logger.info("skip (exists): %s", dest.name)
        return dest, False

    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": user_agent},
        timeout=timeout_seconds,
        follow_redirects=True,
    )
    try:
        logger.info("GET %s", url)
        resp = client.get(url)
        resp.raise_for_status()
        # 一時ファイル経由でアトミックに書き込む。途中でクラッシュしても
        # 書きかけのファイルが残らず、冪等スキップが誤って「完了」と
        # 判定することがない。
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(resp.content)
        tmp.replace(dest)
        logger.info("saved %s (%d bytes)", dest.name, dest.stat().st_size)
        return dest, True
    finally:
        if owns_client:
            client.close()


def download_all(
    urls: list[str],
    dest_dir: Path,
    *,
    user_agent: str,
    timeout_seconds: float,
    sleep_seconds: float,
) -> list[Path]:
    """全 URL をダウンロードする。*実際に* 通信したときだけ間に sleep を挟む。

    スキップ（取得済み）のファイルでは sleep しない。
    """
    paths: list[Path] = []
    with httpx.Client(
        headers={"User-Agent": user_agent},
        timeout=timeout_seconds,
        follow_redirects=True,
    ) as client:
        for i, url in enumerate(urls):
            path, downloaded = download_one(
                url,
                dest_dir,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                client=client,
            )
            paths.append(path)
            # 配布元サーバーへの配慮: 実際に取得した直後、かつ後続の URL が
            # 残っている場合のみ待つ。
            if downloaded and sleep_seconds > 0 and i < len(urls) - 1:
                time.sleep(sleep_seconds)
    return paths
