-- ベンチ(問い3/DuckDB版, RTREE索引あり): 索引を張れば選択検索が PostGIS(GIST) と互角以上か検証。
--   docs/postgis-vs-duckdb.md 参照。RTREE 索引は永続テーブルにしか張れないので、
--   parquet を一旦テーブルへ取り込む(= "ファイル直読" の手軽さは手放す代わりに索引検索が速くなる)。
--   索引使用の証拠は EXPLAIN(plain) の RTREE_INDEX_SCAN で見る(EXPLAIN ANALYZE は TABLE_SCAN と誤表示)。
--   実行(永続DBに対して):
--     uv run python -c "import duckdb; con=duckdb.connect('data/roads.duckdb'); \
--       con.execute('INSTALL spatial;LOAD spatial;'); \
--       print(con.execute(open('sql/bench_bbox_duckdb_rtree.sql').read()).fetchall()[0][1])"
INSTALL spatial; LOAD spatial;

-- 1) parquet をテーブル化(索引を張る土台)
CREATE OR REPLACE TABLE roads AS (
    SELECT road_type, geometry
    FROM read_parquet('data/output/roads_all.parquet')
);

-- 2) geometry に RTREE 索引を張る
CREATE INDEX roads_geom_rtree ON roads USING RTREE (geometry);

-- 3) bbox 検索(フィルタは flip 不要 = デカルトXY判定)。索引が候補に絞り、ST_Intersects で精査
EXPLAIN ANALYZE
SELECT count(*)
FROM roads
WHERE ST_Intersects(geometry, ST_MakeEnvelope(139.75, 35.66, 139.79, 35.70));
