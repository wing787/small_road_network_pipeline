# small_road_network_pipeline

国土数値情報 道路データ **N13-2024** をダウンロードし、メッシュごとに
**GeoParquet** へ変換し、パートをストリーミング結合して全国版スタイルの
GeoParquet 1ファイルにまとめる、**動く最小構成**のデータパイプライン。

学習・ポートフォリオ目的のプロジェクトです。スコープは意図的に小さく
してあります: 対象メッシュの URL はハードコード（スクレイピングなし）で、
デフォルトでは小さな3メッシュのみを処理します。

## データ出典

> 「国土数値情報（道路データ N13-2024）」（国土交通省）
> https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N13-2024.html
>
> 本プロジェクトは国土数値情報を利用し、作者が加工したものです。
> データの再配布は国土数値情報の利用規約に従います。

**元データの構造**（2026-07 に実ダウンロードで確認済み）:

| 項目 | 値 |
| --- | --- |
| 配布単位 | 1次メッシュ（4桁）ごとに zip 1つ |
| 各 zip の内容 | `*.geojson`（UTF-8）1つ + `KS-META-*.xml` |
| ジオメトリ | `LineString`（道路中心線） |
| CRS | **JGD2011 地理座標系、EPSG:6668**（経緯度） |
| 属性 | `N13_001` … `N13_008`（下のマッピング参照） |

`convert.py` で適用する属性マッピング（N13 製品仕様書に基づく）:

| 元カラム | 正規化後の名前 | 意味 |
| --- | --- | --- |
| `N13_001` | `registration_date` | データ登録日 |
| `N13_002` | `road_type` | 種別 |
| `N13_003` | `road_classification` | 道路分類 |
| `N13_004` | `road_status` | 道路状態 |
| `N13_005` | `layer_order` | 階層順（地表からの上下関係） |
| `N13_006` | `width_category` | 幅員区分 |
| `N13_007` | `toll_category` | 有料区分 |
| `N13_008` | `secondary_mesh_code` | 二次メッシュ番号 |

`convert.py` はさらに `source_mesh` カラム（zip ファイル名から取った4桁
メッシュコード）を付与するため、すべてのフィーチャは由来ファイルまで
追跡できます。

### デフォルトのメッシュ

全国でも最小クラスの3メッシュ（各 5〜66 KB）をデフォルトとし、デモを
高速に、かつ配布元サーバーに負荷をかけないようにしています:

| メッシュ | URL | zip サイズ | フィーチャ数 |
| --- | --- | --- | --- |
| 3631 | `.../N13-24/N13-24_3631_GEOJSON.zip` | 約5 KB | 19 |
| 3724 | `.../N13-24/N13-24_3724_GEOJSON.zip` | 約22 KB | 620 |
| 3622 | `.../N13-24/N13-24_3622_GEOJSON.zip` | 約66 KB | 800 |

リストは環境変数 `ROADNET_MESH_ZIP_URLS` または `.env` ファイルで
上書きできます。

## インストール

**Python 3.12+** と [uv](https://docs.astral.sh/uv/) が必要です。

```bash
uv sync
```

## 使い方

```bash
uv run roadnet all         # download -> convert -> merge
# あるいはステップごとに:
uv run roadnet download    # -> data/raw/*.zip     （冪等。既存ファイルはスキップ）
uv run roadnet convert     # -> data/parts/*.parquet
uv run roadnet merge       # -> data/output/roads_all.parquet + roads_all.fgb
uv run roadnet load        # -> PostGIS テーブル `roads`（DB の起動が必要。後述）
```

`merge` は同じパート群から **2種類** の出力を生成します:

| ファイル | 形式 | 理由 |
| --- | --- | --- |
| `data/output/roads_all.parquet` | GeoParquet | 列指向の分析用途（DuckDB、pandas、クラウド） |
| `data/output/roads_all.fgb` | FlatGeobuf | 空間インデックス内蔵 — QGIS でのストリーミング表示、bbox フィルタ読み込み |

結果の読み込み:

```python
import geopandas as gpd

gdf = gpd.read_parquet("data/output/roads_all.parquet")
print(len(gdf), gdf.crs)   # 1439  EPSG:6668

fgb = gpd.read_file("data/output/roads_all.fgb")
print(len(fgb))            # 1439

# FGB の空間インデックスの活用例: bbox 内のフィーチャだけを読む
subset = gpd.read_file("data/output/roads_all.fgb", bbox=(122.9, 24.4, 123.0, 24.5))
```

### 設定

すべての設定は `src/roadnet/config.py`（pydantic-settings）にあります。
`ROADNET_` プレフィックス付きの環境変数で上書きできます。例:

```bash
ROADNET_SLEEP_SECONDS=5 ROADNET_DATA_DIR=/tmp/roads uv run roadnet all
```

ネットワーク挙動: 説明的な `User-Agent` を送信し、*実際に*ダウンロード
した場合のみリクエスト間に `sleep_seconds`（デフォルト2秒）の間隔を
空けます。

## アーキテクチャ

I/O と純粋な変換を関数レベルで分離しているため、変換ロジックは
ネットワークもファイルもなしでユニットテストできます:

```
src/roadnet/
  config.py    pydantic-settings: URL、パス、sleep、タイムアウト、User-Agent
  download.py  I/O:   冪等な httpx ダウンロード（既存はスキップ）
  convert.py   変換:  normalize_roads / count_invalid_geometries / crs_epsg
               I/O:   read_mesh_zip (/vsizip) -> メッシュ単位 GeoParquet
  merge.py     変換:  find_cross_mesh_duplicates（純粋ヘルパー）
               I/O:   merge_parts（ストリーミング ParquetWriter）
                      merge_parts_to_flatgeobuf（ストリーミング pyogrio append）
  load.py      変換:  validate_table_name / gist_index_sql（純粋ヘルパー）
               I/O:   load_parts_to_postgis（ストリーミング to_postgis append）
  cli.py       argparse: download / convert / merge / load / all
```

### ストリーミング結合

`merge.py` は全パートをメモリに載せ**ません** — どちらの形式でも、
メモリ上に保持するパートは常に最大1つです:

- **GeoParquet**: **最初のパート**の Arrow スキーマ（GeoParquet の `geo`
  メタデータ含む）を使った単一の `pyarrow.parquet.ParquetWriter` で
  パートを1つずつ書き込む。
- **FlatGeobuf**: `pyogrio.write_dataframe(..., append=True)` でパートを
  1つずつ追記する。pyogrio 0.13 / GDAL 3.12 で検証済み: append は動作し、
  追記後もパック済み空間インデックスが保持される（`fast_spatial_filter`
  ケーパビリティ。bbox クエリは正しい部分集合を返す）。

これは実運用の「数百万フィーチャ」ケースで効いてきます。

### 不正ジオメトリ

`count_invalid_geometries` は欠損・空・不正なジオメトリを**報告するだけ**
です（メッシュごとに警告ログ）。修復は行わないため、元データが暗黙に
書き換わることはありません。（デフォルトの3メッシュは不正0件。）

## 既知の制限

- **GeoParquet の `bbox` メタデータは最初のパート由来のみ。** ストリーミング
  writer が最初のパートの `geo` メタデータを使い回すため、結合ファイルが
  宣言する bbox は最初のメッシュの範囲だけで、全体の範囲になりません。
  ジオメトリデータ自体は正しく（`gdf.total_bounds` は正確）、メタデータの
  ヒントが狭いだけです。修正には union bbox を計算して `geo` メタデータを
  書き直す必要があり、MVP のスコープ外としています。
- **FlatGeobuf の追記コストは線形以上に増えうる。** GDAL の FGB append は
  追記のたびに内部でファイルを再構築（空間インデックスの再ソート）する
  ことがあり、多数のパートを結合すると総書き込みコストが O(総行数) を
  超えることがあります。MVP スケール（数パート）では問題なし。数千
  パート／数千万行を結合する前に再検討してください（例: 1パスでまとめて
  書く、`ogr2ogr` で後処理する）。
- **スクレイピングなし。** メッシュ URL はハードコードです。実運用の
  パイプラインならダウンロードページからメッシュを列挙するはずです。
- **メッシュ跨ぎの重複は検出のみ。** `find_cross_mesh_duplicates` は
  複数メッシュで共有される同一ジオメトリを検出しますが、パイプラインは
  それらを削除しません（N13 には安全に重複排除できる安定したグローバル
  フィーチャ ID がないため）。

## Docker

`pyogrio` の wheel は GDAL を同梱しているため、OSGeo/GDAL ベースイメージは
不要です。Dockerfile はマルチステージ構成（uv の現行公式パターン:
`ghcr.io/astral-sh/uv` から `uv` バイナリをコピー、キャッシュマウント付き
`uv sync --locked`）:

| ステージ | 内容 | ビルド |
| --- | --- | --- |
| `runtime`（デフォルト） | パイプラインのみ、開発ツールなし | `docker build -t roadnet .` |
| `test` | + pytest/ruff/mypy と `tests/`、`CMD pytest` | `docker build --target test -t roadnet-test .` |

```bash
docker build -t roadnet .

# パイプライン全体を実行し、データをホスト側ディレクトリに永続化:
docker run --rm -v "$(pwd)/data:/app/data" roadnet all

# 1ステップだけ:
docker run --rm -v "$(pwd)/data:/app/data" roadnet download

# テストスイートをコンテナ内で実行:
docker build --target test -t roadnet-test .
docker run --rm roadnet-test
```

## PostGIS (docker compose)

`compose.yaml` は PostGIS 17 / 3.5 のデータベースとパイプラインイメージを
起動します。

> **開発専用の認証情報。** `compose.yaml` の `roadnet`/`roadnet` という
> ユーザー・パスワード・データベース名は、ローカル開発用のハードコード
> されたデフォルトです。この構成を localhost の外に公開したり、認証情報を
> 他所で使い回したりしないでください。

> 公式の `postgis/postgis` イメージは amd64 のみの公開で Apple Silicon
> （arm64）版がないため、compose では `imresamu/postgis` を使っています —
> 同じ docker-postgis プロジェクトのマルチアーキビルドで、環境変数も
> 同一です。

```bash
docker compose up -d postgis            # DB 起動（名前付きボリューム `pgdata` にデータ永続化）
docker compose run --rm pipeline load   # data/parts/*.parquet をテーブル `roads` にストリーム投入
docker compose exec postgis psql -U roadnet -d roadnet \
  -c "SELECT count(*) FROM roads;" \
  -c "SELECT Find_SRID('public','roads','geometry');"
docker compose down                     # 停止。ボリュームは残る（`-v` を付けると削除）
```

`roadnet load` は `GeoDataFrame.to_postgis`（SQLAlchemy 2 + psycopg 3 +
GeoAlchemy2）でパートを1つずつストリーム投入します: 最初のパートで
テーブルを置き換えるため再実行しても冪等、残りは追記、最後にジオメトリ
カラムへ GIST インデックスを作成します。SRID 6668 はパートから引き継がれ
ます。

接続設定は `ROADNET_DATABASE_URL` から読みます。デフォルトは compose の
サービス（`@postgis:5432`）を指します。ホスト側から `load` を実行する
場合は:

```bash
ROADNET_DATABASE_URL=postgresql+psycopg://roadnet:roadnet@localhost:5432/roadnet \
  uv run roadnet load
```

## 開発

```bash
uv run pytest        # 22テスト。ネットワーク・DB 不要（合成 GeoDataFrame を使用）
uv run ruff check .
uv run mypy src tests
```
