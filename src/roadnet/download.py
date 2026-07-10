"""I/O layer: download mesh zips.

Pure network + filesystem side effects live here, kept out of the transform
layers so those stay unit-testable. Downloads are idempotent: an existing,
non-empty file is left untouched.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def filename_from_url(url: str) -> str:
    """Return the trailing filename component of a URL (e.g. ``N13-24_3622_GEOJSON.zip``)."""
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
    """Download ``url`` into ``dest_dir`` if not already present.

    Returns ``(path, downloaded)`` where ``downloaded`` is ``False`` when an
    existing non-empty file was reused (idempotent skip).
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
        # Write atomically via a temp sibling so a crash never leaves a
        # half-written file that the idempotency check would wrongly "skip".
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
    """Download every URL, sleeping between *actual* network requests.

    Skipped (already-present) files do not incur a sleep.
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
            # Be polite to the source server: pause only after a real fetch and
            # only if more URLs remain.
            if downloaded and sleep_seconds > 0 and i < len(urls) - 1:
                time.sleep(sleep_seconds)
    return paths
