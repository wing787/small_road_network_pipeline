"""merge.py のテスト: ストリーム結合の件数保存 + 重複検出ヘルパー。"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely.geometry import LineString

from roadnet.convert import SOURCE_MESH_COLUMN
from roadnet.merge import (
    find_cross_mesh_duplicates,
    merge_parts,
    merge_parts_to_flatgeobuf,
)


def _part(mesh: str, lines: list[LineString]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {SOURCE_MESH_COLUMN: [mesh] * len(lines), "geometry": lines},
        crs="EPSG:6668",
    )


def _write_two_parts(tmp_path: Path) -> tuple[Path, Path]:
    """合成パート2つ: 2フィーチャ（メッシュ3622）+ 1フィーチャ（メッシュ3631）。"""
    part_a = _part("3622", [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])])
    part_b = _part("3631", [LineString([(5, 5), (6, 6)])])
    pa_path = tmp_path / "a.parquet"
    pb_path = tmp_path / "b.parquet"
    part_a.to_parquet(pa_path, index=False)
    part_b.to_parquet(pb_path, index=False)
    return pa_path, pb_path


def test_merge_preserves_feature_count_and_is_geoparquet(tmp_path: Path) -> None:
    part_a = _part("3622", [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])])
    part_b = _part("3631", [LineString([(2, 2), (3, 3)])])

    pa_path = tmp_path / "a.parquet"
    pb_path = tmp_path / "b.parquet"
    part_a.to_parquet(pa_path, index=False)
    part_b.to_parquet(pb_path, index=False)

    out = tmp_path / "merged.parquet"
    total = merge_parts([pa_path, pb_path], out)

    assert total == 3  # 2 + 1。行の欠落も重複もないこと

    # geopandas でラウンドトリップできること（= GeoParquet の `geo` メタデータが保持された証拠）。
    merged = gpd.read_parquet(out)
    assert isinstance(merged, gpd.GeoDataFrame)
    assert len(merged) == 3
    assert merged.crs is not None and merged.crs.to_epsg() == 6668
    assert set(merged[SOURCE_MESH_COLUMN]) == {"3622", "3631"}


def test_merge_fgb_preserves_count_and_roundtrips(tmp_path: Path) -> None:
    pa_path, pb_path = _write_two_parts(tmp_path)
    out = tmp_path / "merged.fgb"

    total = merge_parts_to_flatgeobuf([pa_path, pb_path], out)
    assert total == 3

    # pyogrio でのラウンドトリップ
    via_pyogrio = pyogrio.read_dataframe(out)
    assert len(via_pyogrio) == 3
    assert set(via_pyogrio[SOURCE_MESH_COLUMN]) == {"3622", "3631"}

    # geopandas でのラウンドトリップ（利用者の大半はこちらを使う）
    via_gpd = gpd.read_file(out)
    assert isinstance(via_gpd, gpd.GeoDataFrame)
    assert len(via_gpd) == 3
    assert via_gpd.crs is not None and via_gpd.crs.to_epsg() == 6668


def test_merge_fgb_has_spatial_index(tmp_path: Path) -> None:
    pa_path, pb_path = _write_two_parts(tmp_path)
    out = tmp_path / "merged.fgb"
    merge_parts_to_flatgeobuf([pa_path, pb_path], out)

    # FlatGeobuf の存在意義: パック済み空間インデックスが追記後も生きていること。
    info = pyogrio.read_info(out)
    assert info["capabilities"]["fast_spatial_filter"] is True

    # さらに bbox クエリが実際に正しく機能すること: (5,5)-(6,6) 付近にあるのは
    # メッシュ3631のラインだけ。
    subset = pyogrio.read_dataframe(out, bbox=(4.5, 4.5, 6.5, 6.5))
    assert len(subset) == 1
    assert set(subset[SOURCE_MESH_COLUMN]) == {"3631"}


def test_merge_fgb_overwrites_previous_output(tmp_path: Path) -> None:
    # merge の再実行が前回のファイルに追記してはならない（件数が倍になってしまう）。
    pa_path, pb_path = _write_two_parts(tmp_path)
    out = tmp_path / "merged.fgb"
    assert merge_parts_to_flatgeobuf([pa_path, pb_path], out) == 3
    assert merge_parts_to_flatgeobuf([pa_path, pb_path], out) == 3
    assert len(pyogrio.read_dataframe(out)) == 3


def test_find_cross_mesh_duplicates_flags_shared_geometry() -> None:
    shared = LineString([(0, 0), (1, 1)])  # 2つのメッシュが同じラインを配布しているケース
    unique_a = LineString([(1, 1), (2, 2)])
    unique_b = LineString([(5, 5), (6, 6)])

    gdf = gpd.GeoDataFrame(
        {
            SOURCE_MESH_COLUMN: ["3622", "3622", "3631", "3631"],
            "geometry": [shared, unique_a, shared, unique_b],
        },
        crs="EPSG:6668",
    )
    dups = find_cross_mesh_duplicates(gdf)
    assert len(dups) == 2  # `shared` の2行のみ
    assert set(dups[SOURCE_MESH_COLUMN]) == {"3622", "3631"}


def test_find_cross_mesh_duplicates_ignores_same_mesh_repeats() -> None:
    # 同一ジオメトリが2回あっても、1つのメッシュ内ならメッシュ跨ぎ重複ではない。
    line = LineString([(0, 0), (1, 1)])
    gdf = gpd.GeoDataFrame(
        {SOURCE_MESH_COLUMN: ["3622", "3622"], "geometry": [line, line]},
        crs="EPSG:6668",
    )
    assert len(find_cross_mesh_duplicates(gdf)) == 0


def test_find_cross_mesh_duplicates_empty_input() -> None:
    empty = gpd.GeoDataFrame({SOURCE_MESH_COLUMN: [], "geometry": []}, crs="EPSG:6668")
    assert len(find_cross_mesh_duplicates(empty)) == 0
