"""S3 上の GeoParquet を DuckDB(httpfs) で読むときの「転送量」を測る補助スクリプト（M3 タスク1）。

用途: 同じファイルへの3つの問いが、Range GET で実際に何バイト転送するかを比較する。
「列を絞れば転送は桁で減る」一方、「空間 bbox 検索は（bbox covering 列が無い今の
parquet では）row-group を刈れず geometry 列をほぼ全部引く」を、憶測でなく実測バイトで示す。
docs/postgis-vs-duckdb.md の S3 版に相当。

計測の仕組み:
- ``CALL enable_logging('HTTP')`` で DuckDB 自身の HTTP リクエストログを ``duckdb_logs``
  に残し、GET 応答の Content-Length を合算して転送量を出す（解析は roadnet.http_stats）。
- 拡張の DL や secret 生成をログに混ぜないため、INSTALL/LOAD と CREATE SECRET の「後」に
  ログを有効化する。さらに問いごとに新しい接続を使い、ログの混線を避ける（接続 = ログの器）。

前提:
- 対象の GeoParquet が S3 に配置済みで、``aws sso login`` 済み（credential_chain が拾える）。
- DuckDB 拡張 spatial / httpfs は初回に自動 INSTALL される。
- 3問目（bbox）は geometry 列を広く引くため、数十 MB の egress が出る点に注意。

実行:
    uv run python scripts/measure_s3_transfer.py \\
        --s3-url s3://<bucket>/roads/roads_all.parquet
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import duckdb

from roadnet.http_stats import summarize_transfer

# 東京駅周辺の bbox（経度, 緯度）。docs/postgis-vs-duckdb.md と揃える。
_BBOX = (139.75, 35.66, 139.79, 35.70)
_DEFAULT_S3_URL = "s3://small-road-network-pipeline-r7k3/roads/roads_all.parquet"
_DEFAULT_REGION = "ap-northeast-1"


@dataclass(frozen=True)
class Probe:
    """1つの問い（ラベルと SQL）。"""

    label: str
    sql: str


def _probes(url: str, *, bbox_covering: bool = False) -> list[Probe]:
    """転送量スペクトルを見せる問い（縦=列プロジェクション / 横=行の絞り込み）。

    bbox_covering=True のファイル（bbox covering 列あり）では、row-group プルーニングを
    引き出す「bbox 列述語」版も測る。DuckDB 1.5.5 は ST_Intersects を covering 統計へ
    自動では押し下げないため、bbox 述語を明示して初めて刈れる（naive な空間検索は刈れない）。
    """
    src = f"read_parquet('{url}')"
    x0, y0, x1, y1 = _BBOX
    envelope = f"ST_MakeEnvelope({x0}, {y0}, {x1}, {y1})"
    probes = [
        Probe("count(*) 全件", f"SELECT count(*) FROM {src}"),
        Probe("road_type 別count", f"SELECT road_type, count(*) FROM {src} GROUP BY road_type"),
        Probe(
            "bbox内count(ST_Intersects)",
            f"SELECT count(*) FROM {src} WHERE ST_Intersects(geometry, {envelope})",
        ),
    ]
    if bbox_covering:
        # covering 列（struct bbox）への明示述語。これが row-group を刈る（統計で安く）。
        bbox_pred = (
            f"bbox.xmin <= {x1} AND bbox.xmax >= {x0} "
            f"AND bbox.ymin <= {y1} AND bbox.ymax >= {y0}"
        )
        probes += [
            Probe("bbox述語のみ(候補)", f"SELECT count(*) FROM {src} WHERE {bbox_pred}"),
            Probe(
                "bbox述語 AND ST_Intersects",
                f"SELECT count(*) FROM {src} "
                f"WHERE {bbox_pred} AND ST_Intersects(geometry, {envelope})",
            ),
        ]
    return probes


def _run_probe(region: str, probe: Probe) -> tuple[list[tuple], list[str]]:
    """新しい接続で1問を実行し、(結果行, HTTPログ message 一覧) を返す。

    ログを問い単位で綺麗に切り分けるため、接続を都度作り直す（DuckDB の
    ``duckdb_logs`` は接続内メモリに溜まるので、新接続 = まっさらなログ）。
    """
    con = duckdb.connect()
    try:
        # 進捗バーは stdout を大量のフレームで埋めるので抑止（レポートを読みやすく保つ）。
        con.execute("SET enable_progress_bar = false")
        for stmt in ("INSTALL httpfs", "LOAD httpfs", "INSTALL spatial", "LOAD spatial"):
            con.execute(stmt)
        # region は固定値（引数）。CREATE SECRET は識別子バインドを取らないため直接埋める。
        con.execute(
            "CREATE OR REPLACE SECRET s3_secret "
            f"(TYPE S3, PROVIDER 'credential_chain', REGION '{region}')"
        )
        # ここから下だけをログ対象に（拡張 DL・secret 生成を混ぜない）。
        con.execute("CALL enable_logging('HTTP')")
        rows = con.execute(probe.sql).fetchall()
        messages = [
            m
            for (m,) in con.execute(
                "SELECT message FROM duckdb_logs WHERE type = 'HTTP'"
            ).fetchall()
        ]
        return rows, messages
    finally:
        con.close()


def _result_str(rows: list[tuple]) -> str:
    """結果を1セルの短い文字列に。単一値ならその値、複数行なら行数。"""
    if len(rows) == 1 and len(rows[0]) == 1:
        return f"{rows[0][0]:,}"
    return f"{len(rows)}行"


def _fmt_mb(n: int | None) -> str:
    return "?" if n is None else f"{n / 1e6:.2f} MB"


def main() -> None:
    parser = argparse.ArgumentParser(description="S3 GeoParquet の Range GET 転送量を測る")
    parser.add_argument("--s3-url", default=_DEFAULT_S3_URL, help="対象 parquet の s3:// URL")
    parser.add_argument("--region", default=_DEFAULT_REGION, help="バケットのリージョン")
    parser.add_argument(
        "--bbox-covering",
        action="store_true",
        help="bbox covering 列を持つファイル向けに、bbox 述語版の問いも測る",
    )
    args = parser.parse_args()

    print(f"対象   : {args.s3_url}")
    print(f"region : {args.region}\n")
    header = f"{'問い':<28}{'結果':>12}{'GET数':>7}{'転送量':>12}{'割合':>8}"
    print(header)
    print("-" * 67)

    full_size: int | None = None
    for probe in _probes(args.s3_url, bbox_covering=args.bbox_covering):
        rows, messages = _run_probe(args.region, probe)
        summ = summarize_transfer(messages)
        if summ.full_size:
            full_size = summ.full_size
        frac = f"{summ.fraction * 100:.1f}%" if summ.fraction is not None else "?"
        print(
            f"{probe.label:<28}{_result_str(rows):>12}{summ.n_get:>7}"
            f"{_fmt_mb(summ.get_bytes):>12}{frac:>8}"
        )

    if full_size:
        print(f"\nファイル全体: {_fmt_mb(full_size)}（HEAD 応答の Content-Length）")


if __name__ == "__main__":
    main()
