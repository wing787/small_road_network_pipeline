"""roadnet パイプラインの設定（pydantic-settings）。

パスやネットワーク関連のパラメータをここに集約し、I/O 層を宣言的に保つ。
各フィールドは ``ROADNET_`` プレフィックス付きの環境変数、または ``.env``
ファイルで上書きできる（例: ``ROADNET_SLEEP_SECONDS=5``）。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# デフォルトのメッシュ zip（国土数値情報 道路データ N13-2024）。
#
# 配布は1次メッシュ（4桁）単位の zip で、それぞれ EPSG:6668（JGD2011 経緯度）の
# GeoJSON を1つ含む。以下の3つは全国でも最小クラスのメッシュ（5〜66 KB）で、
# デモを高速かつ配布元に負荷をかけない範囲に保つための選定。
# 2026-07-11 に HTTP 200 / application/zip が返ることを確認済み。
# ---------------------------------------------------------------------------
_N13_BASE = "https://nlftp.mlit.go.jp/ksj/gml/data/N13/N13-24"

DEFAULT_MESH_ZIP_URLS: list[str] = [
    f"{_N13_BASE}/N13-24_3631_GEOJSON.zip",  # 約5 KB
    f"{_N13_BASE}/N13-24_3724_GEOJSON.zip",  # 約22 KB
    f"{_N13_BASE}/N13-24_3622_GEOJSON.zip",  # 約66 KB
]


class Settings(BaseSettings):
    """パイプラインの実行時設定。"""

    model_config = SettingsConfigDict(
        env_prefix="ROADNET_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 取得元データ ---
    mesh_zip_urls: list[str] = Field(default_factory=lambda: list(DEFAULT_MESH_ZIP_URLS))

    # --- ファイルシステム配置 ---
    data_dir: Path = Path("data")
    output_parquet_filename: str = "roads_all.parquet"
    output_fgb_filename: str = "roads_all.fgb"

    # --- PostGIS（開発専用の認証情報。compose.yaml / README 参照） ---
    # デフォルトの DSN は compose のサービス名 `postgis` を指す。ホストからは:
    # ROADNET_DATABASE_URL=postgresql+psycopg://roadnet:roadnet@localhost:5432/roadnet
    sleep_seconds: float = 2.0
    timeout_seconds: float = 60.0
    user_agent: str = (
        "small-road-network-pipeline/0.1 "
        "(portfolio learning project; +https://nlftp.mlit.go.jp)"
    )

    @property
    def raw_dir(self) -> Path:
        """ダウンロードしたメッシュ zip の置き場。"""
        return self.data_dir / "raw"

    @property
    def parts_dir(self) -> Path:
        """メッシュ単位の GeoParquet パートの置き場。"""
        return self.data_dir / "parts"

    @property
    def output_dir(self) -> Path:
        """結合済みの最終出力（GeoParquet + FlatGeobuf）の置き場。"""
        return self.data_dir / "output"

    @property
    def output_parquet_path(self) -> Path:
        return self.output_dir / self.output_parquet_filename

    @property
    def output_fgb_path(self) -> Path:
        return self.output_dir / self.output_fgb_filename

    def ensure_dirs(self) -> None:
        """データディレクトリがなければ作成する（冪等）。"""
        for d in (self.raw_dir, self.parts_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Settings インスタンスを生成する（環境変数 / .env を読む）。"""
    return Settings()
