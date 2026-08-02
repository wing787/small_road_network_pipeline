# パーティション pruning ベンチマーク

`roads` を都道府県で LIST パーティション化した `roads_p` に対し、
`EXPLAIN (ANALYZE, BUFFERS)` で **partition pruning（不要パーティションの読み飛ばし）** の
効果を計測した記録。

## 背景・データ

- 効果を測るには実務スケールの件数が要るため、題材メッシュを**南西諸島の離島（1,439行）から
  1次メッシュ 5339（東京都心, **1,943,251 行**）へ拡張**した。roads 合計 **1,944,690 行**。
- 都道府県は N13 の属性に無い。**N03-2026 行政区域（4県: 埼玉/千葉/東京/神奈川, EPSG:6668→4326）**
  を `admin_area`（10,543 ポリゴン, MULTIPOLYGON, GIST）に投入し（`scripts/load_admin_area.py`）、
  空間結合で導出する。
- パーティションキー `pref_code` = `left(admin_code, 2)`（全国地方公共団体コードの先頭2桁）。

## 構築

- DDL: `sql/partition.sql` — `roads_p` を `PARTITION BY LIST (pref_code)`。
  子は県ごと（`roads_p_11/12/13/14`）＋ `roads_p_default`。
  - 罠1: **パーティションキーは PK に含める必要** → `PRIMARY KEY (fid, pref_code)`。
  - 罠2: **既存テーブルはその場でパーティション化できない** → 新テーブルを作り `INSERT SELECT` で移す。
    roads（非パーティション）はベースラインとして温存。
  - 公平性: `roads` の GIST に合わせ `roads_p` にも GIST を張る（親に作れば全子へ伝播）。
- 投入: `sql/partition_load.sql` — `roads ⋈ admin_area` の INNER JOIN。
  結合述語は `ST_Contains(a.geometry, ST_PointOnSurface(r.geometry))`（**代表点 in ポリゴン**で
  1道路=1県に確定。境界重複を避ける）。

### 投入結果（県別件数）

| pref_code | 県 | 件数 |
|---|---|---|
| 11 | 埼玉 | 529,028 |
| 12 | 千葉 | 173,863 |
| 13 | 東京 | 702,205 |
| 14 | 神奈川 | 516,471 |
| default | （11-14以外） | 0 |
| **計** | | **1,921,567** |

- roads 全体 1,944,690 との差 ≈ 23,000 行は INNER JOIN で落ちた分（離島 1,439 ＋ メッシュ5339の
  県外にかすった道路・海面/橋で代表点がどのポリゴンにも入らない道路）。**想定通りの減り方**。
- 千葉が極端に少ないのは 5339 が千葉の西端しか含まないため。東京>埼玉>神奈川>千葉の順は
  地理的に妥当＝空間結合が正しく効いている傍証。

## 計測: 読むパーティション数と Buffers

`count(*)` を、絞り込み条件を変えて `EXPLAIN (ANALYZE, BUFFERS)` で計測。

| クエリ | 読まれた子 | プラン形 | Buffers (hit+read) | Execution Time |
|---|---|---|---|---|
| `WHERE pref_code='13'` | `roads_p_13` のみ | **Append 無し**（1子だけ） | **12,795** (224+12,571) | 77.7 ms |
| `WHERE pref_code IN ('13','14')` | `_13`,`_14` | Parallel Append（2子） | 23,250 (1,071+22,179) | 53.3 ms |
| （絞り込みなし） | 5子すべて | Parallel Append（5子） | **36,455** (11,120+25,335) | 98.9 ms |

## 結論

- **pruning の証拠は「プランからパーティションが消える」こと**。`pref_code='13'` では
  `roads_p_13` **1子だけ**が計画に載り、他4子（11/12/14/default）は**計画時に除去**される。
  残るのが1子なので束ねる `Append` ノード自体が現れない。絞らないと5子が `Parallel Append` に並ぶ。
- **効果は Buffers（触ったページ数）で単調に出る**: 1子 12,795 < 2子 23,250 < 5子 36,455。
  '13' だけなら全体の約35%のページで済む（≈65%削減）。GISTベンチ同様、**実行時間はノイズが大きく
  （C<A が起きる）、信頼できるのは Buffers という物理量**。
- 補足: 絞ったスキャンに残る `Filter: (pref_code='13')` は冗長な再チェックで安価。
  効きの本体は**フィルタでなくパーティション除去**。

## 正直な注意（過信しない）

「パーティション＝速い」ではない。同じ点フィルタは `roads` に `pref_code` の btree 索引を張っても
近い速度が出る。パーティショニングの本質的な利点は速度そのものより:

- **pruning で他パーティションのデータ/索引に一切触れない**（本計測で確認した点）
- **運用**: 県単位の `DROP TABLE 子` で一括削除、VACUUM/索引再構築/並列を子単位で回せる
- **索引が子ごとに小さく分かれる**

点フィルタ1本の速さだけで測ると過大評価になる。「大きな表を鍵で物理分割し、読む範囲と運用単位を
切る技術」と捉えるのが正確。数百万〜規模で「県別に消す/入れ替える」運用が来たとき効く。

## 再現コマンド

```bash
# 1) 追加データ取得・投入（N13 5339 を roads へ。ホストからは DSN を localhost に上書き）
ROADNET_MESH_ZIP_URLS='["https://nlftp.mlit.go.jp/ksj/gml/data/N13/N13-24/N13-24_5339_GEOJSON.zip"]' \
  uv run roadnet download
uv run roadnet convert
ROADNET_DATABASE_URL="postgresql+psycopg://roadnet:roadnet@localhost:5432/roadnet" uv run roadnet load
ROADNET_DATABASE_URL="postgresql+psycopg://roadnet:roadnet@localhost:5432/roadnet" uv run roadnet transform

# 2) N03 4県を admin_area へ（data/n03/ に zip がある前提。無ければ curl で取得）
ROADNET_DATABASE_URL="postgresql+psycopg://roadnet:roadnet@localhost:5432/roadnet" \
  uv run python scripts/load_admin_area.py

# 3) パーティションテーブル構築 + 投入（psql はコンテナ内なので stdin で流す）
docker compose exec -T postgis psql -U roadnet -d roadnet < sql/partition.sql
docker compose exec -T postgis psql -U roadnet -d roadnet < sql/partition_load.sql

# 4) pruning 計測
docker compose exec -T postgis psql -U roadnet -d roadnet \
  -c "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM roads_p WHERE pref_code='13';" \
  -c "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM roads_p;"
```
