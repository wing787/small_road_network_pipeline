"""ロード層: メッシュ単位の GeoParquet パートを PostGIS のステージングテーブルへ
ストリーム投入する。

ストリーミング原則（merge.py と同じ）: パートは ``GeoDataFrame.to_postgis``
で1つずつ読み書きし、データセット全体をメモリに載せない。投入前に対象テーブルを
``TRUNCATE`` してから全パートを ``if_exists="append"`` で追記するため、再実行
しても二重投入されない（冪等）。``if_exists="replace"`` は使わない（テーブルを
DROP して gdf 推論スキーマで作り直してしまい、schema.sql で設計した
ステージングテーブルを破壊するため）。

投入先は緩いステージングテーブル（``roads_stage``）で、型変換・CRS変換・制約は
後段の ``transform`` が担う。純粋なヘルパー（``validate_table_name``）は I/O を
持たず、データベースなしでユニットテストされる。このリポジトリのテストは
PostGIS の起動を一切必要としない。
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
from sqlalchemy import create_engine, text

from ._sql import validate_table_name

logger = logging.getLogger(__name__)



# --------------------------------------------------------------------------- #
# I/O                                                                         #
# --------------------------------------------------------------------------- #
def load_parts_to_postgis(part_paths: list[Path], database_url: str, table: str) -> int:
    """parquet パートを PostGIS のステージングテーブルへストリーム投入する。
    総ロード行数を返す。
    """
    # 冪等性: 投入前に一度 ``TRUNCATE`` し、全パートを ``append`` で追記する。
    # 型変換・CRS変換・GIST インデックスは後段の ``transform`` が担う。

    if not part_paths:
        raise ValueError("No parts to load.")
    validate_table_name(table)

    engine = create_engine(database_url)
    total_rows = 0
    try:
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {table}"))
        
        for path in part_paths:
            gdf = gpd.read_parquet(path)
            gdf.to_postgis(table, engine, if_exists="append")
            total_rows += len(gdf)
            logger.info("loaded %s (%d rows) -> %s", path.name, len(gdf), table)

    finally:
        engine.dispose()

    logger.info("loaded %d total rows into table %s", total_rows, table)
    return total_rows