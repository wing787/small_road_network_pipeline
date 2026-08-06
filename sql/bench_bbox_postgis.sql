-- ベンチ(問い3/PostGIS版): 東京駅周辺 bbox 内の道路の件数と総延長(測地線, m)。
--   docs/postgis-vs-duckdb.md 参照。GIST 索引で対象(全体の0.52%)だけ触る。
--   EXPLAIN (ANALYZE, BUFFERS) を付けると Bitmap Index Scan on roads_geometry_gist が確認できる。
--   実行: docker compose exec -T postgis psql -U roadnet -d roadnet < sql/bench_bbox_postgis.sql
SELECT COUNT(*), SUM(ST_Length(geometry::geography, use_spheroid => false)) AS total_length_m
FROM roads
WHERE ST_Intersects(geometry, ST_MakeEnvelope(139.75, 35.66, 139.79, 35.70, 4326));