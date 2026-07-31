-- ウィンドウ関数・CTE による集計クエリ集
-- 題材: 国土数値情報 N13-2024 道路データ（roads 本体, 1,439 行 / 3メッシュ）
-- 共通パターン: CTE で「素の集計」(GROUP BY) を確定 → 上段で窓関数を1個かける二段構え
-- CRS 注意: geometry は EPSG:4326（度）。総延長[m]は geometry::geography にキャストして
--           ST_Length（測地線・メートル）で測る。度のまま ST_Length すると無意味な値になる。
-- 型注意: round(値, 桁) の2引数版は round(numeric, int) のみ。double precision を返す
--         ST_Length の集計は ::numeric にキャストしてから round する。
-- 実行例: docker compose exec -T postgis psql -U roadnet -d roadnet -f sql/analysis_window.sql

-- 1) RANK / PARTITION BY: メッシュ内で道路種別ごとの件数・総延長を出し、総延長で順位付け
--    RANK() OVER (PARTITION BY ... ORDER BY ...) はパーティション（メッシュ）ごとに順位を振り直す。
WITH agg AS (
    SELECT
        r.source_mesh,
        rt.label AS road_type_label,
        count(*) AS n,
        sum(ST_Length(r.geometry::geography))  AS total_len_m   -- 総延長[m]（測地線）
    FROM roads r
    JOIN road_type rt ON r.road_type = rt.code                  -- コード→ラベルのデコード
    GROUP BY r.source_mesh, rt.label
)
SELECT
    source_mesh,
    road_type_label,
    n,
    round(total_len_m::numeric, 1) AS total_len_m,
    RANK() OVER (PARTITION BY source_mesh ORDER BY total_len_m DESC) AS len_rank
FROM agg
ORDER BY source_mesh, len_rank;

-- 2) SUM() OVER (): 道路分類ごとの件数・総延長に、全体に占める割合を付ける
--    OVER () は空フレーム＝全行合計。sum(...) OVER () を分母にして構成比を出す。
--    n_pct の分母は count(*) OVER () ではなく sum(n) OVER ()（＝件数の合計）である点に注意。
WITH agg AS (
    SELECT
        rc.label AS road_class_label,
        count(*) AS n,
        sum(ST_Length(r.geometry::geography)) AS total_len_m
    FROM roads r
    JOIN road_classification rc ON r.road_classification = rc.code
    GROUP BY rc.label
)
SELECT
    road_class_label,
    n,
    round(total_len_m::numeric, 1) AS total_len_m,
    round((100.0 * total_len_m / sum(total_len_m) OVER ())::numeric, 1) AS len_pct,  -- 総延長の構成比[%]
    round(100.0 * n / sum(n) OVER (), 1) AS n_pct                                    -- 件数の構成比[%]
FROM agg
ORDER BY total_len_m DESC;

-- 3) 累積 SUM() OVER (PARTITION BY ... ORDER BY ...): メッシュ内で幅員ごとの累積総延長
--    窓に ORDER BY を入れるとデフォルトフレームが「先頭〜現在行」になり、累積になる。
--    並び順は width_label（文字列）ではなく width_code（数値）で。文字列ソートだと
--    '3m-5.5m未満' < '3m未満' となり幅員の大小と食い違う（累積の順序が狂う）。
--    最後の ORDER BY は表示順であって累積計算の順序には効かない（窓の ORDER BY だけが決める）。
WITH agg AS (
    SELECT
        r.source_mesh,
        wc.code AS width_code,          -- 累積の並び順に使う（label でなく code）
        wc.label AS width_label,
        count(*)                              AS n,
        sum(ST_Length(r.geometry::geography)) AS total_len_m
    FROM roads r
    JOIN width_category wc ON r.width_category = wc.code
    GROUP BY r.source_mesh, wc.code, wc.label
)
SELECT
    source_mesh,
    width_label,
    n,
    round(total_len_m::numeric, 1) AS total_len_m,
    round(sum(total_len_m) OVER (PARTITION BY source_mesh ORDER BY width_code)::numeric, 1) AS cum_len_m  -- 累積総延長[m]
FROM agg
ORDER BY source_mesh, width_code;
