import re

_TABLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
GEOMETRY_COLUMN = "geometry"

# --------------------------------------------------------------------------- #
# 純粋なヘルパー（I/O なし — ユニットテスト可能）                                    #
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

# --------------------------------------------------------------------------- #
# ジオメトリのインデックス作成                                                     #
# --------------------------------------------------------------------------- #
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