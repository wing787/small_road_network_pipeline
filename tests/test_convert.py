"""convert.py の純粋な変換ロジックのテスト（ネットワークなし・実データなし）。"""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from roadnet.convert import (
    SOURCE_MESH_COLUMN,
    count_invalid_geometries,
    crs_epsg,
    normalize_roads,
)


def _sample_roads() -> gpd.GeoDataFrame:
    """実際の N13 GeoJSON と同じ形をした小さな合成メッシュ。"""
    return gpd.GeoDataFrame(
        {
            "N13_001": ["2018-10-05", "2019-01-01"],
            "N13_002": ["2", "3"],
            "N13_008": ["362257", "362258"],
            "geometry": [
                LineString([(0, 0), (1, 1)]),
                LineString([(1, 1), (2, 0)]),
            ],
        },
        crs="EPSG:6668",
    )


def test_normalize_renames_columns_and_tags_source_mesh() -> None:
    gdf = _sample_roads()
    out = normalize_roads(gdf, mesh_code="3622")

    assert "road_type" in out.columns  # N13_002 -> road_type
    assert "registration_date" in out.columns  # N13_001 -> registration_date
    assert "secondary_mesh_code" in out.columns  # N13_008
    assert "N13_002" not in out.columns
    assert (out[SOURCE_MESH_COLUMN] == "3622").all()
    assert len(out) == len(gdf)  # 正規化で行が落ちてはならない


def test_normalize_leaves_unknown_columns_untouched() -> None:
    gdf = _sample_roads()
    gdf["extra_col"] = [1, 2]
    out = normalize_roads(gdf, mesh_code="3622")
    assert "extra_col" in out.columns


def test_count_invalid_detects_bad_geometries() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])  # 自己交差 -> 不正ジオメトリ
    good = LineString([(0, 0), (1, 1)])
    empty = LineString()
    gdf = gpd.GeoDataFrame({"geometry": [good, bowtie, empty, None]}, crs="EPSG:6668")
    # bowtie（不正）+ empty + None => 3件が検出対象。正常なラインは含まれない。
    assert count_invalid_geometries(gdf) == 3


def test_count_invalid_zero_for_clean_data() -> None:
    assert count_invalid_geometries(_sample_roads()) == 0


def test_crs_epsg_reads_code() -> None:
    assert crs_epsg(_sample_roads()) == 6668
    no_crs = gpd.GeoDataFrame({"geometry": [LineString([(0, 0), (1, 1)])]})
    assert crs_epsg(no_crs) is None
