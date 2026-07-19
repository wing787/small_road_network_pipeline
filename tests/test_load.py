"""load.py の純粋なヘルパーのテスト — データベース不要。"""

from __future__ import annotations

import pytest

from roadnet.load import gist_index_sql, validate_table_name


def test_validate_table_name_accepts_safe_identifiers() -> None:
    assert validate_table_name("roads") == "roads"
    assert validate_table_name("roads_2024") == "roads_2024"
    assert validate_table_name("_staging") == "_staging"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "1roads",  # 数字始まり
        "Roads",  # 大文字（引用符が必要になる）
        "roads; DROP TABLE",  # SQLインジェクションの試み
        'roads"',  # 引用符による識別子の脱出
        "road-net",  # ハイフン
        "roads table",  # 空白
    ],
)
def test_validate_table_name_rejects_unsafe_identifiers(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_table_name(bad)


def test_gist_index_sql_builds_expected_statement() -> None:
    sql = gist_index_sql("roads")
    assert sql == ("CREATE INDEX IF NOT EXISTS roads_geometry_gist ON roads USING GIST (geometry)")


def test_gist_index_sql_validates_both_identifiers() -> None:
    with pytest.raises(ValueError):
        gist_index_sql("roads; DROP TABLE x")
    with pytest.raises(ValueError):
        gist_index_sql("roads", geometry_column='geom"')
