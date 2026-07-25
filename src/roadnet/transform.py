"""transform層: 生データのまま投入したデータセットに対して、変換処理を行う。
"""

from __future__ import annotations

import logging
from importlib.resources import files

from sqlalchemy import create_engine, text

from ._sql import GEOMETRY_COLUMN, gist_index_sql, validate_table_name

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# transform実行（pythonからsqlファイルを実行するオーケストレーション）                #
# --------------------------------------------------------------------------- #
def transform(database_url: str, table: str) -> int:
    validate_table_name(table)

    total_rows = 0
    engine = create_engine(database_url)
    try:
        sql_text = files("roadnet").joinpath("sql/transform.sql").read_text(encoding="utf-8")

        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {table}"))
            result = conn.execute(text(sql_text))   # ← 受ける
            total_rows = result.rowcount
            conn.execute(text(gist_index_sql(table)))
            logger.info("created GIST index on %s.%s", table, GEOMETRY_COLUMN)
            logger.info("loaded %d total rows into table %s", total_rows, table)
            
    finally:
        engine.dispose()
    
    return total_rows