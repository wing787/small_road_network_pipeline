-- ベンチ(問い3/DuckDB版, 索引なし): 東京駅周辺 bbox 内の道路の件数と総延長(測地線, m)。
--   docs/postgis-vs-duckdb.md 参照。read_parquet の直読には永続索引が無く、194万行を全スキャンする。
--   住み分け: bbox フィルタ(ST_Intersects)はデカルトXY判定なので flip 前の生 geometry で判定。
--             測地線長の ST_Distance_Sphere だけは (緯度,経度) を要求するので flip 済み geom_ll を使う。
--   実行: uv run python -c "import duckdb; print(duckdb.sql(open('sql/bench_bbox_duckdb.sql').read()))"
INSTALL spatial; LOAD spatial;

WITH lines AS (
    -- bbox で絞る(WHERE は生 geometry)。line_id と、長さ計算用に flip した座標(geom_ll)を射影
    SELECT row_number() OVER () AS line_id,
           ST_FlipCoordinates(geometry) AS geom_ll
    FROM read_parquet('data/output/roads_all.parquet')
    WHERE ST_Intersects(geometry, ST_MakeEnvelope(139.75, 35.66, 139.79, 35.70))
),
verts AS (
    -- 絞られた道路だけを頂点に展開(上限排他なので +1)
    SELECT l.line_id, v.i, ST_PointN(geom_ll, v.i::INTEGER) AS pt
    FROM lines l, range(1, ST_NumPoints(geom_ll) + 1) AS v(i)
),
segments AS (
    -- 隣接頂点間の距離。最後の頂点は lead が NULL → SUM が無視
    SELECT line_id,
           ST_Distance_Sphere(pt, lead(pt) OVER (PARTITION BY line_id ORDER BY i)) AS seg_len
    FROM verts
)
-- segments は1本が複数行なので、本数は DISTINCT line_id で数える
SELECT COUNT(DISTINCT line_id) AS cnt, SUM(seg_len) AS total_length_m
FROM segments;
