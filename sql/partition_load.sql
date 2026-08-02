-- roads_p へのデータ投入（一度だけ）。roads を admin_area(N03) と空間結合して
-- pref_code を導出し、宣言的パーティショニングで各県の子へ自動振り分けする。
--   前提: sql/partition.sql（DDL）と scripts/load_admin_area.py（admin_area 投入）が済んでいること。
--   (b) INNER JOIN: 代表点がどの県ポリゴンにも含まれない道路（離島・県外・海面）は落とす。
--   冪等性: 複合PK (fid, pref_code) があるため再実行は PK 衝突で全ロールバック＝二重投入されない。
--   実行:
--     docker compose exec -T postgis psql -U roadnet -d roadnet < sql/partition_load.sql
INSERT INTO roads_p (
    fid, road_type, road_classification, road_status, width_category,
    toll_category, registration_date, layer_order, source_mesh,
    secondary_mesh_code, geometry, pref_code
)
SELECT
    r.fid,
    r.road_type,
    r.road_classification,
    r.road_status,
    r.width_category,
    r.toll_category,
    r.registration_date,
    r.layer_order,
    r.source_mesh,
    r.secondary_mesh_code,
    r.geometry,
    left(a.admin_code, 2) as pref_code
FROM roads r
JOIN admin_area a ON ST_Contains(a.geometry, ST_PointOnSurface(r.geometry));