# 空間索引(GIST)ベンチマーク

`roads.geometry`(`GEOMETRY(LINESTRING, 4326)`)に対する GIST 索引の効果を
`EXPLAIN (ANALYZE, BUFFERS)` で計測した記録。

## 計測条件

- データ: 国土数値情報 N13-2024 道路データ、3メッシュ分 **1,439 行**(南西諸島: 与那国〜石垣〜大東)
- クエリ: bbox 重なり述語 `geometry && ST_MakeEnvelope(..., 4326)` による件数集計
- 「索引あり」= `roads_geometry_gist` 存在時にプランナが**自発的に**選んだプラン(`enable_seqscan` 等の強制なし)
- 「索引なし」= `DROP INDEX roads_geometry_gist` 後に同一クエリを実行
- PostGIS / PostgreSQL(compose の `postgis` サービス)

## 結果1: 選択的なクエリ(131 行ヒット ≒ 全体の 9%)

矩形 `ST_MakeEnvelope(122.95, 24.44, 123, 24.45, 4326)`

| | 索引あり(自然選択) | 索引なし(DROP後) |
|---|---|---|
| プラン | **Bitmap Index Scan** on `roads_geometry_gist` | **Seq Scan** |
| 推定総コスト | **45.28** | 56.33 |
| Buffers (shared hit) | **18** | 38 |
| Rows Removed by Filter | — | 1,308 |
| 実測 Execution Time | 0.193 ms | 0.265 ms |

- プランナは索引ありのとき **45.28 < 56.33** なので自分で Bitmap を選んだ
- **最も信頼できる改善指標は Buffers(18 vs 38)**: 索引ありは触るページ数が約半分。実測時間と違いノイズに揺れない物理量で、索引が I/O を実際に削っている
- 索引なしの `Rows Removed by Filter: 1308` = 全 1,439 行を読んで 1,308 行を捨てている。索引ありはビットマップで先に絞り、ヒープでは 131 行のみ参照

## 結果2: 非選択的なクエリ(800 行ヒット ≒ 全体の 56%)

矩形 `ST_MakeEnvelope(122.934519822, 24.4384843, 123, 24.47269584, 4326)`

- プランナは索引があっても **Seq Scan を選択**(推定コスト Seq 57.82 < 索引強制 74.82)
- 過半数を返すクエリでは、索引で絞ってもヒープのほとんどのページを触るため索引経由が割高になる

## 結論

- **「GIST があれば速い」ではなく「返す割合が小さいときに効く」**。同じ索引・同じテーブルでも、選択率 9% ではプランナが索引を選び、56% では Seq を選ぶ
- 1,439 行では実測時間差は 0.19 vs 0.27 ms とほぼ誤差。**この構造的な差(コスト・Buffers・捨てる行数)が桁で効いてくるのは数百万件規模から**。小規模データで索引の実速度差が出ないのは正常で、索引を張らない理由にはならない
- 索引が使われているかは実行時間でなく **プランの走査方法(Seq Scan / Bitmap Index Scan)と Buffers** で判断する

## 再現コマンド

```bash
# 索引あり(素の状態でプランナに選ばせる)
docker compose exec -T postgis psql -U roadnet -d roadnet \
  -c "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM roads
      WHERE geometry && ST_MakeEnvelope(122.95, 24.44, 123, 24.45, 4326);"

# 索引なし(DROP して同一クエリ)
docker compose exec -T postgis psql -U roadnet -d roadnet \
  -c "DROP INDEX roads_geometry_gist;
      EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM roads
      WHERE geometry && ST_MakeEnvelope(122.95, 24.44, 123, 24.45, 4326);"

# 索引を復旧
docker compose exec -T postgis psql -U roadnet -d roadnet \
  -c "CREATE INDEX roads_geometry_gist ON roads USING GIST (geometry);"
```
