"""roads_all.parquet を「空間ソート + bbox covering 列付き」で書き直す（M3 タスク1・改善実験）。

狙い: S3 直読の bbox 検索で row-group プルーニングを効かせ、転送量を下げられるか検証する。
そのために2つを同時に満たす必要がある（片方だけでは効かない）:
  1. ``write_covering_bbox=True`` … 行ごとの bbox を別列で持ち、parquet が row-group 単位で
     その min/max 統計を残す（DuckDB が検索範囲と突き合わせて row-group を刈る材料）。
  2. 空間ソート（Hilbert 曲線）… 近い地物を同じ row-group に固める。これが無いと各
     row-group の bbox が日本全域に広がり、min/max 統計が無意味 ＝ 刈れない（落とし穴）。
さらに row-group が1つだと刈りようが無いので、``row_group_size`` を明示して複数に割る。

入力 : data/output/roads_all.parquet（既存の結合済み 194万件）
出力 : data/output/roads_all_bbox.parquet
実行 : uv run python scripts/write_bbox_covering_parquet.py
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

_SRC = Path("data/output/roads_all.parquet")
_DST = Path("data/output/roads_all_bbox.parquet")
# 194万件 ÷ 10万 ≒ 約20 row-group。プルーニングの粒度（細かいほど刈りやすいが overhead 増）。
_ROW_GROUP_SIZE = 100_000


def main() -> None:
    gdf = gpd.read_parquet(_SRC)

    # Hilbert 距離で空間ソート: 近接地物を隣り合わせ、各 row-group の bbox を締める。
    # これが covering 列の min/max 統計を「選択的」にする本体（ソート無しでは効かない）。
    order = gdf.geometry.hilbert_distance()
    gdf = gdf.iloc[order.argsort()].reset_index(drop=True)

    gdf.to_parquet(
        _DST,
        write_covering_bbox=True,
        row_group_size=_ROW_GROUP_SIZE,
    )
    print(f"wrote {len(gdf):,} rows -> {_DST} (row_group_size={_ROW_GROUP_SIZE:,})")


if __name__ == "__main__":
    main()
