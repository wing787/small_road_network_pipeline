"""Configuration for the roadnet pipeline (pydantic-settings).

All paths and network parameters live here so the I/O layers stay declarative.
Override any field via environment variables prefixed with ``ROADNET_`` or a
``.env`` file, e.g. ``ROADNET_SLEEP_SECONDS=5``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Default mesh zips (国土数値情報 道路データ N13-2024).
#
# Distribution is per 1-次メッシュ (4-digit primary mesh) zip, each containing a
# single GeoJSON in EPSG:6668 (JGD2011, lon/lat). These three are among the
# smallest meshes nationwide (5-66 KB) so the demo stays fast and polite.
# Verified to return HTTP 200 / application/zip on 2026-07-11.
# ---------------------------------------------------------------------------
_N13_BASE = "https://nlftp.mlit.go.jp/ksj/gml/data/N13/N13-24"

DEFAULT_MESH_ZIP_URLS: list[str] = [
    f"{_N13_BASE}/N13-24_3631_GEOJSON.zip",  # ~5 KB
    f"{_N13_BASE}/N13-24_3724_GEOJSON.zip",  # ~22 KB
    f"{_N13_BASE}/N13-24_3622_GEOJSON.zip",  # ~66 KB
]


class Settings(BaseSettings):
    """Runtime settings for the pipeline."""

    model_config = SettingsConfigDict(
        env_prefix="ROADNET_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- source data ---
    mesh_zip_urls: list[str] = Field(default_factory=lambda: list(DEFAULT_MESH_ZIP_URLS))

    # --- filesystem layout ---
    data_dir: Path = Path("data")
    output_parquet_filename: str = "roads_all.parquet"
    output_fgb_filename: str = "roads_all.fgb"

    # --- network politeness ---
    sleep_seconds: float = 2.0
    timeout_seconds: float = 60.0
    user_agent: str = (
        "small-road-network-pipeline/0.1 "
        "(portfolio learning project; +https://nlftp.mlit.go.jp)"
    )

    @property
    def raw_dir(self) -> Path:
        """Downloaded mesh zips."""
        return self.data_dir / "raw"

    @property
    def parts_dir(self) -> Path:
        """Per-mesh GeoParquet parts."""
        return self.data_dir / "parts"

    @property
    def output_dir(self) -> Path:
        """Final merged outputs (GeoParquet + FlatGeobuf) live here."""
        return self.data_dir / "output"

    @property
    def output_parquet_path(self) -> Path:
        return self.output_dir / self.output_parquet_filename

    @property
    def output_fgb_path(self) -> Path:
        return self.output_dir / self.output_fgb_filename

    def ensure_dirs(self) -> None:
        """Create the data directories if missing (idempotent)."""
        for d in (self.raw_dir, self.parts_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Build a Settings instance (reads env / .env)."""
    return Settings()
