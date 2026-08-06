-- ベンチ(問い2/DuckDB版): road_type 別の総延長(測地線, m)。docs/postgis-vs-duckdb.md 参照。
--   DuckDB spatial の測地線長関数(ST_Length_Spheroid 系)は 1.5.5 で壊れている(全て NaN)ため、
--   線を頂点に分解し隣接2点の ST_Distance_Sphere を合算して自前実装する。
--   注意: ST_Distance_Sphere は座標を (緯度,経度) 順で読む → 読み込み時に ST_FlipCoordinates で反転。
--   実行: uv run python -c "import duckdb; print(duckdb.sql(open('sql/bench_length_duckdb.sql').read()))"
INSTALL spatial; LOAD spatial;

WITH lines AS (
    -- 各線に一意ID(line_id)を振り、長さ計算用に座標を (緯度,経度) へ反転
    SELECT row_number() OVER () AS line_id, road_type, ST_FlipCoordinates(geometry) AS geometry
    FROM read_parquet('data/output/roads_all.parquet')
),
verts AS (
    -- 各線を頂点の行に展開(range を相関カンマ結合。上限排他なので +1)
    SELECT l.line_id, l.road_type, v.i, ST_PointN(l.geometry, v.i::INTEGER) AS pt
    FROM lines l, range(1, ST_NPoints(l.geometry) + 1) AS v(i)
),
segments AS (
    -- 線ごと・頂点順に「次の頂点」との距離。最後の頂点は lead が NULL → SUM が無視
    SELECT line_id, road_type,
           ST_Distance_Sphere(pt, lead(pt) OVER (PARTITION BY line_id ORDER BY i)) AS seg_len
    FROM verts
)
SELECT road_type, SUM(seg_len) AS total_length_m
FROM segments
GROUP BY road_type
ORDER BY total_length_m DESC;
