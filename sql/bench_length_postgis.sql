-- ベンチ(問い2/PostGIS版): road_type 別の総延長(測地線, m)。docs/postgis-vs-duckdb.md 参照。
--   geography 型の ST_Length がワンライナーで測地線長を返す(DuckDB 版の4段CTEと対比)。
--   DuckDB は球面(ST_Distance_Sphere)しか使えないので、公平のため use_spheroid => false で球面に揃える。
--   実行: docker compose exec -T postgis psql -U roadnet -d roadnet < sql/bench_length_postgis.sql
SELECT
    rt.label AS road_type,
    SUM(ST_Length(geometry::geography, use_spheroid => false)) AS total_length_m
FROM roads r
JOIN road_type rt ON r.road_type = rt.code
GROUP BY rt.label
ORDER BY total_length_m DESC;