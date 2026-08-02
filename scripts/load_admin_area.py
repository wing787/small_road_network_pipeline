"""N03-2026 行政区域データを PostGIS の ``admin_area`` テーブルへ投入する補助スクリプト。

用途: パーティショニング検証（M2）で、道路（roads）に「都道府県」を付与するための
参照ポリゴンを用意する。N13 には都道府県属性が無いため、N03 の県ポリゴンと空間結合して
導出する。その結合の「材料」を作るのがこのスクリプトの役割。

前提: 対象4県の N03 zip が ``data/n03/`` にあること（無ければ下記でダウンロード）:

    for p in 11 12 13 14; do
      curl -sL -A "small-road-network-pipeline/0.1" \
        -o "data/n03/N03-20260101_${p}_GML.zip" \
        "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_${p}_GML.zip"
    done

実行（ホストから。DB はホスト公開ポート経由なので localhost に上書き）:

    ROADNET_DATABASE_URL="postgresql+psycopg://roadnet:roadnet@localhost:5432/roadnet" \
        uv run python scripts/load_admin_area.py

設計メモ:
- N03 は EPSG:6668（JGD2011 経緯度）。roads と空間結合するため 4326 に変換して揃える
  （6668↔4326 は座標的には null transform だが、SRID を合わせないと結合演算が成立しない）。
- 元ジオメトリは Polygon。飛び地を持つ市区町村は複数行になるが、点 in ポリゴンの結合には
  支障ない。列型は MULTIPOLYGON に統一しておく（単ポリゴンは1要素の多ポリゴンに昇格）。
- 属性は最小限に絞る: N03_007=全国地方公共団体コード(5桁), N03_001=都道府県名,
  N03_004=市区町村名。冪等性は TRUNCATE + append。
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon
from shapely.geometry.base import BaseGeometry
from sqlalchemy import create_engine, text

from roadnet.config import get_settings

logger = logging.getLogger(__name__)

PREF_CODES = ("11", "12", "13", "14")  # 埼玉・千葉・東京・神奈川（1次メッシュ 5339 がまたぐ4県）
N03_DIR = Path("data/n03")
ADMIN_TABLE = "admin_area"

# N03 属性 → admin_area 列 のマッピング（最小限）
_FIELD_MAP = {
    "N03_007": "admin_code",  # 全国地方公共団体コード(5桁, 先頭2桁=県コード)
    "N03_001": "pref_name",   # 都道府県名
    "N03_004": "city_name",   # 市区町村名（政令市は区が N03_005 側。ここは市名）
}

_DDL = f"""
CREATE TABLE IF NOT EXISTS {ADMIN_TABLE} (
    gid        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    admin_code TEXT NOT NULL,
    pref_name  TEXT NOT NULL,
    city_name  TEXT,
    geometry   GEOMETRY(MULTIPOLYGON, 4326) NOT NULL
);
"""

_GIST = (
    f"CREATE INDEX IF NOT EXISTS {ADMIN_TABLE}_geometry_gist "
    f"ON {ADMIN_TABLE} USING GIST (geometry);"
)


def _to_multipolygon(geom: BaseGeometry | None) -> MultiPolygon | None:
    """単ポリゴンを1要素の MultiPolygon に昇格する（型を揃えるため）。"""
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "MultiPolygon":
        return geom
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    raise ValueError(f"想定外のジオメトリ型: {geom.geom_type}")


def read_pref(pref_code: str) -> gpd.GeoDataFrame:
    """1県の N03 shapefile を zip から直読みし、必要列に絞って 4326 へ変換する。"""
    zip_path = N03_DIR / f"N03-20260101_{pref_code}_GML.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"N03 zip が見つからない: {zip_path}（先にダウンロードする）")
    # GDAL の /vsizip/ で zip 内 shapefile を直読み（.prj=EPSG:6668 を持つ）
    src = f"/vsizip/{zip_path}/N03-20260101_{pref_code}.shp"
    gdf = gpd.read_file(src, columns=list(_FIELD_MAP.keys()))
    gdf = gdf.rename(columns=_FIELD_MAP)
    gdf = gdf.to_crs(epsg=4326)  # 6668 → 4326（SRID を roads に揃える）
    gdf["geometry"] = gdf.geometry.apply(_to_multipolygon)
    gdf = gdf[gdf.geometry.notna()].reset_index(drop=True)
    logger.info("pref %s: %d polygons", pref_code, len(gdf))
    return gdf


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    settings = get_settings()

    parts = [read_pref(p) for p in PREF_CODES]
    admin = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:4326")
    logger.info("total polygons across %d prefectures: %d", len(PREF_CODES), len(admin))

    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(text(_DDL))
            conn.execute(text(f"TRUNCATE {ADMIN_TABLE} RESTART IDENTITY"))
        # 型付き既存テーブルへ追記（gid は IDENTITY で自動採番）
        admin.to_postgis(ADMIN_TABLE, engine, if_exists="append")
        with engine.begin() as conn:
            conn.execute(text(_GIST))
        logger.info("loaded %d rows into %s (+GIST)", len(admin), ADMIN_TABLE)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
