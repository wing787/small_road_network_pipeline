CREATE EXTENSION IF NOT EXISTS postgis;

-- コードテーブル
-- 種別（N13_002）
CREATE TABLE IF NOT EXISTS road_type (
    code SMALLINT NOT NULL PRIMARY KEY,
    label TEXT NOT NULL
);

INSERT INTO road_type (code, label)
    VALUES (1, '通常部'), (2, '庭園路'), (3, '徒歩道'), (4, '石段'), (5, '不明')
    ON CONFLICT (code)
    DO UPDATE SET 
    label = EXCLUDED.label;

-- 道路分類（N13_003）
CREATE TABLE IF NOT EXISTS road_classification (
    code SMALLINT NOT NULL PRIMARY KEY,
    label TEXT NOT NULL
);

INSERT INTO road_classification (code, label)
    VALUES (1, '国道'), (2, '都道府県道'), (3, '市区町村道等'), (4, '高速自動車国道等'), (5, 'その他'), (6, '不明')
    ON CONFLICT (code)
    DO UPDATE SET 
    label = EXCLUDED.label;

-- 道路状態（N13_004）
CREATE TABLE IF NOT EXISTS road_status (
    code SMALLINT NOT NULL PRIMARY KEY,
    label TEXT NOT NULL
);

INSERT INTO road_status (code, label)
    VALUES (1, '通常部'), (2, '橋・高架'), (3, 'トンネル'), (4, '雪囲い'), (5, '建設中'), (6, 'その他'), (7, '不明')
    ON CONFLICT (code)
    DO UPDATE SET 
    label = EXCLUDED.label;

-- 幅員区分（N13_006）
CREATE TABLE IF NOT EXISTS width_category (
    code SMALLINT NOT NULL PRIMARY KEY,
    label TEXT NOT NULL
);

INSERT INTO width_category (code, label)
    VALUES (1, '3m未満'), (2, '3m-5.5m未満'), (3, '5.5m-13m未満'), (4, '13m-19.5m未満'), (5, '19.5m以上'), (6, '不明')
    ON CONFLICT (code)
    DO UPDATE SET 
    label = EXCLUDED.label;

-- 有料区分（N13_007）
CREATE TABLE IF NOT EXISTS toll_category (
    code SMALLINT NOT NULL PRIMARY KEY,
    label TEXT NOT NULL
);

INSERT INTO toll_category (code, label)
    VALUES (1, '有料'), (2, '無料')
    ON CONFLICT (code)
    DO UPDATE SET 
    label = EXCLUDED.label;

-- for staging
CREATE TABLE IF NOT EXISTS roads_stage (
    road_type TEXT,
    road_classification TEXT,
    road_status TEXT,
    width_category TEXT,
    toll_category TEXT,
    registration_date TIMESTAMP,
    layer_order INTEGER,
    source_mesh TEXT,
    secondary_mesh_code TEXT,
    geometry GEOMETRY(LINESTRING, 6668) NOT NULL
);

-- 道路データ本体
CREATE TABLE IF NOT EXISTS roads (
    fid BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    road_type SMALLINT REFERENCES road_type(code) NOT NULL,
    road_classification SMALLINT REFERENCES road_classification(code) NOT NULL,
    road_status SMALLINT REFERENCES road_status(code) NOT NULL,
    width_category SMALLINT REFERENCES width_category(code) NOT NULL,
    toll_category SMALLINT REFERENCES toll_category(code) NOT NULL,
    registration_date DATE NOT NULL,
    layer_order SMALLINT NOT NULL,
    source_mesh TEXT,
    secondary_mesh_code TEXT,
    geometry GEOMETRY(LINESTRING, 4326) NOT NULL
);