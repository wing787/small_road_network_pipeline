"""結合層: メッシュ単位の GeoParquet パートをストリーミングで結合出力する。

同じ ``parts/*.parquet`` から2つの形式を出力する:

- **GeoParquet**（``merge_parts``）: 単一の ``pyarrow.parquet.ParquetWriter``
  でパートを1つずつ書き込む — 全パートをメモリ上で連結することはしない。
  writer は*最初の*パートのスキーマ（GeoParquet の ``geo`` メタデータ含む）を
  採用するため、出力は ``geopandas.read_parquet`` で読める。
- **FlatGeobuf**（``merge_parts_to_flatgeobuf``）: パートを1つずつ読み、
  ``pyogrio.write_dataframe(append=True)`` で追記する。pyogrio 0.13 /
  GDAL 3.12 で検証済み: append は動作し、追記後もパック済み空間インデックス
  が保持される（``fast_spatial_filter`` ケーパビリティ、bbox クエリ）。

ストリーミング原則（実運用の「数百万フィーチャ」ケースで重要）: どちらの
形式でも、メモリ上に保持するパートは常に最大1つ。

既知の制限:

- GeoParquet: ``geo`` メタデータ（特に ``bbox``）は最初のパートからそのまま
  コピーされるため、結合ファイルの bbox はそのメッシュの範囲しか示さず、
  全体の範囲にならない。README 参照。
- FlatGeobuf: GDAL の append は内部でファイルを再構築（インデックスの
  再ソート）することがあり、パート数が多いと総書き込みコストが線形以上に
  増えうる。MVP スケールでは問題ないが、数千パート／数千万行を結合する
  前に再検討すること。
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pyarrow.parquet as pq
import pyogrio

from .convert import SOURCE_MESH_COLUMN

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 純粋なヘルパー（I/O なし — ユニットテスト可能）                                #
# --------------------------------------------------------------------------- #
def find_cross_mesh_duplicates(
    gdf: gpd.GeoDataFrame, mesh_col: str = SOURCE_MESH_COLUMN
) -> gpd.GeoDataFrame:
    """同一ジオメトリが複数の異なるメッシュに現れる行を返す。

    N13 のフィーチャには安定したグローバル ID がないため、隣接する2つの
    メッシュファイルが同じ道路ラインを重複して含むケースをジオメトリ（WKB）
    をキーに検出する。そうしたメッシュ跨ぎ重複に関与する ``gdf`` の部分集合
    （空になりうる）を返す。
    """
    if len(gdf) == 0:
        return gdf.iloc[0:0]
    wkb = gdf.geometry.apply(lambda g: None if g is None else g.wkb)
    # ジオメトリキーごとに異なるメッシュ数を数え、2メッシュ以上で共有される行を残す。
    distinct = gdf.assign(_wkb=wkb).groupby("_wkb")[mesh_col].transform("nunique")
    mask = distinct > 1
    return gdf[mask.to_numpy()]


# --------------------------------------------------------------------------- #
# ストリーミング結合（I/O）                                                     #
# --------------------------------------------------------------------------- #
def merge_parts(part_paths: list[Path], output_path: Path) -> int:
    """parquet パートを1ファイルにストリーム結合する。総書き込み行数を返す。

    最初のパートの Arrow スキーマ（GeoParquet の ``geo`` メタデータ含む）を
    出力全体に使い、以降のパートは書き込み前にそのスキーマへキャストする。
    """
    if not part_paths:
        raise ValueError("No parts to merge.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer: pq.ParquetWriter | None = None
    total_rows = 0
    try:
        for path in part_paths:
            table = pq.read_table(path)
            if writer is None:
                writer = pq.ParquetWriter(output_path, table.schema)
            else:
                # カラム型を最初のパートに揃える。パートごとのスキーマ
                # メタデータも落ちるため、最初のパートの `geo` ブロックが保たれる。
                table = table.cast(writer.schema)
            writer.write_table(table)
            total_rows += table.num_rows
            logger.info("merged %s (%d rows)", path.name, table.num_rows)
    finally:
        if writer is not None:
            writer.close()

    logger.info("wrote %d total rows -> %s", total_rows, output_path)
    return total_rows


def merge_parts_to_flatgeobuf(part_paths: list[Path], output_path: Path) -> int:
    """parquet パートを1つの FlatGeobuf にストリーム結合する。総書き込み行数を返す。

    パートは1つずつ読み（メモリ使用量を抑制）、pyogrio の FlatGeobuf
    ドライバで追記する。最初のパートがファイルを作成し、既存の出力は先に
    削除する — 前回の結果に追記せず、再実行を決定的に保つため。

    出力される .fgb は FlatGeobuf 組み込みのパック済み空間インデックスを
    持つため、QGIS や bbox フィルタ付き読み込みが期待どおり動く。

    注: GDAL の FGB append は追記のたびに内部でファイルを再構築することが
    あり、パート数に対して書き込みコストが線形以上に増えうる。MVP スケール
    （数パート）では許容範囲。モジュール docstring 参照。
    """
    if not part_paths:
        raise ValueError("No parts to merge.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)

    total_rows = 0
    for i, path in enumerate(part_paths):
        gdf = gpd.read_parquet(path)
        pyogrio.write_dataframe(gdf, output_path, driver="FlatGeobuf", append=i > 0)
        total_rows += len(gdf)
        logger.info("merged %s (%d rows) -> fgb", path.name, len(gdf))

    logger.info("wrote %d total rows -> %s", total_rows, output_path)
    return total_rows
