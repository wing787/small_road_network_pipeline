# PostGIS vs DuckDB(spatial) ベンチマーク

同じ道路データ(194万件)に対し、同じ問いを **PostGIS** と **DuckDB(spatial 拡張)** の
両方で書き、**書き味**と**実行時間**を比較した記録。M3(クラウドネイティブGIS)の一環。

## 目的・データ

- 「数百万件を1台で捌く現実解」としての DuckDB を、成熟した空間DBの PostGIS と対比し、
  **どちらがどの用途に向くか**を実測で見極める(M6「分散処理が要るか」判断の物差し)。
- データ: 国土数値情報 N13-2024 道路、1次メッシュ 5339(東京都心)+ 南西諸島の離島。
  合計 **1,944,690 行**(LINESTRING)。
  - PostGIS: `roads` テーブル(`GEOMETRY(LINESTRING, 4326)`, GIST 索引あり)
  - DuckDB: `data/output/roads_all.parquet`(GeoParquet, WKB, CRS=**EPSG:6668**)を直読
- クエリは `sql/bench_*.sql`(PostGIS 版 / DuckDB 版を別ファイルで対にした)。

## 3つの問いと結果

計測は**ウォーム(キャッシュ温め後)の最良値**。実行時間はノイズが大きいので**桁**で読む。

### 問い1: 純粋な属性集計 — `count(*) by road_type`

ジオメトリを触らない素の集計。DuckDB の列指向スキャンの本領。

| エンジン | 時間 | 方式 |
|---|---|---|
| **DuckDB** | **~7 ms** | parquet 直読 + 列指向集計 |
| PostGIS | ~100 ms | Seq Scan + 集約 |

→ 全件を舐める集計は **DuckDB が約14倍速い**。194万件のファイルをその場で数ミリ秒。

### 問い2: 測地線での総延長 — `SUM(length) by road_type`

CRS が度(4326/6668)なので、長さは球面/楕円体で測る必要がある。

| エンジン | 書き方 | 時間 | 結果(通常部, m) |
|---|---|---|---|
| **PostGIS** | `ST_Length(geometry::geography, use_spheroid => false)` — **ワンライナー** | ~1.1 s | 97,202,622 |
| **DuckDB** | 頂点分解 + `ST_Distance_Sphere` 合算 + 座標flip — **4段CTE** | ~2.2 s | 97,202,488 |

- 両者 **6桁一致**(全 road_type で差 <0.001%)。同じ球面モデルに揃えた(PostGIS も `use_spheroid => false`)。
- **書き味は PostGIS 圧勝**。`geography` 型が測地線長をワンライナーで返すのに対し、
  DuckDB は測地線長の関数(`ST_Length_Spheroid` 系)が**このビルド(1.5.5)で壊れており全て NaN を返す**ため、
  「線を頂点に分解 → 隣接2点の `ST_Distance_Sphere` を合算」という自前実装が必要(下記「教訓」参照)。
- 時間も DuckDB が遅いが、これは**エンジンの地力ではなく壊れた関数の回避コスト**(頂点を数千万行に展開する)。
  関数が正常なら DuckDB が勝つ可能性は高い。**この数字を「DuckDBは集計が遅い」と読むのは誤り**(問い1が反証)。

### 問い3: 選択的な空間検索 — bbox 内の件数

`ST_MakeEnvelope(139.75, 35.66, 139.79, 35.70)`(東京駅周辺 ~4km四方、全体の **0.52% = 10,172件**)。
空間索引が効くかどうかの勝負。

| 方式 | 時間 | 走査 |
|---|---|---|
| **DuckDB + RTREE 索引** | **~7 ms** | `RTREE_INDEX_SCAN`(候補に絞る) |
| PostGIS + GIST 索引 | ~11 ms | Bitmap Index Scan(Buffers 1,317ページ) |
| DuckDB 素の全表スキャン | ~132 ms | 194万行に述語評価(索引無効化時) |
| DuckDB parquet 直読スキャン | ~214 ms | ファイル全読み + 述語評価 |

- **索引があれば DuckDB(RTREE) と PostGIS(GIST) は互角**(むしろ DuckDB がやや速い)。
- **索引が無いと DuckDB は10〜30倍遅い**。parquet 直読は永続索引を持てないため、194万行を全スキャンして
  1行ずつ `ST_Intersects` を評価する(GeoParquet に bbox covering 列が無く、行グループ枝刈りも効かない)。

## 結論: 用途で選ぶ(3すくみのトレードオフ)

| 用途 | 向くエンジン/方式 | 理由 |
|---|---|---|
| 全件集計・スキャン | **DuckDB 直読** | 列指向で数百万件を数ms〜数百ms。ファイルをその場で叩ける |
| 選択的な空間検索 | **PostGIS(GIST)** or **DuckDB(RTREE)** | 永続空間索引で対象だけ触る |
| 測地線などの空間関数の成熟度 | **PostGIS** | `geography` 等が揃う。DuckDB spatial は発展途上(壊れた関数あり) |

**核心のトレードオフ**: DuckDB は「**ファイル直読の手軽さ**」と「**索引検索の速さ**」を**同時には得られない**。
生の GeoParquet には RTREE を張れず(索引は永続テーブルにのみ作成可)、選択検索を速くしたいなら
`CREATE TABLE ... AS SELECT ... FROM read_parquet(...)` で取り込んで索引を張る(= PostGIS と同じ発想。
"S3上のファイルをその場で"の利点は手放す)。全件集計主体なら直読、選択検索主体なら索引化、で選ぶ。

数百万件規模ではどちらも1台で十分。**分散処理(M6)を持ち出す前に、この2つで足りるかをまず疑うべき**。

## 教訓(ハマった罠)

### 1. 「基準値に近い ≠ 正しい」— 座標順の偽陽性

DuckDB の `ST_Distance_Sphere` は座標を **(緯度, 経度) 順**で読む(WKT/GeoParquet の (経度, 緯度) と逆)。
これに気づかず素直に渡すと、総延長が PostGIS と **~1% しかズレず、一見"検証パス"してしまう**。
近かったのは東京の偶然(緯度35°・経度139°で `cos(35°)=0.819` と `|cos(139°)|=0.755` が近く、
経度緯度を入れ替えても1本ごとの誤差が小さく、向きバラバラの道路で相殺された)。
**road_type ごとに誤差が 0.34〜1.43% とバラついた違和感**が発見の糸口。
→ 修正: 読み込み時に `ST_FlipCoordinates(geometry)` で反転。すると PostGIS と6桁一致。
一方 `ST_Intersects`(問い3)は**デカルトXY判定**なので flip 不要 — **flip はデータの性質でなく関数の都合**。

### 2. 「プランのラベル ≠ 実測」— EXPLAIN ANALYZE の表示クセ

RTREE 索引使用時、**`EXPLAIN`(plain)は `RTREE_INDEX_SCAN`** と出すが、
**`EXPLAIN ANALYZE`(実行版)は `TABLE_SCAN`** と表示する(DuckDB 1.5.5 の表示クセ)。
ラベルだけ見ると索引が効いていないように誤読する。しかし**時間が真実を語る**:
索引あり ~7ms vs 索引無効化した全表スキャン ~132ms(対照実験: `ST_FlipCoordinates` 二重掛け=恒等変換で
索引を回避して計測)。約16倍差 = 索引は確かに効いている。

### 3. 時間はノイズ、桁で読む

`spatial-index-benchmark.md` / `partition-pruning.md` と同じ。実行時間は run ごとに揺れるので
ウォーム最良値の**桁**で判断し、可能なら Buffers/走査量など物理量を併読する。

## 再現コマンド

```bash
# 前提: roads(194万件)が PostGIS に、roads_all.parquet が data/output/ にある
#       (docs/partition-pruning.md の手順でメッシュ5339を投入済み)

# --- 問い2: 総延長 ---
docker compose exec -T postgis psql -U roadnet -d roadnet < sql/bench_length_postgis.sql
uv run python -c "import duckdb; print(duckdb.sql(open('sql/bench_length_duckdb.sql').read()))"

# --- 問い3: bbox 検索 ---
docker compose exec -T postgis psql -U roadnet -d roadnet < sql/bench_bbox_postgis.sql
uv run python -c "import duckdb; print(duckdb.sql(open('sql/bench_bbox_duckdb.sql').read()))"

# --- 問い3: DuckDB + RTREE(永続DBにテーブル化+索引) ---
uv run python -c "import duckdb; con=duckdb.connect('data/roads.duckdb'); \
  con.execute('INSTALL spatial;LOAD spatial;'); \
  print(con.execute(open('sql/bench_bbox_duckdb_rtree.sql').read()).fetchall()[0][1])"
# 索引が使われる証拠は EXPLAIN(plain) の RTREE_INDEX_SCAN で見る(ANALYZE は TABLE_SCAN と誤表示)
```
