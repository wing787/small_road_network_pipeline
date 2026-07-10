"""Convert layer: one mesh zip -> normalized per-mesh GeoParquet.

The pure transforms (``normalize_roads``, ``count_invalid_geometries``,
``crs_epsg``) take and return GeoDataFrames with no filesystem access, so they
are unit-testable on synthetic data. The I/O wrappers (``read_mesh_zip``,
``convert_zip_to_parquet``) handle reading zips and writing parquet.
"""

from __future__ import annotations

import logging
import re
import zipfile
from pathlib import Path

import geopandas as gpd

logger = logging.getLogger(__name__)

# EPSG:6668 = JGD2011 geographic (lon/lat). Confirmed against real N13-2024 data.
EXPECTED_EPSG = 6668

# Source column -> stable, human-readable name.
# Meanings per the 国土数値情報 N13 product spec (道路データ).
COLUMN_MAP: dict[str, str] = {
    "N13_001": "registration_date",       # データ登録日
    "N13_002": "road_type",               # 種別
    "N13_003": "road_classification",     # 道路分類
    "N13_004": "road_status",             # 道路状態
    "N13_005": "layer_order",             # 階層順（地表からの上下関係）
    "N13_006": "width_category",          # 幅員区分
    "N13_007": "toll_category",           # 有料区分
    "N13_008": "secondary_mesh_code",     # 二次メッシュ番号
}

SOURCE_MESH_COLUMN = "source_mesh"

_MESH_RE = re.compile(r"N13-24_(\d+)_", re.IGNORECASE)


class ConvertError(RuntimeError):
    """Raised when a mesh zip cannot be read into a usable GeoDataFrame."""


# --------------------------------------------------------------------------- #
# Pure transforms (no I/O — unit-testable)                                     #
# --------------------------------------------------------------------------- #
def normalize_roads(gdf: gpd.GeoDataFrame, mesh_code: str) -> gpd.GeoDataFrame:
    """Rename N13_* columns to stable names and tag rows with their source mesh.

    Unknown columns are left as-is. The geometry column is preserved.
    """
    renamed = gdf.rename(columns=COLUMN_MAP)
    renamed[SOURCE_MESH_COLUMN] = mesh_code
    return renamed


def count_invalid_geometries(gdf: gpd.GeoDataFrame) -> int:
    """Count geometries that are missing, empty, or topologically invalid.

    This only *reports* — it never repairs. Repair is deliberately out of scope
    for the MVP so we do not silently alter source data.
    """
    geom = gdf.geometry
    missing = geom.isna()
    # is_empty / is_valid are undefined for missing geometries; guard with fillna.
    empty = geom.is_empty.fillna(False)
    invalid = (~geom.is_valid).fillna(False)
    flagged = missing | empty | invalid
    return int(flagged.sum())


def crs_epsg(gdf: gpd.GeoDataFrame) -> int | None:
    """Return the EPSG code of the GeoDataFrame's CRS, or ``None`` if unknown."""
    if gdf.crs is None:
        return None
    epsg = gdf.crs.to_epsg()
    return int(epsg) if epsg is not None else None


# --------------------------------------------------------------------------- #
# I/O wrappers                                                                 #
# --------------------------------------------------------------------------- #
def mesh_code_from_path(path: Path) -> str:
    """Extract the 4-digit mesh code from an ``N13-24_XXXX_*`` filename."""
    m = _MESH_RE.search(path.name)
    if not m:
        raise ConvertError(f"Cannot parse mesh code from {path.name!r}")
    return m.group(1)


def _inner_data_member(zip_path: Path) -> str:
    """Find the GeoJSON (preferred) or Shapefile member inside a mesh zip."""
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
    """Read the vector layer out of a mesh zip via GDAL's /vsizip/.

    N13-2024 ships GeoJSON (UTF-8), so no encoding handling is needed here. The
    Shapefile fallback below reads its .dbf as Shift-JIS, which is the KSJ
    convention, in case a future/edge zip lacks GeoJSON.
    """
    inner = _inner_data_member(zip_path)
    vsi_path = f"/vsizip/{zip_path}/{inner}"
    read_kwargs: dict[str, object] = {}
    if inner.lower().endswith(".shp"):
        read_kwargs["encoding"] = "cp932"  # Shift-JIS DBF, per KSJ convention
    gdf = gpd.read_file(vsi_path, **read_kwargs)
    if not isinstance(gdf, gpd.GeoDataFrame):  # defensive; read_file may yield DataFrame
        raise ConvertError(f"{zip_path.name} did not yield a GeoDataFrame")
    return gdf


def convert_zip_to_parquet(zip_path: Path, parts_dir: Path) -> Path:
    """Read one mesh zip, normalize it, log quality stats, write a GeoParquet part.

    Returns the written parquet path. Overwrites any existing part (cheap, and
    keeps re-runs deterministic).
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
    """Convert every mesh zip to a GeoParquet part."""
    return [convert_zip_to_parquet(p, parts_dir) for p in zip_paths]
