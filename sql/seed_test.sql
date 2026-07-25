-- 動作確認用の使い捨てテストデータ（本番投入では使わない）。
-- roads_stage（6668・緩い型）に生データを模した3行を入れる。
-- コードはすべて文字列（生データ同様）。ジオメトリは日本国内の 6668 座標。
--
-- 使い方: schema.sql 適用後にこのファイルを流し、その後 transform.sql を実行する。
--   psql ... -f sql/schema.sql
--   psql ... -f sql/seed_test.sql
--   psql ... -f sql/transform.sql

-- 何度流しても同じ状態になるよう、先に空にする。
TRUNCATE roads_stage;

INSERT INTO roads_stage (
    road_type, road_classification, road_status, width_category, toll_category,
    registration_date, layer_order, source_mesh, secondary_mesh_code, geometry
)
VALUES
    -- 東京付近
    ('1', '1', '1', '3', '2', '2024-09-01', 0, '5339', '533946',
     ST_GeomFromText('LINESTRING(139.70 35.65, 139.72 35.66)', 6668)),
    -- 大阪付近
    ('3', '2', '2', '2', '1', '2024-09-01', 1, '5235', '523504',
     ST_GeomFromText('LINESTRING(135.50 34.69, 135.52 34.70)', 6668)),
    -- 名古屋付近
    ('2', '3', '3', '4', '2', '2024-09-01', 0, '5236', '523637',
     ST_GeomFromText('LINESTRING(136.90 35.18, 136.92 35.19)', 6668));
