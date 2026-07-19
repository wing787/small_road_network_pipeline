"""変換層: メッシュ zip 1つ → 正規化済みのメッシュ単位 GeoParquet。

純粋な変換関数（``normalize_roads``、``count_invalid_geometries``、
``crs_epsg``）は GeoDataFrame を受け取り GeoDataFrame を返すだけでファイル
アクセスを持たないため、合成データでユニットテストできる。I/O ラッパー
（``read_mesh_zip``、``convert_zip_to_parquet``）が zip の読み込みと
parquet の書き出しを担当する。
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path

import geopandas as gpd

logger = logging.getLogger(__name__)

# EPSG:6668 = JGD2011 地理座標系（経緯度）。実際の N13-2024 データで確認済み。
EXPECTED_EPSG = 6668

# 元カラム名 → 安定した可読名。
# 意味は国土数値情報 N13（道路データ）の製品仕様書に基づく。
COLUMN_MAP: dict[str, str] = {
    "N13_001": "registration_date",  # データ登録日
    "N13_002": "road_type",  # 種別
    "N13_003": "road_classification",  # 道路分類
    "N13_004": "road_status",  # 道路状態
    "N13_005": "layer_order",  # 階層順（地表からの上下関係）
    "N13_006": "width_category",  # 幅員区分
    "N13_007": "toll_category",  # 有料区分
    "N13_008": "secondary_mesh_code",  # 二次メッシュ番号
}

SOURCE_MESH_COLUMN = "source_mesh"

_MESH_RE = re.compile(r"N13-24_(\d+)_", re.IGNORECASE)


class ConvertError(RuntimeError):
    """メッシュ zip を利用可能な GeoDataFrame として読めなかったときに送出。"""


# --------------------------------------------------------------------------- #
# 純粋な変換（I/O なし — ユニットテスト可能）                                    #
# --------------------------------------------------------------------------- #
def normalize_roads(gdf: gpd.GeoDataFrame, mesh_code: str) -> gpd.GeoDataFrame:
    """N13_* カラムを安定名にリネームし、由来メッシュを行に付与する。

    未知のカラムはそのまま残す。ジオメトリカラムは保持される。
    """
    renamed = gdf.rename(columns=COLUMN_MAP)
    renamed[SOURCE_MESH_COLUMN] = mesh_code
    return renamed


def count_invalid_geometries(gdf: gpd.GeoDataFrame) -> int:
    """欠損・空・トポロジー不正なジオメトリの件数を数える。

    あくまで*報告*のみで、修復は行わない。元データを暗黙に書き換えない
    ため、修復は MVP のスコープから意図的に外している。
    """
    geom = gdf.geometry
    missing = geom.isna()
    # is_empty / is_valid は欠損ジオメトリに対して未定義なので fillna でガードする。
    empty = geom.is_empty.fillna(False)
    invalid = (~geom.is_valid).fillna(False)
    flagged = missing | empty | invalid
    return int(flagged.sum())


def crs_epsg(gdf: gpd.GeoDataFrame) -> int | None:
    """GeoDataFrame の CRS の EPSG コードを返す。不明なら ``None``。"""
    if gdf.crs is None:
        return None
    epsg = gdf.crs.to_epsg()
    return int(epsg) if epsg is not None else None


# --------------------------------------------------------------------------- #
# I/O ラッパー                                                                  #
# --------------------------------------------------------------------------- #
def mesh_code_from_path(path: Path) -> str:
    """``N13-24_XXXX_*`` 形式のファイル名から4桁メッシュコードを抽出する。"""
    m = _MESH_RE.search(path.name)
    if not m:
        raise ConvertError(f"Cannot parse mesh code from {path.name!r}")
    return m.group(1)


def _inner_data_member(zip_path: Path) -> str:
    """メッシュ zip 内の GeoJSON（優先）または Shapefile メンバーを探す。"""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    geojson = [n for n in names if n.lower().endswith((".geojson", ".json"))]
    if geojson:
        return geojson[0]
    shp = [n for n in names if n.lower().endswith(".shp")]
    if shp:
        return shp[0]
    raise ConvertError(f"No .geojson/.json/.shp found in {zip_path.name}")


def read_mesh_zip(zip_path: Path) -> gpd.GeoDataFrame:
    """GDAL の /vsizip/ 経由でメッシュ zip からベクターレイヤーを読み込む。

    N13-2024 は GeoJSON（UTF-8）で配布されているため、ここではエンコーディング
    処理は不要。下の Shapefile フォールバックは、将来の zip や例外的な zip が
    GeoJSON を含まない場合に備えたもので、国土数値情報の慣例に従い .dbf を
    Shift-JIS として読む。
    """
    inner = _inner_data_member(zip_path)
    vsi_path = f"/vsizip/{zip_path}/{inner}"
    read_kwargs: dict[str, object] = {}
    if inner.lower().endswith(".shp"):
        read_kwargs["encoding"] = "cp932"  # 国土数値情報の慣例に従い DBF は Shift-JIS
    gdf = gpd.read_file(vsi_path, **read_kwargs)
    if not isinstance(gdf, gpd.GeoDataFrame):  # 防御的チェック。read_file は DataFrame を返しうる
        raise ConvertError(f"{zip_path.name} did not yield a GeoDataFrame")
    return gdf


def convert_zip_to_parquet(zip_path: Path, parts_dir: Path) -> Path:
    """メッシュ zip 1つを読み、正規化し、品質統計をログし、GeoParquet パートを書く。

    書き出した parquet のパスを返す。既存パートは上書きする（コストが小さく、
    再実行を決定的に保てるため）。
    """
    mesh_code = mesh_code_from_path(zip_path)
    gdf = read_mesh_zip(zip_path)

    epsg = crs_epsg(gdf)
    if epsg != EXPECTED_EPSG:
        logger.warning(
            "mesh %s: CRS EPSG:%s differs from expected EPSG:%s",
            mesh_code, epsg, EXPECTED_EPSG,
        )

    invalid = count_invalid_geometries(gdf)
    if invalid:
        logger.warning("mesh %s: %d invalid/empty/missing geometries (not repaired)",
                       mesh_code, invalid)

    normalized = normalize_roads(gdf, mesh_code)

    parts_dir.mkdir(parents=True, exist_ok=True)
    out_path = parts_dir / f"{zip_path.stem}.parquet"
    normalized.to_parquet(out_path, index=False)
    logger.info("mesh %s: wrote %d features -> %s", mesh_code, len(normalized), out_path.name)
    return out_path


def convert_all(zip_paths: list[Path], parts_dir: Path) -> list[Path]:
    """すべてのメッシュ zip を GeoParquet パートに変換する。"""
    return [convert_zip_to_parquet(p, parts_dir) for p in zip_paths]
