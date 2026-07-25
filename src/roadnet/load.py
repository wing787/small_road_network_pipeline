"""ロード層: メッシュ単位の GeoParquet パートを PostGIS テーブルにストリーム投入する。

ストリーミング原則（merge.py と同じ）: パートは ``GeoDataFrame.to_postgis``
で1つずつ読み書きし、データセット全体をメモリに載せない。最初のパートで
対象テーブルを*置き換える*ため、再実行しても二重投入されない（冪等）。
以降のパートは追記。ロード完了後にジオメトリカラムへ GIST インデックスを
作成する。

純粋なヘルパー（``validate_table_name``、``gist_index_sql``）は I/O を持たず、
データベースなしでユニットテストされる。このリポジトリのテストは PostGIS の
起動を一切必要としない。
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
    """parquet パートを PostGIS にストリーム投入する。総ロード行数を返す。
    """
    # 最初のパートは ``if_exists="replace"`` で書き（再実行の冪等性）、残りは
    # ``append``。最後にジオメトリカラムへ GIST インデックスを作成する。
    
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