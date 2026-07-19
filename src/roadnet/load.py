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
import re
from pathlib import Path

import geopandas as gpd
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

GEOMETRY_COLUMN = "geometry"

_TABLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


# --------------------------------------------------------------------------- #
# 純粋なヘルパー（I/O なし — ユニットテスト可能）                               #
# --------------------------------------------------------------------------- #
def validate_table_name(name: str) -> str:
    """``name`` が引用符不要の安全な PostgreSQL 識別子であればそのまま返す。

    テーブル名は DDL（インデックス作成）に文字列として埋め込まれるため、
    ``[a-z_][a-z0-9_]*`` に厳密に一致しないものはすべて拒否する — これは
    ホワイトリストであり、エスケープ機構ではない。
    """
    if not _TABLE_NAME_RE.fullmatch(name):
        raise ValueError(
            f"Unsafe table name {name!r}: must match [a-z_][a-z0-9_]* "
            "(lowercase letters, digits, underscores; not starting with a digit)."
        )
    return name


def gist_index_sql(table: str, geometry_column: str = GEOMETRY_COLUMN) -> str:
    """テーブルのジオメトリカラムに対する ``CREATE INDEX`` 文を組み立てる。

    どちらの識別子も、埋め込み前に同じホワイトリストで検証する。
    """
    safe_table = validate_table_name(table)
    safe_geom = validate_table_name(geometry_column)
    return (
        f"CREATE INDEX IF NOT EXISTS {safe_table}_{safe_geom}_gist "
        f"ON {safe_table} USING GIST ({safe_geom})"
    )


# --------------------------------------------------------------------------- #
# I/O                                                                          #
# --------------------------------------------------------------------------- #
def load_parts_to_postgis(part_paths: list[Path], database_url: str, table: str) -> int:
    """parquet パートを PostGIS にストリーム投入する。総ロード行数を返す。

    最初のパートは ``if_exists="replace"`` で書き（再実行の冪等性）、残りは
    ``append``。最後にジオメトリカラムへ GIST インデックスを作成する。
    """
    if not part_paths:
        raise ValueError("No parts to load.")
    validate_table_name(table)

    engine = create_engine(database_url)
    total_rows = 0
    try:
        for i, path in enumerate(part_paths):
            gdf = gpd.read_parquet(path)
            gdf.to_postgis(table, engine, if_exists="replace" if i == 0 else "append")
            total_rows += len(gdf)
            logger.info("loaded %s (%d rows) -> %s", path.name, len(gdf), table)

        with engine.begin() as conn:
            conn.execute(text(gist_index_sql(table)))
        logger.info("created GIST index on %s.%s", table, GEOMETRY_COLUMN)
    finally:
        engine.dispose()

    logger.info("loaded %d total rows into table %s", total_rows, table)
    return total_rows
