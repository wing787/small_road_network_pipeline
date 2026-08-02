-- パーティショニング検証（M2）: roads を都道府県で LIST パーティション化した実験用テーブル。
--   目的: partition pruning の効果を EXPLAIN で測る（docs/partition-pruning.md 参照）。
--   roads 本体（非パーティション）はベースラインとして温存し、ここは別テーブルで実験する。
--   pref_code は roads には無く、admin_area(N03) との空間結合で導出する（→ partition_load.sql）。
--   実行（DDL・一度だけ）:
--     docker compose exec -T postgis psql -U roadnet -d roadnet < sql/partition.sql

-- 親テーブル: 自身はデータを持たず、pref_code で子へ振り分けるだけ
CREATE TABLE roads_p (
    fid BIGINT, -- IDENTITY は付けない（roads の値をコピーする）
    road_type SMALLINT REFERENCES road_type(code) NOT NULL,
    road_classification SMALLINT REFERENCES road_classification(code) NOT NULL,
    road_status SMALLINT REFERENCES road_status(code) NOT NULL,
    width_category SMALLINT REFERENCES width_category(code) NOT NULL,
    toll_category SMALLINT REFERENCES toll_category(code) NOT NULL,
    registration_date DATE NOT NULL,
    layer_order SMALLINT NOT NULL,
    source_mesh TEXT,
    secondary_mesh_code TEXT,

    geometry GEOMETRY(LINESTRING, 4326) NOT NULL,
    pref_code TEXT, -- パーティションキー。PK に含めるので NULL 不可（INNER JOIN で 11-14 のみ投入）
    PRIMARY KEY (fid, pref_code) -- キーを含む複合PK
) PARTITION BY LIST (pref_code);

-- 子パーティション: 1県ぶんの型。
CREATE TABLE roads_p_13 PARTITION OF roads_p FOR VALUES IN ('13');
CREATE TABLE roads_p_11 PARTITION OF roads_p FOR VALUES IN ('11');
CREATE TABLE roads_p_12 PARTITION OF roads_p FOR VALUES IN ('12');
CREATE TABLE roads_p_14 PARTITION OF roads_p FOR VALUES IN ('14');

-- 明示した県（11-14）以外の受け皿。今回は INNER JOIN なので空（将来の未知県が来ても落ちない保険）
CREATE TABLE roads_p_default PARTITION OF roads_p DEFAULT;

-- 測定の公平性のため GIST を張り直す（親に作れば全子へ伝播）
CREATE INDEX roads_p_geometry_gist ON roads_p USING GIST (geometry);