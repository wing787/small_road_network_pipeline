-- staging table to prod table
INSERT INTO roads (road_type, road_classification, road_status, width_category, toll_category, registration_date, layer_order, source_mesh, secondary_mesh_code, geometry)
SELECT
    road_type::SMALLINT,
    road_classification::SMALLINT,
    road_status::SMALLINT,
    width_category::SMALLINT,
    toll_category::SMALLINT,
    registration_date::DATE,
    layer_order::SMALLINT,
    source_mesh,
    secondary_mesh_code,
    ST_Transform(geometry, 4326)
FROM roads_stage;